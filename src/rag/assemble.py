"""Turn a generation into the public answer payload (PRD §7 template, architecture §7).

Every response has one source link with a readable label and the ingest date of
the cited page ("Last updated from sources", shown as DD Mon YYYY by the UI).

Code-added sentences, within the three-sentence limit:
- FR-3: an expense-ratio answer adds "Regular Plan values differ; see the linked page."
- §8 stale data: when the cited document is past its freshness limit, "Please check
  the linked page for the latest value." The factsheet and TER file are judged by
  the date they state (their figures are "as on" that date); other pages by their
  ingest date.

Miss / error replies link the scheme page of the fund the question is about, or
the HDFC MF schemes listing when no single fund is in play (FR-1, FR-5).
"""

from __future__ import annotations

from datetime import date

from src.guards.common import (
    AnswerPayload,
    make_payload,
    scheme_page_source,
    schemes_listing_source,
    source_label,
    source_row,
)
from src.rag.generate import Generation
from src.rag.retrieve import RetrievedChunk
from src.rag.validate import MAX_SENTENCES, sentences

NOT_FOUND_TEXT = "I couldn't find this in the official sources, so I won't guess."
UNGROUNDED_TEXT = (
    "I can only give figures that are stated in the official sources, and answering "
    "this would need figures that aren't there, so I won't guess."
)
ERROR_TEXT = "Sorry, I couldn't generate an answer right now. Please try again."
PAGE_HINT = " The scheme page linked below may help."
LISTING_HINT = " The HDFC Mutual Fund schemes page linked below may help."
REGULAR_NOTE = "Regular Plan values differ; see the linked page."
STALE_NOTE = "Please check the linked page for the latest value."
DATED_DOC_TYPES = ("factsheet", "ter")  # figures "as on" the document's own date


def is_stale(chunk: RetrievedChunk, today: date | None = None) -> bool:
    row = source_row(chunk["url"]) or {}
    limit = (row.get("freshness_limit_days") or "").strip()
    if not limit.isdigit():
        return False
    as_of = chunk.get("doc_date") if chunk.get("doc_type") in DATED_DOC_TYPES else ""
    as_of = as_of or chunk["fetched_at"]
    try:
        age = ((today or date.today()) - date.fromisoformat(as_of)).days
    except ValueError:
        return False
    return age > int(limit)


def _with_notes(text: str, notes: list[str]) -> str:
    """Append notes, trimming the body so the total stays within three sentences."""
    notes = [n for n in notes if n not in text]
    if not notes:
        return text
    body = sentences(text)[: max(1, MAX_SENTENCES - len(notes))]
    return " ".join(body + notes[: MAX_SENTENCES - len(body)])


def assemble(generation: Generation, chunks: list[RetrievedChunk],
             today: date | None = None) -> AnswerPayload:
    cited = chunks[generation.chunk_index]
    notes = []
    if cited["field"] == "expense_ratio" and "Regular" not in generation.text:
        notes.append(REGULAR_NOTE)
    if is_stale(cited, today):
        notes.append(STALE_NOTE)
    return AnswerPayload(
        text=_with_notes(generation.text, notes),
        source_url=cited["url"],
        source_label=source_label(cited["url"]),
        last_updated_from_sources=cited["fetched_at"] or None,
        refusal=False,
        refusal_reason=None,
    )


def _reply(text: str, schemes: list[str], reason: str) -> AnswerPayload:
    page = scheme_page_source(schemes[0]) if len(schemes) == 1 else None
    if page:
        return make_payload(text + PAGE_HINT, page, refusal=True, refusal_reason=reason)
    return make_payload(text + LISTING_HINT, schemes_listing_source(), refusal=True,
                        refusal_reason=reason)


def not_found(schemes: list[str]) -> AnswerPayload:
    return _reply(NOT_FOUND_TEXT, schemes, "not_in_corpus")


def ungrounded(schemes: list[str]) -> AnswerPayload:
    return _reply(UNGROUNDED_TEXT, schemes, "not_in_corpus")


def generation_error(schemes: list[str]) -> AnswerPayload:
    return _reply(ERROR_TEXT, schemes, "error")
