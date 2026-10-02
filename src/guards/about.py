"""Questions about the assistant itself: which funds it covers, what it can answer.

These have a fixed answer (the configured scheme list), so they are answered here
rather than by retrieval: no single scheme page states "the funds this bot covers".
Runs after the advice / performance / scope guards, so "which fund should I buy"
is still refused as advice.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, corpus_last_fetched
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
        ]
    ),
    re.I,
)

_FUND_LIST = ", ".join(
    f"{name.removesuffix(' Direct Growth')} ({category})"
    for name, category in SCHEME_CATEGORIES.items()
)
ABOUT_TEXT = (
    f"I can answer factual questions about five HDFC Mutual Fund schemes (Direct "
    f"Growth plans): {_FUND_LIST}. For each, I can share facts such as expense "
    f"ratio, exit load, minimum SIP, riskometer, benchmark, fund size (AUM), NAV and "
    f"fund managers, taken from its public Groww scheme page. I don't give investment "
    f"advice or compare returns."
)


def is_about(text: str) -> bool:
    return bool(_ABOUT_RE.search(text))


def answer() -> AnswerPayload:
    # Not a fact from one page, so there is no single citation; the five scheme
    # pages are listed in data/sources.csv and the README.
    return AnswerPayload(
        text=ABOUT_TEXT,
        source_url=None,
        last_updated_from_sources=corpus_last_fetched(),
        refusal=False,
        refusal_reason=None,
    )
