"""Owner-facing CLI for approving and revoking pairing codes.

Usage: python -m venus.pair_cli --list | --approve CODE | --revoke OPENID
Optional: --db PATH (default data/pairing.sqlite3).
Openids are always masked so secrets never reach the terminal.
"""

import sys

from venus.pairing import (
    approve_code,
    connect_database,
    pending_codes,
    revoke_openid,
)

DEFAULT_DB_PATH = 'data/pairing.sqlite3'
USAGE = (
    'usage: python -m venus.pair_cli'
    ' (--list | --approve CODE | --revoke OPENID) [--db PATH]'
)


def mask_openid(openid):
    if len(openid) <= 6:
        return '****'
    return openid[:4] + '****' + openid[-2:]


def _parse(argv):
    action = None
    value = None
    db_path = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == '--list':
            if action is not None:
                return None
            action = 'list'
        elif token in ('--approve', '--revoke'):
            if action is not None or i + 1 >= len(argv):
                return None
            value = argv[i + 1]
            if value.startswith('-'):
                return None
            action = token[2:]
            i += 1
        elif token == '--db':
            if db_path is not None or i + 1 >= len(argv):
                return None
            db_path = argv[i + 1]
            if db_path.startswith('-'):
                return None
            i += 1
        else:
            return None
        i += 1
    if action is None:
        return None
    return action, value, db_path or DEFAULT_DB_PATH


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parsed = _parse(list(argv))
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 2
    action, value, db_path = parsed
    db = connect_database(db_path)
    try:
        if action == 'list':
            for code, openid in pending_codes(db):
                print(f'{code} {mask_openid(openid)}')
        elif action == 'approve':
            openid = approve_code(db, value)
            if openid is not None:
                print(f'paired user {mask_openid(openid)}')
        else:
            granted = revoke_openid(db, value)
            state = 'revoked' if granted else 'not revoked'
            print(f'{state} {mask_openid(value)}')
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
