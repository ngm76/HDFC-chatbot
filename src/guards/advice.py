"""Advice guard (PRD FR-8, §6 precedence 2): buy/sell/hold/switch, recommendations,
suitability, "which is better", own portfolio or goals.

When unsure between fact and advice, the PRD says choose advice, so the patterns
are broad. A mixed message ("What's the exit load and should I exit now?") is
advice; the refusal offers the fact as a separate question, so each response
keeps a single link. Returns-comparison questions ("which had better returns")
are left to the performance guard, which runs next.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, educational_source, make_payload
from src.schemes import detect_schemes, short_name

_ADVICE_RE = re.compile(
    r"|".join(
        [
            r"\bshould\s+(i|we)\s+(buy|sell|invest|redeem|switch|hold|exit|stop|continue|start|put|keep|choose|pick|go\s+for|move)\b",
            r"\b(shall|can|could|would)\s+(i|we)\s+(buy|sell|invest|redeem|switch)\b.*\b(now|today|good|better|right)\b",
            r"\b(is|are)\s+(it|this|that|now|they)\s+(a\s+)?(good|right|safe|smart|wise|bad)\s+(time\s+)?(to\s+)?(buy|sell|invest|investment|fund|option|choice)\b",
            r"\bworth\s+(buying|investing|it)\b",
            r"\b(best|top|better|safest)\s+([\w-]+\s+){0,3}(fund|funds|scheme|schemes|option|choice|investment)\b",
            r"\bgood\s+(mutual\s+)?(fund|funds|scheme|schemes|option|choice|investment)\b",
            r"\bwhich\s+(fund|scheme|one|option)\s+(should|to|do\s+you)\b",
            r"\bwhich\b.{0,60}\b(is|are|would\s+be)\s+(better|best|safer|right|suitable)\b",
            r"\b(better|best)\s+for\s+(me|my|us)\b",
            r"\bso\s+should\s+i\b|\bshould\s+i\s+pick\b",
            r"\b(recommend|suggest|advise|advice)\b",
            r"\b(suitable|right|good|appropriate|best|better|ideal)\s+(for|to)\s+(me|my|us|a\s+\d+)",
            r"\b(funds?|schemes?|options?)\s+(is|are)\s+(the\s+)?(best|better|top|safest)\b",
            r"\b(allocate|allocation|rebalance|diversify)\b.*\b(my|i|me)\b",
            r"\bmy\s+(portfolio|goals?|retirement|savings)\b",
            r"\bhow\s+much\s+(should|to|can)\s+(i|we)?\s*invest\b",
            r"\b(buy|sell)\s+or\s+(sell|hold|buy)\b",
        ]
    ),
    re.I,
)

# Facts a mixed message also asks for, offered as a separate question.
_FACTS = (
    ("exit load", re.compile(r"\bexit\s+load\b", re.I)),
    ("expense ratio", re.compile(r"\b(expense\s+ratio|ter)\b", re.I)),
    ("minimum SIP", re.compile(r"\b(min(imum)?\s+)?sip\s+(amount|minimum)|\bminimum\s+sip\b", re.I)),
    ("lock-in", re.compile(r"\block[\s-]?in\b", re.I)),
    ("riskometer level", re.compile(r"\b(riskometer|risk\s+level)\b", re.I)),
    ("benchmark", re.compile(r"\bbenchmark\b", re.I)),
)

REFUSAL_TEXT = (
    "I can only share facts from official HDFC Mutual Fund, SEBI and AMFI pages, so I "
    "can't recommend whether to buy, sell or choose a fund."
)
OFFER_TEXT = (
    "I can tell you a scheme's expense ratio, exit load, minimum SIP, lock-in, "
    "riskometer level or benchmark if that helps."
)
LINK_TEXT = "To learn how to choose a fund for your goals, see AMFI's investor education page."


def is_advice(text: str) -> bool:
    return bool(_ADVICE_RE.search(text))


def refusal(text: str = "") -> AnswerPayload:
    asked = [name for name, pattern in _FACTS if pattern.search(text)]
    if asked:
        schemes = detect_schemes(text)
        fund = f" of {short_name(schemes[0])}" if len(schemes) == 1 else ""
        offer = f"I can share the {asked[0]}{fund} if you ask it as a separate question."
    else:
        offer = OFFER_TEXT
    return make_payload(f"{REFUSAL_TEXT} {offer} {LINK_TEXT}", educational_source(),
                        refusal=True, refusal_reason="advice")
