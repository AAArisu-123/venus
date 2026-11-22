"""Environment and path configuration shared by the CLI, doctor and bot."""

import os

from .credentials import load_credentials

REQUIRED_ENV_NAMES = (
    'VENUS_API_KEY',
    'VENUS_BASE_URL',
    'VENUS_MODEL',
)

DEFAULT_DB = 'data/venus.sqlite3'
DEFAULT_CREDENTIALS = 'data/qq-credentials.json'
DEFAULT_PAIRING_DB = 'data/pairing.sqlite3'


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def load_config(environ=None):
    """Validate and return configuration; fail closed on anything missing.

    Values are read from ``environ`` (the process environment by default).
    Only env-var *names* appear in errors; secret values are never exposed.
    ``QQ_ALLOWED_OPENIDS`` is a comma-separated allowlist of user openids.
    """
    environ = os.environ if environ is None else environ
    values = {}
    for name in REQUIRED_ENV_NAMES:
        value = environ.get(name)
        if not _filled(value):
            raise ValueError(f'缺少必需的环境变量：{name}')
        values[name] = value

    app_id = environ.get('QQ_APP_ID')
    app_secret = environ.get('QQ_APP_SECRET')
    if not (_filled(app_id) and _filled(app_secret)):
        stored = load_credentials(
            environ.get('QQ_CREDENTIALS_FILE') or DEFAULT_CREDENTIALS)
        if stored is None:
            raise ValueError(
                '缺少 QQ 凭据：请先运行扫码绑定，或设置 QQ_APP_ID 与 QQ_APP_SECRET'
            )
        app_id, app_secret = stored

    allowed = frozenset(
        part.strip()
        for part in (environ.get('QQ_ALLOWED_OPENIDS') or '').split(',')
        if part.strip()
    )

    return {
        'app_id': app_id,
        'app_secret': app_secret,
        'api_key': values['VENUS_API_KEY'],
        'base_url': values['VENUS_BASE_URL'],
        'model': values['VENUS_MODEL'],
        'allowed_openids': allowed,
        'pairing_db': environ.get('QQ_PAIRING_DB') or DEFAULT_PAIRING_DB,
    }
