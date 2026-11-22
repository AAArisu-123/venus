"""QQ private-chat client built on Tencent's botpy SDK."""

import asyncio
import logging
import re
import sys
from contextlib import closing
from pathlib import Path

import botpy

from .__main__ import DEFAULT_PERSONA, answer, connect_database
from .commands import TIMEZONE, handle_command
from .config import DEFAULT_DB, DEFAULT_PAIRING_DB, REQUIRED_ENV_NAMES, load_config
from .env_file import load_env_file
from .qq_access import AccessGate
from .qq_handler import QQHandler
from .proactive import ensure_default_schedule
from .proactive_runner import loop_forever
from .proactive_composer import compose_opener
from .pairing import connect_database as connect_pairing_database, is_allowed as pairing_is_allowed
from .activity import init_activity, record_activity
from .presence import init_presence, note_user_message
from datetime import datetime, timezone


_LOG = logging.getLogger(__name__)
FALLBACK_REPLY = '刚才走神了一下。你再说一遍，我在听。'
MAX_QQ_CHARS = 900
MAX_QQ_PART_CHARS = 120

_BOLD = re.compile(r'(\*\*|__)(.*?)\1')
_HEADING = re.compile(r'(?m)^#{1,6}\s*')
_BULLET = re.compile(r'(?m)^\s*[-*•]\s+')
_CODE_FENCE = re.compile(r'(?m)^```.*$')
_INLINE_CODE = re.compile(r'`([^`]*)`')
_BLANK_LINES = re.compile(r'\n{3,}')


def clean_reply(text):
    """Make model text readable in a QQ chat bubble.

    Removes the most visible Markdown markers, collapses blank lines and caps
    the result at a sentence boundary. It never logs or returns an error that
    contains the original message.
    """
    if not isinstance(text, str):
        return ''
    cleaned = text.replace('\r\n', '\n').strip()
    cleaned = _CODE_FENCE.sub('', cleaned)
    cleaned = _INLINE_CODE.sub(r'\1', cleaned)
    cleaned = _BOLD.sub(r'\2', cleaned)
    cleaned = _HEADING.sub('', cleaned)
    cleaned = _BULLET.sub('', cleaned)
    cleaned = _BLANK_LINES.sub('\n\n', cleaned).strip()
    if len(cleaned) > MAX_QQ_CHARS:
        cut = cleaned[:MAX_QQ_CHARS]
        for separator in ('。', '！', '？', '\n', '.', '!', '?'):
            index = cut.rfind(separator)
            if index >= MAX_QQ_CHARS * 0.6:
                cut = cut[:index + 1]
                break
        cleaned = cut.rstrip() + '…'
    return cleaned.strip()


def split_reply(text, max_chars=MAX_QQ_PART_CHARS):
    """Split a long reply into at most two natural QQ bubbles.

    The split is made at a sentence boundary near the character budget, so
    two short thoughts feel like consecutive chat messages instead of one
    wall of text. If no usable boundary exists, the reply stays intact.
    """
    if not isinstance(text, str):
        return ['']
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return [cleaned]
    window = cleaned[:max_chars]
    cut = max(window.rfind(separator) for separator in ('。', '！', '？', '\n', '.', '!', '?'))
    if cut < max_chars * 0.4:
        return [cleaned]
    first = cleaned[:cut + 1].strip()
    rest = cleaned[cut + 1:].strip()
    if not rest:
        return [first]
    return [first, rest]


PAIRING_PROMPT = (
    '配对码：{code}\n'
    '请让机主在这台电脑上批准后，我们就可以开始聊天了。'
)


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _parse_message(message):
    """Read the C2C object's fields manually, returning (id, openid, text).

    Returns ``None`` for malformed payloads or messages with no text body
    (for example, attachment-only messages). Only the text is stripped.
    """
    if message is None:
        return None
    message_id = getattr(message, 'id', None)
    author = getattr(message, 'author', None)
    user_id = getattr(author, 'user_openid', None) if author is not None else None
    content = getattr(message, 'content', None)
    if not _filled(message_id) or not _filled(user_id) or not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    return (message_id, user_id, text)


def build_handler(config, api_for, db_path=None, persona_path=None):
    """Create the QQHandler used to serialize replies per user.

    ``api_for(message_id)`` resolves the API object used to send the reply.
    The model call runs in a worker thread and opens/closes its own SQLite
    connection on every request, so no connection is shared across threads.
    """
    if not callable(api_for):
        raise TypeError('api_for must be callable')
    db_path = DEFAULT_DB if db_path is None else db_path
    persona_path = DEFAULT_PERSONA if persona_path is None else persona_path
    api_key = config['api_key']
    base_url = config['base_url']
    model = config['model']

    async def reply(user_id, text):
        def work():
            try:
                with closing(connect_database(db_path)) as db:
                    command_result = handle_command(
                        db, str(Path(persona_path).resolve()), user_id, text
                    )
                    if command_result is not None:
                        return command_result
                    content = answer(db, persona_path, user_id, text,
                                     base_url, model, api_key)
                    if isinstance(content, str) and content.strip():
                        return content
                    return FALLBACK_REPLY
            except Exception as exc:
                # Keep failures silent to the user but never leave the chat
                # without a reply. Only the exception type is logged.
                _LOG.debug('reply failed: %s', type(exc).__name__)
                return FALLBACK_REPLY
        return await asyncio.to_thread(work)

    async def send(user_id, message_id, content):
        api = api_for(message_id)
        if api is None:
            return
        parts = split_reply(clean_reply(content) or FALLBACK_REPLY)
        for index, part in enumerate(parts, start=1):
            payload = {
                'openid': user_id,
                'msg_type': 0,
                'msg_id': message_id,
                'content': part,
            }
            if len(parts) > 1:
                payload['msg_seq'] = index
            await api.post_c2c_message(**payload)
            if index < len(parts):
                # A short gap makes two bubbles feel like a person typing,
                # not a single reply split by the client.
                await asyncio.sleep(0.4)

    return QQHandler(reply, send)


