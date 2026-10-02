"""Ambiguous-scheme guard (PRD FR-2, §8): a fund-fact question that names none of
the five schemes gets a request to name the fund, instead of an answer about
whichever fund happens to rank first in retrieval. When the name fits more than one
scheme ("HDFC cap fund"), the reply carries chips to pick from.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, make_payload, schemes_listing_source
from src.schemes import SCHEME_CATEGORIES, detect_schemes, fuzzy_schemes, short_name

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
        and len(fuzzy_schemes(text)) != 1
        and not _DEFINITION_RE.search(text)
    )


def clarification(candidates: list[str] | None = None) -> AnswerPayload:
    """Ask which fund; with `candidates` (an ambiguous name), offer them as chips."""
    if candidates:
        names = [short_name(c) for c in candidates]
        text = (f"Which fund do you mean: {', '.join(names[:-1])} or {names[-1]}? "
                "Please pick one so I can answer for the right scheme.")
    else:
        names = [short_name(c) for c in SCHEME_CATEGORIES]
        text = CLARIFY_TEXT
    payload = make_payload(text, schemes_listing_source(), refusal=True, refusal_reason="clarify")
    payload["chips"] = names
    return payload
