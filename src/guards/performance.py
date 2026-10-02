"""Performance guard: returns, CAGR, NAV growth, benchmark comparisons.

Never computes or compares. Points to the official factsheet instead.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, factsheet_source, make_payload
from src.schemes import detect_schemes

_PERFORMANCE_RE = re.compile(
    r"|".join(
        [
            r"(?<!tax\s)(?<!income\s)(?<!itr\s)\breturns?\b(?!\s+filing)",
            r"\bcagr\b",
            r"\bxirr\b",
            r"\b(annuali[sz]ed|absolute|trailing|historical|past)\s+(return|performance|growth)",
            r"\bperform(ed|ing|ance)?\b",
            r"\b(out|under)perform",
            r"\bbeat(s|en)?\s+((the|its|their)\s+)?(benchmark|index|market|nifty|sensex)\b",
            r"\bhow\s+much\s+(did|has|will|would)\b.*\b(grow|grown|earn|make|made|gain)\b",
            r"\b(grow|grown|growth|gain(ed)?|earn(ed)?)\b.*\b(\d+\s*(years?|yrs?)|since\s+inception)\b",
            r"\bnav\s+(growth|increase|change|history)\b",
            # Not "capital gains": statements and taxation are in scope.
        ]
    ),
    re.I,
)


def is_performance(text: str) -> bool:
    return bool(_PERFORMANCE_RE.search(text))


def refusal(text: str) -> AnswerPayload:
    schemes = detect_schemes(text)
    scheme = schemes[0] if len(schemes) == 1 else None
    name = scheme.removesuffix(" Direct Growth") if scheme else "these schemes"
    message = (
        "I can't calculate, predict or compare fund returns. The official past "
        f"performance of {name} is published in the HDFC Mutual Fund monthly "
        "factsheet linked below. Past performance may not be sustained in future."
    )
    return make_payload(
        message, factsheet_source(scheme), refusal=True, refusal_reason="performance"
    )
