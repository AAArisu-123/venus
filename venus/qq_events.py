"""Independent QQ C2C (single-chat) inbound event validation.

This module is a pure validator: it neither prints nor stores messages or
credentials, reads no files and performs no network access. It only inspects
the caller-supplied dictionary and returns plain values.
"""


def _nonempty_string(value):
    """Return True only for a string with at least one non-whitespace char."""
    return isinstance(value, str) and bool(value.strip())


def parse_c2c_event(data):
    """Validate the inner ``data`` object of a QQ C2C message event.

    The expected payload (per the QQ bot OpenAPI single-chat event) carries:

    * ``id`` -- the message id;
    * ``author.user_openid`` -- the sender's open id;
    * ``content`` -- the message body text;
    * optional extra fields such as ``attachments`` are ignored.

    Every required field must be a non-empty string (whitespace-only counts
    as empty). Only the body text is stripped.

    Returns ``(message_id, user_id, text)`` for a valid event, or ``None``
    when the payload is malformed or carries no text body -- for example an
    attachment-only message whose ``content`` is empty.
    """
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
