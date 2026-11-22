"""Slash-command layer for Venus personas.

Ordinary text is returned as ``None`` so the caller can route it to the
conversation model instead. Storage lives in the caller-supplied SQLite connection; the
persona and user identifiers are opaque strings and every statement is fully
parameterized, so hostile input is data and never executed.

Privacy: all reads, writes and deletes are filtered by the
``(persona, user_id)`` pair, and replies only ever describe the requesting
user's own entries. Response text is clipped so a long memory can never turn
into an unbounded reply.
"""

import re

from .affect import affect_command
from .long_memory import MAX_CONTENT_LEN, add_memory, delete_memory, init_memory, list_memories
from .proactive import (
    disable_schedule,
    init_proactive,
    set_random_schedule,
    set_schedule,
)
from .auto_memory import set_auto_enabled
from .privacy import detect, safe_reply
from .profile import (
    clear_profile,
    describe_profile,
    get_profile,
    init_profile,
    set_field,
)
from .web_settings import init_web_settings, set_enabled

__all__ = ["handle_command", "TIMEZONE"]

# Daily proactive time entered by the user is interpreted in this zone.
TIMEZONE = "Asia/Shanghai"

_MAX_LISTED = 20      # memory entries described by one /记忆 reply
_MAX_SNIPPET = 60     # characters of each entry shown
_MAX_REPLY = 1200     # hard cap for any single reply

_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")

_HELP_TEXT = (
    "可用命令：\n"
    "/记住 内容 —— 让我长期记住这件事\n"
    "/记忆 —— 列出我记住的内容和编号\n"
    "/忘记 编号 —— 删除指定编号的记忆\n"
    "/修改记忆 编号 新内容 —— 修改指定编号的记忆\n"
    "/自动记忆 开启 或 关闭 —— 自动提取偏好（默认开启）\n"
    "/称呼 名字 —— 设置我希望怎么称呼你\n"
    "/风格 描述 —— 设置你偏好的交流方式，例如短句、少用表情\n"
    "/边界 描述 —— 设置不想聊的话题或需要避开的内容\n"
    "/画像 —— 查看个性化设置；/画像 清除 可全部删除\n"
    "/心情 查看、开启、关闭、重置 —— 心情模拟（默认开启，需 AnimaFlux）\n"
    "/主动 开启 —— 随机模式：北京时间 19:00-21:00 的晚间窗口随机出现，每天最多 1 次（默认开启）\n"
    "/主动 开启 HH:MM —— 兼容旧版：按指定的固定时间问候\n"
    "/主动 关闭 —— 停止主动消息\n"
    "/联网 开启 —— 开启联网搜索（默认关闭；搜索词会发送给外部搜索服务商，可能产生费用）\n"
    "/联网 关闭 —— 关闭联网搜索\n"
    "/关于 —— 查看 AI 身份与本机数据说明\n"
    "/帮助 —— 显示本列表"
)

_ABOUT_TEXT = (
    "我是运行在这台电脑上的 AI 聊天伴侣，角色人设只是发送给模型的提示词。\n"
    "普通对话会发送给你配置的模型服务；聊天记录、长期记忆和画像保存在本机 "
    "SQLite，未加密。发送前会拦截明显的密码、验证码、API 密钥、令牌、"
    "身份证、银行卡、手机号和邮箱，这些内容不会发送或保存。\n"
    "你可以用 /记忆 查看和删除长期记忆，用 /画像 查看和清除个性化设置。"
)

# Enabling web search must disclose that the model's search terms are sent to
# an external provider and may carry a cost, and that proactive sharing is a
# separate opt-in. Kept as module constants so the wording cannot drift.
_WEB_ENABLE_REPLY = (
    "已开启联网搜索。请注意：联网搜索会把你的搜索词发送给外部搜索服务商，"
    "可能产生额外费用；请只搜索你愿意对外提供的内容。"
    "主动分享是另一项独立设置，仍需单独发送 /主动 开启 才会开启，"
    "发送 /联网 关闭 可关闭联网搜索。"
)
_WEB_DISABLE_REPLY = (
    "已关闭联网搜索，我不会再把你的搜索词发送给外部搜索服务商。"
    "主动分享若仍开启，需用 /主动 关闭 单独停止。"
)


