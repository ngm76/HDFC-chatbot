"""Phase 8: the full query path (architecture §4.2).

PII check → guards → (conversation context) → retrieve → generate → assemble.
A message with PII is blocked first, before anything else reads it (FR-10/11);
otherwise only the redacted query goes past the guards, and failures are logged
by type only, never with the user's text.

`history` is the recent conversation (redacted questions + answer texts, kept
in the UI session). It lets follow-ups ("And its exit load?", "What about Large
Cap?") inherit the fund and topic; facts still come from the retrieved cards.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Sequence

from src.guards.common import AnswerPayload
from src.guards.pii import redact
from src.guards.pipeline import pii_block, run_guards
from src.rag import context
from src.rag.assemble import assemble, generation_error, not_found, ungrounded
from src.rag.generate import (
    GenerationError,
    UngroundedNumberError,
    ValidationFailed,
    generate,
    generator_label,
)
from src.rag.holdings import absence_answer
from src.rag.retrieve import RetrievedChunk, intent_fields, one_page_covers, retrieve
from src.schemes import (
    ambiguous_schemes,
    detect_schemes,
    former_name_used,
    fuzzy_schemes,
    short_name,
)

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


def ask(
    message: str, history: Sequence[context.Turn] = (), selected_scheme: str | None = None
) -> Answer:
    """`selected_scheme`: the fund picked in the UI's scheme panel, used when the
    question names no fund (before falling back to the chat history)."""
    redacted, pii_types = redact(message.strip())
    if pii_types:  # blocked: nothing below ever sees the message
        decision = pii_block(pii_types, redacted)
        return Answer(decision.payload, None, decision.query)

    # A misspelled name that clearly means one scheme ("hdfc smal cap") is treated
    # like a selection, so retrieval filters by it and the UI says what was assumed.
    fuzzy = fuzzy_schemes(message) if not detect_schemes(message) else []
    matched = fuzzy[0] if len(fuzzy) == 1 else None
    pick = matched or selected_scheme
    # Carry the fund over only for questions naming none.
    carried = None
    if not detect_schemes(message):
        early = context.resolve(message, history, pick)
        carried = early.carried_scheme
        # An ambiguous name the user just typed ("HDFC cap fund") is asked about with
        # chips; only an explicit selection (left panel or a chip) settles it, not a
        # fund mentioned earlier in the chat.
        if early.carried_from == "chat" and ambiguous_schemes(message):
            carried = None
    decision = run_guards(message, context_scheme=carried)
    if not decision.allowed:
        return Answer(decision.payload, None, decision.query)

    query = decision.query
    resolved = context.resolve(query, history, pick)
    note = None
    if matched and resolved.carried_scheme == matched:
        note = f"Assumed you mean {short_name(matched)}."
    elif resolved.carried_from == "selection":
        note = f"Answering for {resolved.carried_scheme} (selected on the left)."
    elif resolved.carried_from == "chat":
        note = f"Follow-up: assumed you mean {resolved.carried_scheme} from earlier in the chat."
    renamed = former_name_used(query)
    if renamed:  # PRD §8: answer under the current name, mention the former once
        former, scheme = renamed
        note = f"{short_name(scheme)} was formerly called {former}."

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

    # PRD §8 factual comparison: several schemes are answered together only when
    # one official page states the fact for all of them; otherwise answer the first
    # and invite a second question (each answer keeps a single citation).
    schemes = resolved.schemes
    if len(schemes) > 1 and not one_page_covers(schemes, intent_fields(query)):
        rest = ", ".join(short_name(s) for s in schemes[1:])
        note = (f"Answered for {short_name(schemes[0])}; no single official page covers "
                f"both, so please ask about {rest} separately.")
        schemes = schemes[:1]
        resolved = replace(resolved, schemes=schemes)

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
    except ValidationFailed as exc:  # FR-4: rejected twice -> FR-1 fallback
        logger.warning("answer rejected by validator twice: %s", exc)
        return Answer(not_found(resolved.schemes), decision.pii_warning, query,
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
