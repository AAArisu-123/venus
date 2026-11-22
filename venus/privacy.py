"""Block secrets and personal identifiers before a model call.

The rules are deliberately narrow so normal chat passes through unchanged.
"""

import re

__all__ = ["detect", "redact", "safe_reply"]

_RULES = (
    ("私钥", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("API 密钥", re.compile(
        r"\b(?:sk|ak|ghp|gho|ghu|ghs|ghr|xox[abprs])[-_][A-Za-z0-9_-]{16,}\b",
        re.IGNORECASE,
    )),
    ("API 密钥", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("访问令牌", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE)),
    ("密码", re.compile(
        r"(?:密码|口令|password|passwd|pwd)\s*(?:是|为|:|：|=)\s*\S+",
        re.IGNORECASE,
    )),
    ("验证码", re.compile(
        r"(?:验证码|校验码|动态码|otp|code)\s*(?:是|为|:|：|=)?\s*\d{4,8}",
        re.IGNORECASE,
    )),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("银行卡号", re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)


def detect(text):
    """Return the labels of sensitive categories found in ``text``.

    The input itself is never included in the result. Non-string input yields
    an empty list so callers do not need a separate type check.
    """
    if not isinstance(text, str):
        return []
    return [label for label, pattern in _RULES if pattern.search(text)]


def redact(text):
    """Replace matched sensitive spans with ``[已隐藏]``.

    Used before old history, memories or profiles are sent to a model, so a
    value stored before this guard existed cannot leak on a later turn.
    """
    if not isinstance(text, str):
        return text
    for _, pattern in _RULES:
        text = pattern.sub("[已隐藏]", text)
    return text


def safe_reply(labels):
    """Build a deterministic warning without echoing the sensitive value."""
    unique = "、".join(dict.fromkeys(label for label in labels if label))
    if not unique:
        unique = "敏感信息"
    return (
        f"这句话里可能有需要保护的信息（{unique}），我没有发送给模型，也没有保存。"
        "请删掉敏感部分后再发；如果是配置密钥，请直接修改本机的 .env 或 "
        "data/qq-credentials.json。"
    )
