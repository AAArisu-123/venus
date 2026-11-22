"""Independent persona loading for Venus.

Loads a UTF-8 JSON persona file and validates the required fields.
"""

import json

MAX_DESCRIPTION_LENGTH = 12000

# Optional free-text layers. They let a persona describe how it speaks and
# what it will not do without turning every custom character into a new
# prompt format. Existing two-field personas remain valid.
OPTIONAL_TEXT_LIMITS = {
    'style': 2000,
    'boundaries': 2000,
    'relationship_pace': 1000,
    'post_history_instructions': 1000,
}

MAX_EXAMPLES = 8
MAX_EXAMPLE_USER_CHARS = 500
MAX_EXAMPLE_ASSISTANT_CHARS = 1000


def load_persona(path):
    """Read a persona JSON file and return it as a dict.

    Requires nonempty string ``name`` and ``description`` (at most
    12000 characters). Optional ``style``, ``boundaries`` and
    ``relationship_pace`` strings are validated when present. Any other
    fields are passed through untouched.
    Raises ValueError on invalid content; OSError/json.JSONDecodeError
    propagate from file reading and JSON parsing.
    """
    with open(path, encoding='utf-8') as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError('人设必须是 JSON 对象。')
    for field in ('name', 'description'):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'人设字段 {field} 必须是非空字符串。')
    if len(data['description']) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f'人设描述过长，最多 {MAX_DESCRIPTION_LENGTH} 字符。')
    for field, limit in OPTIONAL_TEXT_LIMITS.items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str):
            raise ValueError(f'人设字段 {field} 必须是字符串。')
        if len(value) > limit:
            raise ValueError(f'人设字段 {field} 过长，最多 {limit} 字符。')
    if 'examples' in data:
        examples = data['examples']
        if not isinstance(examples, list) or len(examples) > MAX_EXAMPLES:
            raise ValueError(f'人设字段 examples 必须是最多 {MAX_EXAMPLES} 条的数组。')
        for item in examples:
            if not isinstance(item, dict):
                raise ValueError('examples 的每一项必须是包含 user 和 assistant 的对象。')
            user = item.get('user')
            assistant = item.get('assistant')
            if (not isinstance(user, str) or not user.strip()
                    or len(user) > MAX_EXAMPLE_USER_CHARS):
                raise ValueError('examples.user 必须是非空字符串且不超过 500 字。')
            if (not isinstance(assistant, str) or not assistant.strip()
                    or len(assistant) > MAX_EXAMPLE_ASSISTANT_CHARS):
                raise ValueError('examples.assistant 必须是非空字符串且不超过 1000 字。')
    return data
