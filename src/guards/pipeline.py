"""Guard pipeline (architecture §8), run on every user message before retrieval.

Order: PII (warn + redact, never stored) → advice → performance → scope →
about-the-assistant ("which funds do you cover?") → fund-fact question with no
fund named (ask which fund) → allow.
Every later check sees only the redacted text. Deterministic; no retriever or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.guards import about, advice, clarify, performance, scope
from src.guards.common import AnswerPayload
from src.guards.pii import PII_WARNING, redact


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    query: str  # redacted message; the only form of the input safe to pass on or log
    payload: AnswerPayload | None = None  # set when refused (architecture §7 shape)
    pii_types: list[str] = field(default_factory=list)
    pii_warning: str | None = None  # the UI shows this alongside the answer


def run_guards(message: str, context_scheme: str | None = None) -> GuardDecision:
    """`context_scheme`: the fund carried over from earlier in the conversation;
    when set, a question that names no fund is a follow-up, not ambiguous."""
    query, pii_types = redact(message.strip())
    warning = PII_WARNING if pii_types else None

    def refuse(payload: AnswerPayload) -> GuardDecision:
        return GuardDecision(False, query, payload, pii_types, warning)

    if advice.is_advice(query):
        return refuse(advice.refusal())
    if performance.is_performance(query):
        return refuse(performance.refusal(query))
    if scope.out_of_scope_reason(query, context_scheme):
        return refuse(scope.refusal())
    if about.is_about(query):
        # Answered here (not a refusal): a fixed reply listing the covered schemes.
        return GuardDecision(False, query, about.answer(), pii_types, warning)
    if clarify.needs_fund(query) and not context_scheme:
        return refuse(clarify.clarification())
    return GuardDecision(True, query, None, pii_types, warning)
