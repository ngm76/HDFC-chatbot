"""Questions about the assistant itself: which funds it covers, what it can answer.

These have a fixed answer (the configured scheme list), so they are answered here
rather than by retrieval: no single scheme page states "the funds this bot covers".
Runs after the advice / performance / scope guards, so "which fund should I buy"
is still refused as advice.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, make_payload, schemes_listing_source
from src.schemes import SCHEME_CATEGORIES

_ABOUT_RE = re.compile(
    r"|".join(
        [
            # "which (all) funds can you access / do you cover / are available"
            r"\b(which|what)\b.{0,20}\b(mutual\s+)?(funds?|schemes?)\b.{0,40}"
            r"\b(you|this\s+(bot|app|assistant|prototype|chatbot)|available|covered|supported|included)\b",
            # "list / show (me) the funds (you cover)"
            r"\b(list|show|name)\b.{0,15}\b(all\s+)?(the\s+)?(mutual\s+)?(funds?|schemes?)\b",
            # "what can you do / answer / help with", "what do you know"
            r"\bwhat\s+(can|do)\s+you\s+(do|answer|cover|know|help)",
            r"\bhow\s+many\s+(mutual\s+)?(funds?|schemes?)\b",
            r"\b(your|the)\s+(scope|coverage)\b",
            # greetings and thanks get the same short introduction
            r"^\s*(hi|hello|hey|namaste|thanks|thank\s+you|good\s+(morning|afternoon|evening))\b"
            r"[\s!.,?]*$",
        ]
    ),
    re.I,
)

_FUND_LIST = ", ".join(
    f"{name.removesuffix(' Direct Growth')} ({category})"
    for name, category in SCHEME_CATEGORIES.items()
)
ABOUT_TEXT = (
    f"I answer factual questions about five HDFC Mutual Fund schemes (Direct Plan - "
    f"Growth): {_FUND_LIST}. I can share facts such as expense ratio, exit load, "
    f"minimum SIP, lock-in, riskometer, benchmark, NAV, fund size and holdings, and how "
    f"to download statements, from official HDFC Mutual Fund, SEBI and AMFI pages. I "
    f"don't give investment advice or compare returns."
)


def is_about(text: str) -> bool:
    return bool(_ABOUT_RE.search(text))


def answer() -> AnswerPayload:
    # Every response carries one link (FR-5): the HDFC MF schemes listing.
    return make_payload(ABOUT_TEXT, schemes_listing_source(), refusal=False)
