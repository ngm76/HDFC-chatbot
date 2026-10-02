"""Advice guard: buy/sell, recommendations, suitability, allocation, "best fund".

Returns-comparison questions ("which had better returns") are left to the
performance guard, which runs next.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, make_payload

_ADVICE_RE = re.compile(
    r"|".join(
        [
            r"\bshould\s+(i|we)\s+(buy|sell|invest|redeem|switch|hold|exit|stop|continue|start|put|keep|choose|pick|go\s+for)\b",
            r"\b(shall|can|could|would)\s+(i|we)\s+(buy|sell|invest|redeem|switch)\b.*\b(now|today|good|better|right)\b",
            r"\b(is|are)\s+(it|this|that|now|they)\s+(a\s+)?(good|right|safe|smart|wise|bad)\s+(time\s+)?(to\s+)?(buy|sell|invest|investment|fund|option|choice)\b",
            r"\bworth\s+(buying|investing|it)\b",
            r"\b(best|top|better|safest)\s+([\w-]+\s+){0,3}(fund|funds|scheme|schemes|option|choice|investment)\b",
            r"\bgood\s+(mutual\s+)?(fund|funds|scheme|schemes|option|choice|investment)\b",
            r"\bwhich\s+(fund|scheme|one|option)\s+(should|to|do\s+you)\b",
            r"\b(recommend|suggest|advise|advice)\b",
            r"\b(suitable|right|good|appropriate|best|better|ideal)\s+(for|to)\s+(me|my|us|a\s+\d+)",
            r"\b(funds?|schemes?|options?)\s+(is|are)\s+(the\s+)?(best|better|top|safest)\b",
            r"\b(allocate|allocation|rebalance|diversify)\b.*\b(my|i|me)\b",
            r"\bmy\s+portfolio\b",
            r"\bhow\s+much\s+(should|to|can)\s+(i|we)?\s*invest\b",
            r"\b(buy|sell)\s+or\s+(sell|hold|buy)\b",
        ]
    ),
    re.I,
)

REFUSAL_TEXT = (
    "I can only share facts from Groww scheme pages, so I can't recommend whether "
    "to buy, sell or choose a fund."
)


def is_advice(text: str) -> bool:
    return bool(_ADVICE_RE.search(text))


def refusal() -> AnswerPayload:
    # No link (owner decision, 2026-10-02): the brief suggested an educational link,
    # but the reply is clearer as a plain statement.
    return make_payload(REFUSAL_TEXT, None, refusal=True, refusal_reason="advice")