def build_proactive_generator(config, db_path, persona_path):
    async def generate(user_id):
        def work():
            with closing(connect_database(db_path)) as db:
                return compose_opener(
                    db, persona_path, user_id, config['base_url'],
                    config['model'], config['api_key'], mode='proactive')
        return await asyncio.to_thread(work)
    return generate


class Client(botpy.Client):
    """botpy client wired to Venus with an allowlist and per-user locking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handler = None
        self.allowed_openids = frozenset()
        self.gate = None
        self._apis = {}
        self._proactive_task = None
        self._proactive_generate = None
        self._proactive_db = DEFAULT_DB
        self._pairing_db = DEFAULT_PAIRING_DB
        self._proactive_persona = str(DEFAULT_PERSONA.resolve())

    def configure(self, config, db_path=None, persona_path=None):
        """Install the access gate and handler before ``run``."""
        self.allowed_openids = frozenset(config['allowed_openids'])
        self._pairing_db = config['pairing_db']
        self.gate = AccessGate(self.allowed_openids, self._pairing_db)
        self._proactive_db = db_path if db_path is not None else DEFAULT_DB
        self._proactive_persona = str(Path(persona_path if persona_path is not None else DEFAULT_PERSONA).resolve())
        self.handler = build_handler(config, self._take_api, db_path, persona_path)
        self._proactive_generate = build_proactive_generator(
            config, self._proactive_db, self._proactive_persona)

    def _authorized_for_proactive(self, user_id):
        if self.allowed_openids:
            return user_id in self.allowed_openids
        try:
            with closing(connect_pairing_database(self._pairing_db)) as db:
                return pairing_is_allowed(db, user_id)
        except Exception:
            return False

    async def on_ready(self):
        if self.handler is not None and (self._proactive_task is None or self._proactive_task.done()):
            self._proactive_task = asyncio.create_task(loop_forever(
                self._proactive_db, self._proactive_persona, self.api.post_c2c_message,
                authorized=self._authorized_for_proactive, generate=self._proactive_generate))

    async def close(self):
        if self._proactive_task is not None:
            self._proactive_task.cancel()
            try:
                await self._proactive_task
            except asyncio.CancelledError:
                pass
        await super().close()

    def _take_api(self, message_id):
        return self._apis.pop(message_id, None)

    async def on_c2c_message_create(self, message):
        handler = self.handler
        if handler is None:
            return
        parsed = _parse_message(message)
        if parsed is None:
            return
        message_id, user_id, text = parsed
        gate = self.gate
        if gate is None:
            return
        kind, code = gate.decide(user_id)
        if kind == 'deny':
            return
        api = getattr(message, '_api', None)
        if api is None or not callable(getattr(api, 'post_c2c_message', None)):
            return
        if kind == 'prompt':
            await api.post_c2c_message(
                openid=user_id,
                msg_type=0,
                msg_id=message_id,
                content=PAIRING_PROMPT.format(code=code),
            )
            return
        try:
            with closing(connect_database(self._proactive_db)) as activity_db:
                init_presence(activity_db)
                note_user_message(
                    activity_db, self._proactive_persona, user_id,
                    datetime.now(timezone.utc))
                if not text.startswith('/'):
                    init_activity(activity_db)
                    record_activity(activity_db, self._proactive_persona, user_id, message_id, datetime.now(timezone.utc))
                    ensure_default_schedule(
                        activity_db, self._proactive_persona, user_id, TIMEZONE
                    )
        except Exception as exc:
            # Activity/default scheduling is best-effort; a locked or
            # corrupt side table must not swallow the actual reply.
            _LOG.debug('activity update failed: %s', type(exc).__name__)
        # A concurrent event with the same id is still in flight. Do not
        # overwrite its api, and do not let this duplicate's cleanup remove
        # it: the first reply must still be delivered through its own api.
        owns_api = message_id not in self._apis
        if owns_api:
            self._apis[message_id] = api
        try:
            await handler.handle(message_id, user_id, text)
        finally:
            if owns_api:
                self._apis.pop(message_id, None)


def ensure_event_loop():
    """Give botpy a current event loop.

    ``botpy.Client.__init__`` calls ``asyncio.get_event_loop()``, and Python
    3.12+ no longer creates one implicitly on the main thread. Every entry
    point that constructs the client (the bot itself and any diagnostic tool)
    must therefore install a loop first.
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main(*, scheduled=False):
    """Validate config, then start the official botpy client."""
    load_env_file(Path(__file__).resolve().parent.parent / '.env')
    try:
        config = load_config()
    except ValueError as exc:
        print(f'QQ 机器人配置错误：{exc}', file=sys.stderr)
        return 2
    intents = botpy.Intents(public_messages=True)
    ensure_event_loop()
    # Never let the SDK create a content-bearing botpy.log in the project
    # directory. The scheduled entry point installs its own status-only log
    # handler; manual runs keep console output only.
    client = Client(intents=intents, ext_handlers=False)
    client.configure(config)
    client.run(appid=config['app_id'], secret=config['app_secret'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
