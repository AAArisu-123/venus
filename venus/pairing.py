"""Short-lived pairing codes that the owner approves locally."""

import secrets
import sqlite3
import time
from pathlib import Path

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ234567'
CODE_LENGTH = 6
CODE_TTL_SECONDS = 600


def connect_database(path):
    db_path = str(path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        db.execute(
            'CREATE TABLE IF NOT EXISTS pairings ('
            '  code TEXT PRIMARY KEY,'
            '  openid TEXT NOT NULL,'
            '  created_at INTEGER NOT NULL,'
            '  approved_at INTEGER'
            ')'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_pairings_openid ON pairings(openid)'
        )
        db.commit()
    except BaseException:
        db.close()
        raise
    return db


def _valid_code(code):
    return (
        isinstance(code, str)
        and len(code) == CODE_LENGTH
        and set(code) <= set(CODE_ALPHABET)
    )


def _random_code(db):
    while True:
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        taken = db.execute(
            'SELECT 1 FROM pairings WHERE code = ?', (code,)
        ).fetchone()
        if not taken:
            return code


def request_code(db, openid, *, now=None, make_code=None):
    if not isinstance(openid, str):
        raise TypeError('openid must be a string')
    if not openid.strip():
        raise ValueError('openid must not be blank')
    if is_allowed(db, openid):
        return None
    if now is None:
        now = time.time()
    if make_code is not None:
        code = make_code()
        if not isinstance(code, str):
            raise TypeError('code must be a string')
        if not _valid_code(code):
            raise ValueError('code must use the pairing alphabet')
    else:
        code = _random_code(db)
    db.execute(
        'DELETE FROM pairings WHERE openid = ? AND approved_at IS NULL',
        (openid,),
    )
    db.execute(
        'INSERT OR REPLACE INTO pairings (code, openid, created_at, approved_at)'
        ' VALUES (?, ?, ?, NULL)',
        (code, openid, now),
    )
    db.commit()
    return code


def approve_code(db, code, *, now=None):
    if not isinstance(code, str):
        return None
    normalized = code.strip().upper()
    if not _valid_code(normalized):
        return None
    if now is None:
        now = time.time()
    row = db.execute(
        'SELECT openid, created_at FROM pairings'
        ' WHERE code = ? AND approved_at IS NULL',
        (normalized,),
    ).fetchone()
    if row is None:
        return None
    openid, created_at = row
    if now - created_at >= CODE_TTL_SECONDS:
        return None
    db.execute(
        'UPDATE pairings SET approved_at = ? WHERE code = ?',
        (now, normalized),
    )
    db.commit()
    return openid


def is_allowed(db, openid):
    if not isinstance(openid, str):
        return False
    return db.execute(
        'SELECT 1 FROM pairings WHERE openid = ? AND approved_at IS NOT NULL',
        (openid,),
    ).fetchone() is not None


def approved_openids(db):
    """Return the openids the owner has approved, oldest approval first.

    Re-pairing the same user keeps one entry: the earliest approval decides the
    order, so a diagnostic listing stays stable instead of repeating somebody
    who reconnected several times.
    """
    return [
        row[0]
        for row in db.execute(
            'SELECT openid FROM pairings WHERE approved_at IS NOT NULL'
            ' GROUP BY openid ORDER BY MIN(approved_at), openid'
        )
    ]


def pending_codes(db, *, now=None):
    if now is None:
        now = time.time()
    return db.execute(
        'SELECT code, openid FROM pairings'
        ' WHERE approved_at IS NULL AND ? - created_at < ?'
        ' ORDER BY created_at, code',
        (now, CODE_TTL_SECONDS),
    ).fetchall()


def revoke_openid(db, openid):
    if not isinstance(openid, str):
        return False
    granted = db.execute(
        'SELECT 1 FROM pairings WHERE openid = ? AND approved_at IS NOT NULL',
        (openid,),
    ).fetchone() is not None
    db.execute('DELETE FROM pairings WHERE openid = ?', (openid,))
    db.commit()
    return granted
