"""Answer payload (architecture §7) and URL lookups from data/sources.csv.

Looks at role=ingest rows (the Groww scheme pages that form the corpus) and
role=reference rows (official AMFI / HDFC links used only in refusal messages).
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

from src.schemes import SHARED_SCHEME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES_CSV = PROJECT_ROOT / "data" / "sources.csv"

# Advice-refusal educational page; documented as such in data/schemes.md.
EDUCATIONAL_HOST = "amfiindia.com"


class AnswerPayload(TypedDict):
    text: str
    source_url: str | None
    last_updated_from_sources: str | None
    refusal: bool
    refusal_reason: str | None


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
        last_updated_from_sources=(source or {}).get("fetched_at") or None,
        refusal=refusal,
        refusal_reason=refusal_reason,
    )


LINK_ROLES = ("ingest", "reference")


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
    """The scheme's page in the corpus (its Groww page), used as the link on misses."""
    for row in _source_rows():
        if row.get("scheme") == scheme and row.get("role") == "ingest":
            return row
    return None


def factsheet_source(scheme: str | None = None) -> dict[str, str]:
    """Factsheet row for the scheme if one exists, else the shared AMC factsheet.
    Among candidates, the PDF itself beats the (JS-rendered) hub page."""
    rows = [r for r in _source_rows() if r.get("doc_type") == "factsheet"]
    for wanted in ([scheme] if scheme else []) + [SHARED_SCHEME]:
        matches = [r for r in rows if r.get("scheme") == wanted]
        if matches:
            return max(matches, key=lambda r: r["url"].lower().split("?")[0].endswith(".pdf"))
    raise LookupError(f"no factsheet ingest row in {SOURCES_CSV}")
