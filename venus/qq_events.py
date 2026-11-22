"""Validate QQ C2C event payloads without side effects."""


def _nonempty_string(value):
    """Return True only for a string with at least one non-whitespace char."""
    return isinstance(value, str) and bool(value.strip())


def parse_c2c_event(data):
    """Return `(message_id, user_id, text)`, or None if the event is unusable."""
    if not isinstance(data, dict):
        return None

    message_id = data.get('id')
    if not _nonempty_string(message_id):
        return None

    author = data.get('author')
    if not isinstance(author, dict):
        return None
    user_id = author.get('user_openid')
    if not _nonempty_string(user_id):
        return None

    content = data.get('content')
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None

    return (message_id, user_id, text)
