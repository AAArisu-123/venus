"""Load simple KEY=VALUE settings from a local .env file."""

import os
from pathlib import Path


def load_env_file(path, environ=None):
    """Read KEY=VALUE lines into ``environ`` without overriding existing keys.

    Blank lines and lines starting with ``#`` are skipped. Surrounding single
    or double quotes around a value are removed. Lines without ``=`` or with an
    empty key are ignored. The file is optional: a missing file is a no-op.

    Returns the number of keys added.
    """
    target = os.environ if environ is None else environ
    env_path = Path(path)
    if not env_path.is_file():
        return 0
    added = 0
    for raw in env_path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key or key in target:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        target[key] = value
        added += 1
    return added
