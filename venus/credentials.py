"""Local file-based store for the QQ AppID/AppSecret pair.

The QR onboarding flow writes the credentials obtained from Tencent into a
local JSON file; the bot reads it at startup instead of asking the user to
copy secrets by hand. Nothing here prints, logs or echoes a secret.
"""

import json
import os
import tempfile


def _valid_fields(app_id, app_secret):
    return (
        isinstance(app_id, str)
        and bool(app_id.strip())
        and isinstance(app_secret, str)
        and bool(app_secret.strip())
    )


def load_credentials(path):
    """Return (app_id, app_secret), or None when the file does not exist.

    Malformed files or files without a valid pair of string fields raise
    ValueError. No secret is ever printed.
    """
    path = os.fspath(path)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('credential file is not valid JSON') from exc

    if not isinstance(data, dict):
        raise ValueError('credential file must contain a JSON object')

    app_id = data.get('app_id')
    app_secret = data.get('app_secret')
    if not _valid_fields(app_id, app_secret):
        raise ValueError('credential file is missing valid app_id/app_secret')
    return app_id, app_secret


def save_credentials(path, app_id, app_secret):
    """Atomically write the credential pair to *path*.

    Validation happens before any filesystem change, so invalid values leave
    an existing file untouched. The write goes to a temporary file in the
    same directory and is moved into place with os.replace; permissions are
    tightened to 0o600 on a best-effort basis.
    """
    if not _valid_fields(app_id, app_secret):
        raise ValueError('app_id and app_secret must be non-blank strings')

    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    payload = json.dumps(
        {'app_id': app_id, 'app_secret': app_secret},
        ensure_ascii=False,
        indent=2,
    ) + '\n'

    fd, tmp_path = tempfile.mkstemp(prefix='.qq-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
