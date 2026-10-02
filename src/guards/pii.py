"""PII guard: detect and redact identifiers before anything else sees the message.

Conservative regex + keyword checks (architecture §8). Matches are replaced with
a type tag like [PAN]; only the tag names ever leave this module. Never log or
print the raw message — use the redacted text.
"""

from __future__ import annotations

import re

# Order matters: specific shapes first, so e.g. a 12-digit Aadhaar is not later
# swallowed by the generic long-number rule.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I)),
    ("AADHAAR", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("OTP", re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password)\b\D{0,15}\d{4,8}\b", re.I)),
    (
        "ACCOUNT",
        re.compile(
            r"\b(?:account|a/c|acct|folio|bank\s+account)\b(?:\s*(?:no\.?|number|#))?"
            r"\s*(?:is\s*)?[:\-]?\s*[A-Z0-9/-]{5,20}\d\b",
            re.I,
        ),
    ),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("ACCOUNT", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),  # bare long numbers (a/c, card)
]

PII_WARNING = (
    "Please don't share personal details such as PAN, Aadhaar, account or folio "
    "numbers, OTPs, email addresses or phone numbers. I've removed them from your "
    "message and nothing was stored."
)


def redact(text: str) -> tuple[str, list[str]]:
    """Return (text with PII replaced by [TYPE] tags, sorted unique PII types found)."""
    found: set[str] = set()
    for kind, pattern in _PATTERNS:
        text, n = pattern.subn(f"[{kind}]", text)
        if n:
            found.add(kind)
    return text, sorted(found)
