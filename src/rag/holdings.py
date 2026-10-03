"""Definite answers when a fund does not hold a named company.

"Does HDFC Small Cap Fund hold Infosys?" - if the name appears in none of the
fund's holdings cards (which together cover the fund's full list in the monthly
factsheet), the answer is stated directly: "Infosys is not among the 85 holdings
listed for … in the factsheet as on 31 Aug 2026".
This is an exact, deterministic check, so no LLM is involved. When the name IS
found, the normal RAG path answers with the matching card.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, source_label
from src.ingest.official import human_date
from src.rag.retrieve import HOLDINGS_FIELDS, _collection
from src.schemes import short_name

# Pull the company name out of common "is X held" phrasings.
_NAME_PATTERNS = [
    re.compile(r"\b(?:hold|holds|own|owns|have|has|invest(?:s|ed)?\s+in)\s+(?:any\s+)?"
               r"(?:shares\s+of\s+|stake\s+in\s+)?(?P<name>[A-Za-z0-9&.' -]+?)\s*\??$", re.I),
    re.compile(r"\bhow\s+much\s+(?:of\s+)?(?P<name>[A-Za-z0-9&.' -]+?)\s+(?:does|do|is)\b", re.I),
    re.compile(r"\bis\s+(?P<name>[A-Za-z0-9&.' -]+?)\s+(?:in|part\s+of|among|held\s+by|one\s+of)\b", re.I),
]
_TRAILING = re.compile(r"\s+(ltd|limited|shares?|stocks?|equity)\.?$", re.I)
_NOT_A_NAME = re.compile(
    r"\b(hdfc|fund|scheme|large|small|flexi|elss|tax|saver|balanced|advantage|exit|load|"
    r"sip|nav|aum|expense|ratio|lock|benchmark|risk|manager|holdings?)\b",
    re.I,
)
_COUNT_RE = re.compile(r"(\d[\d,]*) holdings in total")
# The question must be about holdings: "what is the weather in Pune" also matches
# the "is X in" phrasing, but is not a holdings question.
_HOLDINGS_QUESTION_RE = re.compile(
    r"\b(hold|holds|held|holding|holdings|own|owns|stake|portfolio|invest(s|ed)?\s+in|"
    r"exposure|part\s+of\s+(the\s+)?(fund|portfolio|holdings)|among\s+(the\s+)?holdings)\b",
    re.I,
)


def asked_company(query: str) -> str | None:
    for pattern in _NAME_PATTERNS:
        m = pattern.search(query.strip())
        if not m:
            continue
        name = _TRAILING.sub("", m.group("name").strip(" .?")).strip()
        name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)
        if name and len(name.split()) <= 5 and not _NOT_A_NAME.search(name):
            return name
    return None


def absence_answer(query: str, scheme: str) -> AnswerPayload | None:
    """A direct "not among the holdings" answer, or None to use the normal path."""
    if not _HOLDINGS_QUESTION_RE.search(query):
        return None
    name = asked_company(query)
    if not name:
        return None
    cards = _collection().get(
        where={"$and": [{"scheme": scheme}, {"field": {"$in": list(HOLDINGS_FIELDS)}}]},
        include=["documents", "metadatas"],
    )
    if not cards["documents"]:
        return None
    pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.I)
    if any(pattern.search(doc) for doc in cards["documents"]):
        return None  # held: the normal RAG path answers with the matching card
    count = next((m.group(1) for d in cards["documents"] if (m := _COUNT_RE.search(d))), None)
    meta = cards["metadatas"][0]
    listed = f"the {count} holdings" if count else "the holdings"
    as_on = f" as on {human_date(meta['doc_date'])}" if meta.get("doc_date") else ""
    return AnswerPayload(
        text=(f"{name} is not among {listed} listed for {short_name(scheme)} (Direct Plan - "
              f"Growth) in the HDFC Mutual Fund monthly factsheet{as_on}."),
        source_url=meta["url"],
        source_label=source_label(meta["url"]),
        last_updated_from_sources=meta.get("fetched_at") or None,
        refusal=False,
        refusal_reason=None,
    )
