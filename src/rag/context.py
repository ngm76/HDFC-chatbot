"""Conversation context: the last HISTORY_TURNS exchanges, used to understand
follow-up questions ("And its expense ratio?", "What about Large Cap?").

Only the redacted questions and the answer texts are kept (UI session memory,
never written to disk). History helps interpret a follow-up; facts in answers
must still come from the excerpts retrieved for the current question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from src.schemes import detect_schemes

HISTORY_TURNS = 25  # previous question/answer exchanges kept as context
MAX_ANSWER_CHARS_IN_CONTEXT = 300  # long answers (holdings lists) are shortened

Turn = tuple[str, str]  # (redacted question, answer text)

_FOLLOW_UP_RE = re.compile(
    r"^\s*(and|also|what\s+about|how\s+about|same\s+for|for|what\s+of|then|ok(ay)?)\b", re.I
)


@dataclass(frozen=True)
class Resolved:
    schemes: list[str]  # schemes to filter retrieval by (named or carried over)
    search_text: str  # text used for retrieval (may include the previous question)
    carried_scheme: str | None  # set when the fund was not named in the question
    previous_question: str | None
    carried_from: str | None = None  # "selection" (UI scheme picker) or "chat"


def recent(history: Sequence[Turn]) -> list[Turn]:
    return list(history)[-HISTORY_TURNS:]


def _last_scheme(history: Sequence[Turn]) -> str | None:
    """The most recent single scheme mentioned (questions first, then answers)."""
    for question, answer in reversed(recent(history)):
        for text in (question, answer):
            schemes = detect_schemes(text)
            if len(schemes) == 1:
                return schemes[0]
    return None


def resolve(query: str, history: Sequence[Turn], selected: str | None = None) -> Resolved:
    """`selected`: the scheme picked in the UI. Priority for a question that names
    no fund: the selected scheme, then the most recent fund in the chat."""
    turns = recent(history)
    previous = turns[-1][0] if turns else None
    schemes = detect_schemes(query)
    carried = carried_from = None
    if not schemes:
        if selected:
            carried, carried_from = selected, "selection"
        else:
            carried = _last_scheme(turns)
            carried_from = "chat" if carried else None
        if carried:
            schemes = [carried]
    # A short follow-up ("What about Large Cap?") borrows the previous question's
    # topic for the search; the scheme filter still comes from this question.
    search_text = query
    if previous and _FOLLOW_UP_RE.match(query) and len(query.split()) <= 8:
        search_text = f"{previous} {query}"
    return Resolved(schemes, search_text, carried, previous, carried_from)


def transcript(history: Sequence[Turn]) -> str:
    """Compact text of the recent exchanges for the generator prompt."""
    lines = []
    for question, answer in recent(history):
        short = answer if len(answer) <= MAX_ANSWER_CHARS_IN_CONTEXT else (
            answer[:MAX_ANSWER_CHARS_IN_CONTEXT].rsplit(" ", 1)[0] + " …"
        )
        lines.append(f"User: {question}\nAssistant: {short}")
    return "\n".join(lines)
