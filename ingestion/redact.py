"""Keep API keys out of logs, manifests and error messages."""

from __future__ import annotations

import re

_PATTERNS = [
    # ...?api_key=VALUE&...
    (re.compile(r"(?i)(api[_-]?key=)[^&\s\"']+"), r"\1<redacted>"),
    # "api_key": "VALUE"
    (re.compile(r'(?i)("api[_-]?key"\s*:\s*")[^"]*(")'), r"\1<redacted>\2"),
]

_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember an exact secret value so it is masked wherever it appears."""
    if value and len(value) >= 4:
        _secrets.add(value)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    for secret in _secrets:
        text = text.replace(secret, "<redacted>")
    return text
