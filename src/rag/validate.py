"""Post-generation validator (PRD FR-4, §7 tone).

Rejects an answer that contains a return figure, a recommendation verb or hype word
("should", "better", "best", "suitable", "safe", "good", "ideal", "recommended",
"guaranteed"), a first-person opinion, more than three sentences, or a link that is
not in the source list. The generator regenerates once, then the pipeline falls
back to the FR-1 "couldn't find this in the official sources" reply.

RETURN_FIGURE_RE is shared with the ingest strict check (no indexed chunk may carry
a return figure).
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES_CSV = PROJECT_ROOT / "data" / "sources.csv"
MAX_SENTENCES = 3

# A returns figure: "Returns (%) 20.34", "CAGR 12.5%", "since inception 13.18%",
# "15% returns".
RETURN_FIGURE_RE = re.compile(
    r"\b(returns?|CAGR|XIRR)\b[^.\n]{0,20}?(?:\(%\))?\s*[:\-]?\s*-?\d+(?:\.\d+\s*%?|\s*%)"
    r"|\bsince inception\b[^.\n]{0,15}?\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*%\s*(?:p\.?a\.?\s*)?(?:returns?|CAGR)\b",
    re.I,
)
# FR-4 recommendation verbs and §7 judgement words.
BANNED_WORDS_RE = re.compile(
    r"\b(should|better|best|suitable|safe|safer|safest|good|ideal|recommend(s|ed|ation)?|"
    r"guarantee(s|d)?)\b",
    re.I,
)
FIRST_PERSON_OPINION_RE = re.compile(r"\bI\s+(think|believe|feel|would\s+suggest|'d\s+suggest|suggest)\b", re.I)
_URL_RE = re.compile(r"https?://[^\s)\]]+|\bwww\.[^\s)\]]+", re.I)
_ABBREVIATIONS = re.compile(r"\b(Rs|No|Nos|e\.g|i\.e|p\.a|viz|approx|Ltd|Co|vs|Mr|Ms|Dr)\.", re.I)


class ValidationError(Exception):
    """The answer broke an FR-4 rule; the message names the rule (no user text)."""


def sentences(text: str) -> list[str]:
    protected = _ABBREVIATIONS.sub(lambda m: m.group(0)[:-1] + "\x00", text.strip())
    parts = [s for s in re.split(r"(?<=[.!?])\s+", protected) if s.strip()]
    return [s.replace("\x00", ".") for s in parts]


@lru_cache(maxsize=1)
def _known_urls() -> frozenset[str]:
    with SOURCES_CSV.open(encoding="utf-8", newline="") as handle:
        return frozenset((r.get("url") or "").strip().rstrip("/").lower()
                         for r in csv.DictReader(handle) if r.get("url"))


def check(text: str, *, verbatim: bool = False) -> None:
    """Raise ValidationError if `text` breaks FR-4. `verbatim`: the text is quoted
    from an official source (offline fallback), so only the return-figure and link
    rules apply (the source's own wording may contain e.g. "better")."""
    if len(sentences(text)) > MAX_SENTENCES:
        raise ValidationError("more than three sentences")
    if RETURN_FIGURE_RE.search(text):
        raise ValidationError("contains a return figure")
    for url in _URL_RE.findall(text):
        normal = url.rstrip(".,;").rstrip("/").lower()
        normal = normal if normal.startswith("http") else "https://" + normal
        if normal not in _known_urls():
            raise ValidationError("contains a link that is not in the source list")
    if verbatim:
        return
    word = BANNED_WORDS_RE.search(text)
    if word:
        raise ValidationError(f"uses the word '{word.group(0).lower()}' (recommendation / judgement)")
    if FIRST_PERSON_OPINION_RE.search(text):
        raise ValidationError("gives a first-person opinion")
