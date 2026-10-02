"""Answer payload (architecture §7) and URL lookups from data/sources.csv.

Looks at role=ingest rows (the official corpus), role=reference rows (official
links that are never ingested, e.g. the HDFC MF schemes listing) and role=help rows
(the two Groww help-centre links, PRD Addendum A5). Every link a guard returns comes
from this file, never from the model.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import NotRequired, TypedDict
from urllib.parse import urlparse

from src.schemes import SHARED_SCHEME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES_CSV = PROJECT_ROOT / "data" / "sources.csv"

# Advice-refusal educational page; documented as such in data/schemes.md.
EDUCATIONAL_HOST = "amfiindia.com"


class AnswerPayload(TypedDict):
    """PRD §7 template: body (text), one source (url + readable label), and the
    ingest date of the cited page (ISO; the UI shows it as DD Mon YYYY)."""
    text: str
    source_url: str | None
    source_label: str | None  # e.g. "HDFC Small Cap Fund – scheme page"
    last_updated_from_sources: str | None
    refusal: bool
    refusal_reason: str | None
    chips: NotRequired[list[str]]  # scheme choices for an ambiguous name (clarify)


def make_payload(
    text: str,
    source: dict[str, str] | None,
    *,
    refusal: bool,
    refusal_reason: str | None = None,
) -> AnswerPayload:
    return AnswerPayload(
        text=text,
        source_url=source["url"] if source else None,
        source_label=(source or {}).get("label") or None,
        last_updated_from_sources=(source or {}).get("fetched_at") or None,
        refusal=refusal,
        refusal_reason=refusal_reason,
    )


def source_row(url: str) -> dict[str, str] | None:
    """The sources.csv row for a URL (label, freshness limit, fetched_at, ...)."""
    return next((r for r in _source_rows() if r["url"] == url), None)


def source_label(url: str) -> str | None:
    row = source_row(url)
    return row.get("label") or None if row else None


LINK_ROLES = ("ingest", "reference", "help")


@lru_cache(maxsize=1)
def _source_rows() -> tuple[dict[str, str], ...]:
    with SOURCES_CSV.open(encoding="utf-8", newline="") as handle:
        rows = [
            {k: (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]
    return tuple(r for r in rows if r.get("role") in LINK_ROLES and r.get("url"))


def corpus_last_fetched() -> str | None:
    """Newest fetched_at among the ingested pages (the corpus's last update)."""
    dates = [r["fetched_at"] for r in _source_rows() if r.get("role") == "ingest" and r.get("fetched_at")]
    return max(dates) if dates else None


def educational_source() -> dict[str, str]:
    """The official investor-education row used for advice / scope refusals."""
    for row in _source_rows():
        host = (urlparse(row["url"]).hostname or "").lower()
        if host == EDUCATIONAL_HOST or host.endswith("." + EDUCATIONAL_HOST):
            return row
    raise LookupError(f"no {EDUCATIONAL_HOST} row in {SOURCES_CSV}")


def scheme_page_source(scheme: str) -> dict[str, str] | None:
    """The scheme's official page (first ingest row for it), the link on misses."""
    for row in _source_rows():
        if row.get("scheme") == scheme and row.get("role") == "ingest":
            return row
    return None


def _row(role: str, **match: str) -> dict[str, str]:
    for row in _source_rows():
        if row.get("role") == role and all(row.get(k) == v for k, v in match.items()):
            return row
    raise LookupError(f"no role={role} {match} row in {SOURCES_CSV}")


def help_source(purpose: str) -> dict[str, str]:
    """Groww help-centre link: purpose "pii_block" (FR-11) or "non_mf_redirect" (FR-15)."""
    return _row("help", question_types=purpose)


def schemes_listing_source() -> dict[str, str]:
    """HDFC MF's list of all its schemes (for "scheme not in corpus", PRD §8)."""
    return _row("reference", doc_type="schemes_listing")


def factsheet_source(scheme: str | None = None) -> dict[str, str]:
    """Factsheet row for the scheme if one exists, else the shared AMC factsheet.
    Among candidates, the PDF itself beats the (JS-rendered) hub page."""
    rows = [r for r in _source_rows() if r.get("doc_type") == "factsheet"]
    for wanted in ([scheme] if scheme else []) + [SHARED_SCHEME]:
        matches = [r for r in rows if r.get("scheme") == wanted]
        if matches:
            return max(matches, key=lambda r: r["url"].lower().split("?")[0].endswith(".pdf"))
    raise LookupError(f"no factsheet ingest row in {SOURCES_CSV}")
