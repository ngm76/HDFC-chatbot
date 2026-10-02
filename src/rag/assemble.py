"""Phase 8: turn a generation into the public answer payload (architecture §7).

Exactly one citation: the chunk the generator says it used. Last updated is the
newest fetched_at among all chunks passed to the generator.

Miss / error replies link the scheme page of the fund the question is about
(named, or carried over from the conversation). With no fund in play they carry
no link: a generic education page would be irrelevant to the question.
"""

from __future__ import annotations

from src.guards.common import AnswerPayload, make_payload, scheme_page_source
from src.rag.generate import Generation
from src.rag.retrieve import RetrievedChunk

NOT_FOUND_TEXT = "This prototype doesn't have that information in its sources, so I won't guess."
UNGROUNDED_TEXT = (
    "I can only give figures that are stated in the sources, and answering this would "
    "need figures that aren't there, so I won't guess."
)
ERROR_TEXT = "Sorry, I couldn't generate an answer right now. Please try again."
PAGE_HINT = " The scheme page linked below may help."


def assemble(generation: Generation, chunks: list[RetrievedChunk]) -> AnswerPayload:
    cited = chunks[generation.chunk_index]
    return AnswerPayload(
        text=generation.text,
        source_url=cited["url"],
        last_updated_from_sources=max(c["fetched_at"] for c in chunks) or None,
        refusal=False,
        refusal_reason=None,
    )


def _reply(text: str, schemes: list[str], reason: str) -> AnswerPayload:
    page = scheme_page_source(schemes[0]) if len(schemes) == 1 else None
    return make_payload(text + (PAGE_HINT if page else ""), page, refusal=True, refusal_reason=reason)


def not_found(schemes: list[str]) -> AnswerPayload:
    return _reply(NOT_FOUND_TEXT, schemes, "not_in_corpus")


def ungrounded(schemes: list[str]) -> AnswerPayload:
    return _reply(UNGROUNDED_TEXT, schemes, "not_in_corpus")


def generation_error(schemes: list[str]) -> AnswerPayload:
    return _reply(ERROR_TEXT, schemes, "error")
