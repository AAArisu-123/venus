"""Optional AnimaFlux state, scoped in Venus's existing local SQLite database."""

import json
import math
from datetime import datetime, timezone

from .affect_appraisal import FIELDS

try:
    from animaflux import AgentState, StateDelta, StateEngine
except ModuleNotFoundError as exc:
    if exc.name != 'animaflux':
        raise
    AgentState = StateDelta = StateEngine = None


def parse_delta(raw):
    """Treat model output purely as bounded numeric data, never instructions."""
    if not isinstance(raw, str) or len(raw) > 4096:
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    if not isinstance(obj, dict):
        return {}
    result = {}
    for group, fields in FIELDS.items():
        values = obj.get(group)
        if not isinstance(values, dict):
            continue
        bound = 1 if group in ('emotion', 'inner') else 0.35
        clean = {}
        for key in fields:
            value = values.get(key)
            if type(value) is int or (type(value) is float and math.isfinite(value)):
                clean[key] = max(-bound, min(bound, value))
        if clean:
            result[group] = clean
    return result


def _init(db):
    db.execute('CREATE TABLE IF NOT EXISTS affect_state ('
               'persona TEXT NOT NULL, user_id TEXT NOT NULL, enabled INTEGER NOT NULL, '
               'revision INTEGER NOT NULL, state TEXT, PRIMARY KEY (persona, user_id))')


def _ensure_default(db, persona, user_id):
    """Enable the simulated mood by default; an explicit off row wins."""
    _init(db)
    with db:
        db.execute(
            'INSERT OR IGNORE INTO affect_state'
            '(persona, user_id, enabled, revision, state) '
            'VALUES (?, ?, 1, 0, NULL)',
            (persona, user_id),
        )


def snapshot(db, persona, user_id, now=None):
    """Return (revision, decayed state) for an enabled scope without saving decay.

    Mood is on by default; ``/心情 关闭`` writes enabled = 0 and suppresses the
    feature for that exact persona/user scope.
    """
    if StateEngine is None:
        return None
    _ensure_default(db, persona, user_id)
    row = db.execute('SELECT revision, state FROM affect_state '
                     'WHERE persona = ? AND user_id = ? AND enabled = 1',
                     (persona, user_id)).fetchone()
    if row is None:
        return None
    now = now or datetime.now(timezone.utc)
    state = json.loads(row[1]) if row[1] is not None else AgentState(updated_at=now.isoformat()).to_dict()
    return row[0], StateEngine(None, None).decayed(state, now)


def preview(state, changes):
    when = datetime.fromisoformat(state['updated_at'])
    return StateEngine(None, None).apply(state, StateDelta(changes), when)


def commit(db, persona, user_id, revision, state):
    """Compare-and-set: a stale evaluation cannot undo a reset or opt-out."""
    with db:
        cur = db.execute('UPDATE affect_state SET state = ?, revision = revision + 1 '
                         'WHERE persona = ? AND user_id = ? AND enabled = 1 AND revision = ?',
                         (json.dumps(state, allow_nan=False), persona, user_id, revision))
    return cur.rowcount == 1


def describe(state):
    mood = state['emotion']
    inner = state['inner']
    relationship = state['relationship']
    notes = []
    for condition, label in (
        (mood['happiness'] >= 5.35, '有些愉快'),
        (mood['happiness'] <= 4.55, '兴致略低'),
        (mood['sadness'] >= 0.4, '还有一点难过'),
        (mood['anger'] >= 0.45, '有点不快'),
        (mood['anxiety'] >= 0.4, '带着一点不安'),
        (inner['vulnerability'] >= 3.55, '此刻更愿意坦露感受'),
        (inner['sharing_urge'] >= 4.45, '有一点想分享自己的想法'),
        (state['self_state']['self_presence'] >= 5.35, '更愿意表达自己的看法'),
        (relationship['unresolved_tension'] >= 0.45, '近期可能有没聊开的分歧，只有当前上下文相关时才提'),
        (relationship['affection'] >= 5.55 and relationship['familiarity'] >= 1.45, '比刚认识时更有默契'),
        (relationship['trust'] <= 4.5, '表达更谨慎，不推断对方意图'),
    ):
        if condition:
            notes.append(label)
    return '；'.join(notes) if notes else '暂时平静，没有明显的情绪倾向'


def affect_command(db, persona, user_id, action):
    if action not in ('', '查看', '开启', '关闭', '重置'):
        return '格式：/心情 查看、开启、关闭 或 重置。'
    if StateEngine is None:
        return '心情功能暂不可用：此环境未安装 AnimaFlux。'
    _init(db)
    if action in ('开启', '关闭'):
        enabled = int(action == '开启')
        with db:
            db.execute('INSERT INTO affect_state(persona, user_id, enabled, revision, state) '
                       'VALUES (?, ?, ?, 0, NULL) ON CONFLICT(persona, user_id) DO UPDATE SET '
                       'enabled = excluded.enabled, revision = affect_state.revision + 1 '
                       'WHERE affect_state.enabled != excluded.enabled',
                       (persona, user_id, enabled))
        if enabled:
            return ('已开启心情状态。普通聊天会将有限的聊天和相关记忆片段交给现有模型'
                    '额外评估一次，可能增加耗时和 API 费用。/心情 关闭 可停用。')
        return '已关闭心情状态，不再评估或使用该状态；已有状态可用 /心情 重置 清除。'
    if action == '重置':
        with db:
            db.execute('UPDATE affect_state SET state = NULL, revision = revision + 1 '
                       'WHERE persona = ? AND user_id = ?', (persona, user_id))
        return '已重置这段聊天的心情状态。不会删除原有聊天记录或长期记忆，也不会改变开关。'
    current = snapshot(db, persona, user_id)
    if current is None:
        return '心情状态已关闭。发送 /心情 开启 可重新启用。'
    return '当前角色心情（模拟状态，默认开启）：' + describe(current[1]) + '。'
