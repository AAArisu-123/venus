"""Owner-facing self-check for the local Venus setup.

Every check that is easy to get wrong by hand is one command here instead of an
ad-hoc script: configuration, persona, database, proactive schedule, the log
destination and the paired users are all reported locally. Two network checks
are opt-in:

``--api``
    Send one tiny chat completion through the configured model endpoint.

``--send-test``
    Send one QQ private message over plain HTTPS. This talks to the QQ bot API
    directly (access token + ``/v2/users/{openid}/messages``) instead of
    opening a gateway, so the scheduled bot may keep running while it checks
    the delivery path.

Usage:
    python -m venus.doctor [--api] [--send-test] [--openid ID]
                           [--env PATH] [--db PATH] [--pairing-db PATH]

Secrets never reach stdout: the app id and openids are masked, the API key and
client secret are never printed, and only error codes (not bodies) are echoed.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Tuple

from .env_file import load_env_file
from .memory import connect_database
from .pairing import approved_openids
from .pairing import connect_database as connect_pairing_database
from .persona import load_persona
from .qq_bot import DEFAULT_PERSONA, load_config
from .qq_service import open_status_handler
from .__main__ import _complete

DEFAULT_ENV = Path(__file__).resolve().parent.parent / '.env'
TOKEN_URL = 'https://bots.qq.com/app/getAppAccessToken'
API_BASE = 'https://api.sgroup.qq.com'
TEST_MESSAGE = '维纳斯自检消息，收到请忽略。'
TIMEOUT_SECONDS = 30

USAGE = (
    'usage: python -m venus.doctor [--api] [--send-test] [--openid ID]'
    ' [--env PATH] [--db PATH] [--pairing-db PATH] [--log-dir PATH]'
)

Check = Tuple[str, bool, str]


def mask(value):
    """Mask an identifier so it can be shown in logs and terminals."""
    if not isinstance(value, str) or not value:
        return '（空）'
    if len(value) <= 6:
        return '****'
    return value[:4] + '…' + value[-2:]


def resolve_openids(config):
    """Return the openids this bot serves, allowlist first, then pairings.

    The allowlist wins when configured; otherwise the pairing database decides,
    which is the normal setup for a personal bot. A missing pairing database is
    reported as "no users" rather than being created as a side effect.
    """
    allowed = sorted(config.get('allowed_openids') or ())
    if allowed:
        return allowed
    path = config.get('pairing_db')
    if not path or not Path(path).exists():
        return []
    with closing(connect_pairing_database(path)) as db:
        return approved_openids(db)


def check_config(config):
    model = config.get('model') or '（未配置）'
    return True, f'模型 {model}，appid {mask(config.get("app_id"))}'


def check_persona(persona_path):
    text = Path(persona_path).read_text(encoding='utf-8')
    persona = load_persona(persona_path)
    return True, f'{Path(persona_path).name}（{persona.get("name", "未命名")}，{len(text)} 字节）'


def check_database(db_path):
    path = Path(db_path).expanduser()
    if not path.exists():
        return False, f'{path} 尚未创建（第一次聊天时自动建立）'
    with closing(connect_database(str(path))) as db:
        count = db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
    return True, f'{path}（{count} 条消息）'


def check_schedule(db_path, timezone_name='Asia/Shanghai'):
    path = Path(db_path).expanduser()
    if not path.exists():
        return True, '尚未初始化（第一次正常聊天后自动建立随机计划）'
    with closing(connect_database(str(path))) as db:
        try:
            rows = db.execute(
                'SELECT enabled, mode FROM proactive_schedule').fetchall()
        except Exception:
            return True, '尚未初始化（第一次正常聊天后自动建立随机计划）'
        if not rows:
            return True, '没有计划（第一次正常聊天后自动建立）'
        enabled = sum(1 for row in rows if row[0])
        random_mode = sum(1 for row in rows if row[1] == 'random')
        return True, f'{enabled}/{len(rows)} 个用户开启，其中 {random_mode} 个为晚间随机模式'


def check_log(folder=None):
    folder = folder or Path(os.environ.get('LOCALAPPDATA', '')) / 'Venus' / 'logs'
    handler = open_status_handler(Path(folder))
    try:
        return True, str(handler.baseFilename)
    finally:
        handler.close()


def check_users(config):
    openids = resolve_openids(config)
    if not openids:
        return False, '没有可服务的用户（未配置 allowlist，也没有已配对用户）'
    return True, '，'.join(mask(openid) for openid in openids)


def collect_checks(config, *, db_path, persona_path, log_folder=None):
    """Run every local (offline) check and return ``[(name, ok, detail)]``."""
    checks = [
        ('配置', lambda: check_config(config)),
        ('人设', lambda: check_persona(persona_path)),
        ('数据库', lambda: check_database(db_path)),
        ('主动计划', lambda: check_schedule(db_path)),
        ('日志', lambda: check_log(log_folder)),
        ('用户', lambda: check_users(config)),
    ]
    results = []
    for name, run in checks:
        try:
            ok, detail = run()
        except Exception as exc:
            ok, detail = False, f'检查失败（{type(exc).__name__}）'
        results.append((name, ok, detail))
    return results


def _post_json(url, payload, headers=None, *, timeout=TIMEOUT_SECONDS):
    """POST a JSON body and return the decoded JSON response.

    Only the HTTP status and the API's error code are surfaced; response bodies
    are never echoed, so a token or secret cannot leak through an error path.
    """
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json', **(headers or {})},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise RuntimeError(f'接口返回错误状态 {status}') from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f'无法连接接口：{exc.reason}') from None
    except OSError as exc:
        raise RuntimeError(f'接口通信失败：{type(exc).__name__}') from None
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError('接口返回内容无法解析') from None
    if isinstance(data, dict) and data.get('code') not in (None, 0):
        raise RuntimeError(f'接口返回错误码 {data.get("code")}')
    return data


def probe_model(base_url, model, api_key, *, complete=None):
    """Ask the configured endpoint for one short reply."""
    complete = complete or _complete
    content = complete(
        [{'role': 'user', 'content': '只回复两个字：正常'}],
        base_url, model, api_key,
    )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError('模型返回了空内容')
    return content.strip()[:40]


def request_access_token(app_id, app_secret, *, post=None):
    post = post or _post_json
    data = post(TOKEN_URL, {'appId': app_id, 'clientSecret': app_secret})
    token = data.get('access_token') if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError('QQ 接口未返回 access_token')
    return token


def send_test_message(app_id, app_secret, openid, content=TEST_MESSAGE, *,
                      post=None):
    """Deliver one private message without opening a gateway."""
    post = post or _post_json
    token = request_access_token(app_id, app_secret, post=post)
    url = (API_BASE + '/v2/users/' + urllib.parse.quote(openid, safe='')
           + '/messages')
    data = post(url, {'content': content, 'msg_type': 0},
                {'Authorization': 'QQBot ' + token})
    return data if isinstance(data, dict) else {}


def _parse(argv):
    flags = {'api': False, 'send_test': False, 'openid': None,
             'env': DEFAULT_ENV, 'db': None, 'pairing_db': None,
             'log_dir': None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == '--api':
            flags['api'] = True
        elif token == '--send-test':
            flags['send_test'] = True
        elif token in ('--openid', '--env', '--db', '--pairing-db', '--log-dir'):
            if index + 1 >= len(argv):
                return None
            value = argv[index + 1]
            if value.startswith('--'):
                return None
            flags[token[2:].replace('-', '_')] = value
            index += 1
        else:
            return None
        index += 1
    return flags


def _print(results):
    for name, ok, detail in results:
        print(f'[{"ok" if ok else "!!"}] {name}：{detail}')


def main(argv=None):
    args = _parse(list(sys.argv[1:] if argv is None else argv))
    if args is None:
        print(USAGE, file=sys.stderr)
        return 2
    load_env_file(args['env'])
    try:
        config = load_config()
    except ValueError as exc:
        print(f'[!!] 配置：{exc}', file=sys.stderr)
        return 1
    db_path = args['db'] or 'data/venus.sqlite3'
    persona_path = DEFAULT_PERSONA
    if args['pairing_db']:
        config['pairing_db'] = args['pairing_db']

    results = collect_checks(
        config, db_path=db_path, persona_path=persona_path,
        log_folder=Path(args['log_dir']) if args['log_dir'] else None)
    ok_all = all(ok for _, ok, _ in results)
    _print(results)
    if not args['api'] and not args['send_test']:
        print('提示：加 --api 检查模型接口，加 --send-test 检查 QQ 发送。')

    if args['api']:
        try:
            reply = probe_model(
                config['base_url'], config['model'], config['api_key'])
            print(f'[ok] 模型接口：返回“{reply}”')
        except Exception as exc:
            ok_all = False
            print(f'[!!] 模型接口：{type(exc).__name__}：{exc}')

    if args['send_test']:
        try:
            openids = [args['openid']] if args['openid'] else resolve_openids(config)
            if len(openids) != 1:
                raise RuntimeError(
                    '需要用 --openid 指定一个用户' if openids
                    else '没有可发送的用户')
            send_test_message(config['app_id'], config['app_secret'], openids[0])
            print(f'[ok] QQ 发送：已向 {mask(openids[0])} 发送一条测试消息')
        except Exception as exc:
            ok_all = False
            print(f'[!!] QQ 发送：{type(exc).__name__}：{exc}')

    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())

