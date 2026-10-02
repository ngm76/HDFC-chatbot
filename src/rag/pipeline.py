"""Phase 8: the full query path (architecture §4.2).

guards → (conversation context) → retrieve → generate → assemble. Only the
redacted query goes past the guards, and failures are logged by type only,
never with the user's text.

`history` is the recent conversation (redacted questions + answer texts, kept
in the UI session). It lets follow-ups ("And its exit load?", "What about Large
Cap?") inherit the fund and topic; facts still come from the retrieved cards.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from src.guards.common import AnswerPayload
from src.guards.pipeline import run_guards
from src.rag import context
from src.rag.assemble import assemble, generation_error, not_found, ungrounded
from src.rag.generate import GenerationError, UngroundedNumberError, generate, generator_label
from src.rag.holdings import absence_answer
from src.rag.retrieve import RetrievedChunk, retrieve
from src.schemes import detect_schemes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Answer:
    payload: AnswerPayload  # architecture §7 shape
    pii_warning: str | None = None  # shown by the UI next to the answer
    redacted_query: str = ""  # safe to display or keep in session history
    # Transparency: the chunks Chroma returned, which one was cited, and which
    # generator wrote the answer. Empty when guards answered without retrieval.
    retrieved: tuple[RetrievedChunk, ...] = ()
    cited_index: int | None = None
    generator: str | None = None
    # Set when the fund came from earlier in the conversation (shown in the UI).
    context_note: str | None = None


def ask(message: str, history: Sequence[context.Turn] = ()) -> Answer:
    # Carry the fund over from the conversation only for questions naming none.
    carried = None if detect_schemes(message) else context.resolve(message, history).carried_scheme
    decision = run_guards(message, context_scheme=carried)
    if not decision.allowed:
        return Answer(decision.payload, decision.pii_warning, decision.query)

    query = decision.query
    resolved = context.resolve(query, history)
    note = (
        f"Follow-up: assumed you mean {resolved.carried_scheme} from earlier in the chat."
        if resolved.carried_scheme else None
    )

    # "Does <fund> hold <company>?" with no match in the fund's full holdings list.
    # For a short follow-up ("What about Large Cap?") the company comes from the
    # previous question ("Does it hold Infosys?").
    if len(resolved.schemes) == 1:
        asked = [query]
        if resolved.search_text != query and resolved.previous_question:
            asked.append(resolved.previous_question)
        for text in asked:
            absent = absence_answer(text, resolved.schemes[0])
            if absent:
                return Answer(absent, decision.pii_warning, query, context_note=note)

    chunks = retrieve(resolved.search_text, schemes=resolved.schemes or None)
    if not chunks:
        return Answer(not_found(resolved.schemes), decision.pii_warning, query, context_note=note)

    # Short follow-ups are passed with the question they follow up, so the model
    # reads "What about Large Cap?" as "Does Large Cap hold Infosys?".
    gen_query = query
    if resolved.search_text != query and resolved.previous_question:
        gen_query = (
            f'{query} (follow-up to the previous question: "{resolved.previous_question}"; '
            "answer that question for the fund named here)"
        )
    label = generator_label()
    try:
        generation = generate(
            gen_query, chunks, context.transcript(history), resolved.carried_scheme
        )
    except UngroundedNumberError as exc:
        logger.warning("answer rejected: %s", exc)
        return Answer(ungrounded(resolved.schemes), decision.pii_warning, query,
                      tuple(chunks), None, label, note)
    except GenerationError as exc:
        logger.warning("generation failed: %s", exc)
        return Answer(generation_error(resolved.schemes), decision.pii_warning, query,
                      tuple(chunks), None, label, note)

    if not generation.found:
        return Answer(not_found(resolved.schemes), decision.pii_warning, query,
                      tuple(chunks), None, label, note)
    return Answer(
        assemble(generation, chunks), decision.pii_warning, query,
        tuple(chunks), generation.chunk_index, label, note,
    )