def handle_command(db, persona, user_id, text):
    """Handle one incoming message.

    Returns ``None`` when ``text`` is not a command, so the caller keeps its
    normal conversation path. Otherwise returns a bounded reply string. Only
    the explicit commands below touch stored data.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    name, _, rest = stripped[1:].partition(" ")
    rest = rest.strip()
    handler = {
        "记住": _remember,
        "记忆": _list,
        "忘记": _forget,
        "修改记忆": _correct,
        "主动": _proactive,
        "自动记忆": _automatic,
        "称呼": _display_name,
        "风格": _style,
        "边界": _boundaries,
        "画像": _profile,
        "心情": affect_command,
        "联网": _web,
        "关于": _about,
        "帮助": _help,
    }.get(name)
    if handler is None:
        return _clip("未识别的命令。发送 /帮助 查看可用命令。")
    _ensure_schema(db)
    return _clip(handler(db, persona, user_id, rest))


def _ensure_schema(db):
    """Create the memory, profile and scheduling tables if absent (idempotent)."""
    init_memory(db)
    init_profile(db)
    init_proactive(db)
    init_web_settings(db)
    db.commit()


def _remember(db, persona, user_id, content):
    if content == "":
        return "格式：/记住 想让我记住的内容，例如 /记住 我喜欢猫"
    labels = detect(content)
    if labels:
        return safe_reply(labels)
    if len(content) > MAX_CONTENT_LEN:
        return f"这段内容超过 {MAX_CONTENT_LEN} 字，请精简后再 /记住。"
    with db:
        memory_id = add_memory(db, persona, user_id, content,
                               category="fact", importance=4, source="explicit")
    return f"已记住（编号 {memory_id}）：{_snippet(content)}"


def _list(db, persona, user_id, _rest):
    memories = list_memories(db, persona, user_id)
    if not memories:
        return "我还没有记住任何内容。用 /记住 内容 告诉我就行。"
    lines = [f"[{memory_id}] {_snippet(content)}" for memory_id, content in memories[-_MAX_LISTED:]]
    shown = len(lines)
    header = f"我记得 {len(memories)} 条：" if shown == len(memories) else f"最近的 {shown} 条（更早的已省略）："
    lines.insert(0, header)
    lines.append("用 /忘记 编号 可以删除某条。")
    return "\n".join(lines)


def _forget(db, persona, user_id, rest):
    memory_id = _parse_id(rest)
    if memory_id is None:
        return "格式：/忘记 编号，先用 /记忆 查看编号。"
    with db:
        deleted = delete_memory(db, persona, user_id, memory_id)
    if deleted:
        return f"已删除编号 {memory_id} 的记忆。"
    return f"没有找到编号 {memory_id} 的记忆，它可能已被删除。"


def _correct(db, persona, user_id, rest):
    id_text, _, content = rest.partition(" ")
    memory_id = _parse_id(id_text)
    if memory_id is None or content.strip() == "":
        return "格式：/修改记忆 编号 新内容，先用 /记忆 查看编号。"
    labels = detect(content)
    if labels:
        return safe_reply(labels)
    if len(content) > MAX_CONTENT_LEN:
        return f"这段内容超过 {MAX_CONTENT_LEN} 字，请精简后再 /修改记忆。"
    # In-place, scoped UPDATE: the id is kept and the match is restricted to
    # this (persona, user_id) so no other scope's row can be touched. The
    # reply for a zero-row update is identical to a genuinely missing id, so
    # it never reveals whether the id exists in a different scope. The raw
    # content is stored verbatim (newlines and all) -- only the display
    # snippet is flattened. ``with db`` commits the correction to disk.
    with db:
        cur = db.execute(
            "UPDATE memories SET content = ? "
            "WHERE id = ? AND persona = ? AND user_id = ?",
            (content, memory_id, persona, user_id),
        )
    if cur.rowcount > 0:
        return f"已修改编号 {memory_id} 的记忆：{_snippet(content)}"
    return f"没有找到编号 {memory_id} 的记忆，它可能已被删除。"


def _proactive(db, persona, user_id, rest):
    action, _, argument = rest.partition(" ")
    argument = argument.strip()
    if action == "关闭":
        if argument:
            return _proactive_format()
        # Create a durable opt-out even when default-on scheduling has not
        # written a row yet; the stored mode/time is preserved if it exists.
        disable_schedule(db, persona, user_id, TIMEZONE)
        return "已关闭主动消息，我不会再定时找你。"
    if action != "开启":
        return _proactive_format()
    if argument == "":
        # Bare form opts into the evening random schedule: the concrete minute
        # is picked lazily per day by slot_due_and_claim.
        set_random_schedule(db, persona, user_id, True, TIMEZONE)
        return ("已开启主动消息：会参考你最近的聊天频率，在北京时间 19:00 到 21:00 "
                "的晚间窗口随机出现，每天最多 1 次；正在聊天或刚聊完时不会插话。"
                "发送 /主动 关闭 可以停止。")
    parsed = _parse_clock(argument)
    if parsed is None:
        return _proactive_format()
    hour, minute = parsed
    set_schedule(db, persona, user_id, True, hour, minute, TIMEZONE)
    return f"已开启主动消息，参考近期聊天频率，最多每天 {_format_clock(hour, minute)}（{TIMEZONE}）问候一次。发送 /主动 关闭 可以停止。"


def _automatic(db, persona, user_id, rest):
    if rest not in ('开启', '关闭'):
        return '格式：/自动记忆 开启 或 /自动记忆 关闭'
    set_auto_enabled(db, persona, user_id, rest == '开启')
    return ('已开启自动记忆：会尝试保存明确的偏好，可用 /记忆 查看和 /忘记 编号 删除。'
            if rest == '开启' else '已关闭自动记忆；已有记忆不会自动删除。')


def _web(db, persona, user_id, rest):
    if rest == "开启":
        set_enabled(db, persona, user_id, True)
        return _WEB_ENABLE_REPLY
    if rest == "关闭":
        set_enabled(db, persona, user_id, False)
        return _WEB_DISABLE_REPLY
    return _web_format()


def _profile_command(db, persona, user_id, field, label, command, rest):
    """Shared handler for the three free-text profile fields."""
    if rest == "":
        current = get_profile(db, persona, user_id)[field]
        if current:
            return f"当前{label}：{current}"
        return f"还没有设置{label}。发送 /{command} 内容 即可设置。"
    labels = detect(rest)
    if labels:
        return safe_reply(labels)
    if rest == "清除":
        try:
            set_field(db, persona, user_id, field, "")
        except ValueError as exc:
            return f"设置失败：{exc}"
        return f"已清除{label}。"
    try:
        set_field(db, persona, user_id, field, rest)
    except ValueError as exc:
        return f"设置失败：{exc}"
    return f"已设置{label}：{_snippet(rest)}"


def _display_name(db, persona, user_id, rest):
    return _profile_command(db, persona, user_id, "display_name", "称呼", "称呼", rest)


def _style(db, persona, user_id, rest):
    return _profile_command(db, persona, user_id, "style", "交流偏好", "风格", rest)


def _boundaries(db, persona, user_id, rest):
    return _profile_command(db, persona, user_id, "boundaries", "边界", "边界", rest)


def _profile(db, persona, user_id, rest):
    if rest == "清除":
        clear_profile(db, persona, user_id)
        return "已清除你的全部画像设置，不影响聊天记录和长期记忆。"
    if rest:
        return "格式：/画像 查看，或 /画像 清除 删除全部画像设置。"
    profile = get_profile(db, persona, user_id)
    text = describe_profile(profile)
    if not text:
        return ("你还没有设置画像。可以用 /称呼 名字、/风格 描述、/边界 描述 "
                "告诉我你希望怎样被对待。")
    return ("你的画像（仅保存在本机）：\n" + text
            + "\n发送 /画像 清除 可以全部删除。")


def _about(db, persona, user_id, _rest):
    return _ABOUT_TEXT


def _help(db, persona, user_id, _rest):
    return _HELP_TEXT


def _parse_id(rest):
    if not rest.isdigit():
        return None
    try:
        return int(rest)
    except ValueError:  # pragma: no cover - overflow guard
        return None


def _parse_clock(value):
    """Return ``(hour, minute)`` for a 24-hour ``HH:MM`` string, else None."""
    match = _TIME_PATTERN.match(value)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _format_clock(hour, minute):
    return "%02d:%02d" % (hour, minute)


def _proactive_format():
    return ("格式：/主动 开启（随机模式，北京时间 19:00-21:00 之间随机出现，每天最多 1 次）"
            "或 /主动 开启 HH:MM（24 小时制，例如 /主动 开启 19:30，兼容旧版固定时间）"
            "或 /主动 关闭")


def _web_format():
    return "格式：/联网 开启 或 /联网 关闭"


def _snippet(content):
    flat = " ".join(content.split())
    return flat if len(flat) <= _MAX_SNIPPET else flat[:_MAX_SNIPPET] + "…"


def _clip(reply):
    return reply if len(reply) <= _MAX_REPLY else reply[:_MAX_REPLY] + "…"
