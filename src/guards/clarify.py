"""Ambiguous-scheme guard (architecture §12): a fund-fact question that names none
of the five schemes gets a request to name the fund, instead of an answer about
whichever fund happens to rank first in retrieval.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload
from src.schemes import SCHEME_CATEGORIES, detect_schemes

# Facts that differ per fund, so the fund must be known before answering.
_FUND_FACT_RE = re.compile(
    r"\b(expense\s+ratio|ter|exit\s+load|sip|lump\s*sum|minimum\s+(investment|amount)|"
    r"nav|net\s+asset\s+value|aum|fund\s+size|corpus|benchmark|riskometer|risk\s+level|"
    r"how\s+risky|fund\s+managers?|who\s+manages|lock[\s-]?in|stamp\s+duty|"
    r"investment\s+objective|holdings?|stocks?\s+(held|does|do)|top\s+\d+\s+stocks|"
    r"allocation|asset\s+mix|sector\s+(split|breakdown|allocation))\b",
    re.I,
)

# "What is an expense ratio?" / "What does exit load mean?" ask for a definition,
# which is the same for every fund, so no fund is needed.
_DEFINITION_RE = re.compile(
    r"\bwhat\s+(is|are)\s+(an?|meant\s+by)\b|\bwhat\s+does\b.*\bmean\b|\bmeaning\s+of\b|"
    r"\bdefin(e|ition)\b|\bexplain\b",
    re.I,
)

_FUND_NAMES = ", ".join(n.removesuffix(" Direct Growth") for n in SCHEME_CATEGORIES)
CLARIFY_TEXT = (
    f"Which fund do you mean? I cover five HDFC Mutual Fund schemes: {_FUND_NAMES}. "
    "Please ask again with the fund name, for example: \"What is the expense ratio "
    "of HDFC Small Cap Fund?\""
)


def needs_fund(text: str) -> bool:
    return (
        bool(_FUND_FACT_RE.search(text))
        and not detect_schemes(text)
        and not _DEFINITION_RE.search(text)
    )


def clarification() -> AnswerPayload:
    return AnswerPayload(
        text=CLARIFY_TEXT,
        source_url=None,
        last_updated_from_sources=None,
        refusal=True,
        refusal_reason="clarify",
    )
