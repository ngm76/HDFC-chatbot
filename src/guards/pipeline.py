"""Guard pipeline (PRD §6, architecture §8), run on every user message before retrieval.

Fixed precedence; the first rule that fires decides:
PII (block) → advice → performance → about-the-assistant → out-of-scope (other
AMC / scheme / plan, live data, non-MF redirect) → ambiguous scheme name (chips) →
fund-fact question with no fund named (ask which fund) → allow (fact).

A message with PII is blocked before any other check: only the PII type names and
the redacted text leave this module, and nothing is passed on (FR-10 to FR-12).
"About" runs before out-of-scope so "What can you do?" is not treated as non-MF;
it still runs after advice, so "Which fund should I buy?" is refused.
Deterministic; no retriever or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.guards import about, advice, clarify, performance, scope
from src.guards.common import AnswerPayload, help_source, make_payload
from src.guards.pii import PII_BLOCK_TEXT, redact
from src.schemes import ambiguous_schemes


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    query: str  # redacted message; the only form of the input safe to pass on or log
    payload: AnswerPayload | None = None  # set when not allowed (architecture §7 shape)
    pii_types: list[str] = field(default_factory=list)
    pii_warning: str | None = None  # kept for callers; PII is now blocked, see payload

    @property
    def blocked_for_pii(self) -> bool:
        return bool(self.pii_types)


def pii_block(pii_types: list[str], redacted: str) -> GuardDecision:
    payload = make_payload(PII_BLOCK_TEXT, help_source("pii_block"),
                           refusal=True, refusal_reason="pii")
    return GuardDecision(False, redacted, payload, pii_types)


def run_guards(message: str, context_scheme: str | None = None) -> GuardDecision:
    """`context_scheme`: the fund carried over from the UI selection or earlier in the
    conversation; when set, a question that names no fund is a follow-up."""
    query, pii_types = redact(message.strip())
    if pii_types:
        return pii_block(pii_types, query)

    def refuse(payload: AnswerPayload) -> GuardDecision:
        return GuardDecision(False, query, payload)

    if advice.is_advice(query):
        return refuse(advice.refusal(query))
    if performance.is_performance(query):
        return refuse(performance.refusal(query))
    if about.is_about(query):
        # Answered here (not a refusal): a fixed reply listing the covered schemes.
        return GuardDecision(False, query, about.answer())
    reason = scope.out_of_scope_reason(query, context_scheme)
    if reason:
        return refuse(scope.refusal(reason, query, context_scheme))
    candidates = ambiguous_schemes(query)
    if candidates and not context_scheme:
        return refuse(clarify.clarification(candidates))
    if clarify.needs_fund(query) and not context_scheme:
        return refuse(clarify.clarification())
    return GuardDecision(True, query)
