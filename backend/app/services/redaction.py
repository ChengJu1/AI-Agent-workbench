"""Mask secrets and personal identifiers before anything reaches task or tool audit logs."""
import re

SECRET_KEY = re.compile(r'(password|passwd|token|secret|\botp\b|captcha|verification|^auth$|authorization|cookie|session_key|'
                        r'id_number|id_card|identity_number|身份证|验证码|授权码|密码)', re.I)
PATTERNS = [
    (re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)'), '[身份证号已隐藏]'),
    (re.compile(r'(?<!\d)\d{16,19}(?!\d)'), '[卡号已隐藏]'),
    (re.compile(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)'), r'\1****\2'),
    (re.compile(r'\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b'), r'\1***@\2'),
    (re.compile(r'([?&](?:token|code|key|sig|signature|auth|session)[^=&]*=)[^&#\s]+', re.I), r'\1***'),
]
MAX_TEXT = 2000


def redact_text(text, limit=MAX_TEXT):
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text if limit is None or len(text) <= limit else text[:limit] + '…'


def redact(value, depth=0, limit=MAX_TEXT):
    """limit=None keeps full length (audit logs); task logs stay truncated."""
    if depth > 8:
        return '…'
    if isinstance(value, dict):
        return {k: ('***' if SECRET_KEY.search(str(k)) and v not in (None, '') else redact(v, depth + 1, limit)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1, limit) for item in (value if limit is None else value[:200])]
    if isinstance(value, str):
        return redact_text(value, limit)
    return value
