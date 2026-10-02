"""PII guard (PRD FR-10 to FR-13): detect identifiers before anything else sees the message.

A message with PII is **blocked**: nothing is sent to retrieval, the model or the
logs, and the user gets a fixed safety message with a link to Groww's help centre.
`redact` stays as the server-side backstop (FR-12): matches are replaced with a type
tag like [PAN], and only the tag names ever leave this module. Never log or print
the raw message.

Aadhaar is a 12-digit number with a Verhoeff check digit; a 12-digit number that
fails the checksum is labelled ACCOUNT instead, so it is blocked either way.
"""

from __future__ import annotations

import re

# Order matters: specific shapes first, so e.g. a 12-digit Aadhaar is not later
# swallowed by the generic long-number rule.
_AADHAAR_RE = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I)),
    ("AADHAAR", _AADHAAR_RE),  # only Verhoeff-valid matches, see _aadhaar_valid
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

# FR-11 wording.
PII_BLOCK_TEXT = (
    "For your safety, please don't share personal details like PAN, Aadhaar, account "
    "numbers or OTPs. I don't need them to answer. For help with your own account, "
    "please visit Groww's help centre."
)

# --- Verhoeff checksum (Aadhaar) ----------------------------------------------------
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    check = 0
    for i, digit in enumerate(reversed(digits)):
        check = _D[check][_P[i % 8][digit]]
    return check == 0


def _aadhaar_valid(match: re.Match[str]) -> bool:
    return verhoeff_valid(match.group(0))


def redact(text: str) -> tuple[str, list[str]]:
    """Return (text with PII replaced by [TYPE] tags, sorted unique PII types found)."""
    found: set[str] = set()
    for kind, pattern in _PATTERNS:
        if kind == "AADHAAR":
            def sub(m: re.Match[str]) -> str:
                # Checksum-valid: Aadhaar. Otherwise still a 12-digit ID-like number
                # (e.g. a mistyped Aadhaar or an account number): blocked as ACCOUNT.
                tag = kind if _aadhaar_valid(m) else "ACCOUNT"
                found.add(tag)
                return f"[{tag}]"
            text = pattern.sub(sub, text)
            continue
        text, n = pattern.subn(f"[{kind}]", text)
        if n:
            found.add(kind)
    return text, sorted(found)


def pii_types(text: str) -> list[str]:
    """PII types in the text (empty if none). The text itself is never returned."""
    return redact(text)[1]
