import argparse
from contextlib import closing
import http.client
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .memory import connect_database, history, save_turn
from .long_memory import init_memory, list_memories, touch_memories
from .memory_recall import recall
from .auto_memory import is_auto_enabled, remember_candidates
from .profile import init_profile, peek_profile
from .prompt import build_messages
from .web_settings import is_enabled as web_enabled
from .web_tool import complete_web, WebToolError
from .persona import load_persona
from .privacy import detect, safe_reply
from . import affect
from . import life
from .affect_appraisal import make_appraisal, should_appraise
from .presence import init_presence, note_assistant_message, note_user_message


DEFAULT_PERSONA = Path(__file__).resolve().parent.parent / 'personas' / 'venus.json'
MAX_CHAT_TOKENS = 400
_LOG = logging.getLogger(__name__)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def answer(db, persona_path, user_id, text, base_url, model, api_key, *,
           life_text=None):
    labels = detect(text)
    if labels:
        # Do not read history, call the model, or save a turn for a message
        # that contains a credential or a high-confidence identifier.
        return safe_reply(labels)
    persona = load_persona(persona_path)
    persona_id = str(Path(persona_path).resolve())
    rows = history(db, persona_id, user_id)
    init_memory(db)
    init_profile(db)
    init_presence(db)
    life.init_life(db)
    # Release the schema/migration write transaction before the model call;
    # otherwise a slow reply could hold SQLite's writer lock.
    db.commit()
    now = datetime.now(timezone.utc)
    note_user_message(db, persona_id, user_id, now)
    relevant = recall(db, persona_id, user_id, text, limit=5)
    if relevant:
        memories = relevant
    else:
        memories = list_memories(db, persona_id, user_id)[-3:]
    profile = peek_profile(db, persona_id, user_id)
    if life_text is None:
        try:
            life_text = life.life_summary(
                db, persona_id, user_id,
                today=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
            )
        except sqlite3.Error:
            life_text = ''
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('模型地址必须是 HTTPS；仅本机测试允许 HTTP，且地址不能包含凭据、查询参数或片段。')
    use_web = web_enabled(db, persona_id, user_id)
    if use_web and parsed.hostname != 'api.deepseek.com':
        raise ValueError('联网功能目前仅支持 DeepSeek 官方服务。')
    pending, affect_text = _apply_affect_context(
        db, persona_id, user_id, persona, rows, memories, text,
        base_url, model, api_key)
    messages = build_messages(persona, profile, memories, rows, text,
                              affect_text=affect_text, web=use_web,
                              life_text=life_text)
    if use_web:
        try:
            content, sources = complete_web(base_url, api_key, messages)
        except WebToolError as exc:
            raise ValueError('联网请求失败，请稍后重试或使用 /联网 关闭。') from exc
        if sources:
            content += '\n来源：' + ' '.join(dict.fromkeys(s['url'] for s in sources[:3]))
    else:
        content = _complete(messages, base_url, model, api_key)
    save_turn(db, persona_id, user_id, text, content)
    try:
        note_assistant_message(db, persona_id, user_id, now)
    except sqlite3.Error:
        _LOG.warning('无法记录对话时间；回复不受影响。')
    if memories:
        try:
            touch_memories(db, persona_id, user_id, [mid for mid, _ in memories])
        except sqlite3.Error:
            _LOG.warning('无法更新记忆使用记录；回复不受影响。')
    if pending is not None:
        try:
            affect.commit(db, persona_id, user_id, *pending)
        except (sqlite3.Error, ValueError):
            _LOG.warning('无法保存角色心情；普通回复不受影响。')
    try:
        auto_enabled = is_auto_enabled(db, persona_id, user_id)
    except sqlite3.Error:
        auto_enabled = False
    if auto_enabled:
        try:
            with db:
                remember_candidates(db, persona_id, user_id, text)
        except (sqlite3.Error, ValueError):
            _LOG.warning('无法更新自动记忆；回复不受影响。')
    return content


def _apply_affect_context(db, scope, user_id, persona, rows, memories, text,
                          base_url, model, api_key):
    """Return ``(pending_update, affect_text)`` for prompt assembly.

    ``pending_update`` is the compare-and-set payload to commit after a
    successful reply; ``affect_text`` is the short mood description injected
    into the persona layer. Both are empty/None when the feature is off or
    unreadable.
    """
    try:
        current = affect.snapshot(db, scope, user_id)
        if current is None:
            return None, ''
        revision, mood = current
        pending = None
        if should_appraise(text, len(rows)):
            try:
                raw = make_appraisal(
                    lambda prompt: _complete(prompt, base_url, model, api_key, appraisal=True),
                    persona, affect.describe(mood), rows, [value for _, value in memories], text,
                )
                changes = affect.parse_delta(raw)
                if changes:
                    mood = affect.preview(mood, changes)
                    pending = (revision, mood)
            except ValueError:
                _LOG.info('情绪评估不可用；沿用已有状态。')
        return pending, affect.describe(mood)
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        _LOG.warning('无法读取角色心情，本轮改用普通对话。')
        return None, ''


def _complete(messages, base_url, model, api_key, *, appraisal=False):
    endpoint = base_url.rstrip('/') + '/chat/completions'
    payload = {'model': model, 'messages': messages}
    if appraisal:
        payload.update(response_format={'type': 'json_object'}, max_tokens=256)
    else:
        # A safety cap, not the style target. The prompt asks for 1-2 short
        # sentences; this stops a runaway reply from becoming a wall of text.
        payload['max_tokens'] = MAX_CHAT_TOKENS
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(endpoint, data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5 if appraisal else 60) as response:
            result = json.load(response)
        content = result['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('模型未返回有效文字。')
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError('模型请求失败，请检查网络、模型服务与配置。') from exc
    except (OSError, http.client.HTTPException, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('模型请求失败，请检查网络、模型服务与配置。') from exc
    return content


def main():
    parser = argparse.ArgumentParser(description='Venus 本地文字对话原型')
    parser.add_argument('--persona', type=Path, default=DEFAULT_PERSONA, help='自定义人设 JSON 文件')
    parser.add_argument('--db', default='data/venus.sqlite3', help='本地对话数据库路径')
    parser.add_argument('--user', default='local', help='本地用户标识（不是身份认证）')
    parser.add_argument('--message', help='发送一条消息并退出；省略则进入交互模式')
    args = parser.parse_args()
    key = os.environ.get('VENUS_API_KEY', '')
    base = os.environ.get('VENUS_BASE_URL', '')
    model = os.environ.get('VENUS_MODEL', '')
    if not all((key, base, model)):
        parser.exit(2, '请设置 VENUS_API_KEY、VENUS_BASE_URL、VENUS_MODEL 环境变量。\n')
    try:
        persona = load_persona(args.persona)
        with closing(connect_database(args.db)) as db:
            def send(text):
                if not text.strip():
                    return
                print(answer(db, args.persona, args.user, text, base, model, key), flush=True)
            if args.message is not None:
                send(args.message)
            else:
                print(f"正在与 {persona['name']} 聊天，输入 /quit 退出。聊天内容会发送给模型服务并保存在本机。", flush=True)
                while True:
                    try:
                        text = input('你：')
                    except EOFError:
                        break
                    if text.strip() == '/quit':
                        break
                    try:
                        send(text)
                    except ValueError as exc:
                        print(f'发送失败：{exc}', file=sys.stderr)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'错误：{exc}\n')


if __name__ == '__main__':
    main()
