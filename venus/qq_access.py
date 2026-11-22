"""QQ access control: allowlist or locally approved pairing codes."""

import sqlite3
import time

from venus.pairing import connect_database, is_allowed, pending_codes, request_code


class AccessGate:
    def __init__(self, allowed, pair_db, make_code=None, now=None):
        self._allowed = frozenset(allowed)
        self._pair_db = pair_db
        self._make_code = make_code
        self._now = now if now is not None else time.time

    def decide(self, user):
        # Invalid or blank identities are always denied.
        if not isinstance(user, str) or not user.strip():
            return ('deny', None)

        # Allowlist membership is granted without touching the pairing db.
        if user in self._allowed:
            return ('allow', None)

        # In allowlist mode, everyone else is denied and never prompted.
        if self._allowed:
            return ('deny', None)

        # Pairing mode: consult the pairing database, failing closed on error.
        try:
            db = connect_database(self._pair_db)
        except (sqlite3.Error, OSError):
            return ('deny', None)

        try:
            if is_allowed(db, user):
                return ('allow', None)

            now = self._now()
            if any(pending_user == user for _, pending_user in pending_codes(db, now=now)):
                # A code was already issued; never prompt the same user twice.
                return ('deny', None)

            code = request_code(db, user, now=now, make_code=self._make_code)
            if not code:
                return ('deny', None)
            return ('prompt', code)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return ('deny', None)
        finally:
            db.close()
