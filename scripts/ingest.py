"""Phase 5: rebuild the vector index from data/sources.csv.

load → chunk → embed → store (architecture §4.1), then write fetched_at back to
sources.csv for every URL that loaded. Run from the project root:

    python scripts/ingest.py                     # reuse cached downloads in data/raw/
    python scripts/ingest.py --refresh           # re-download every URL
    python scripts/ingest.py --refresh --strict  # deployment build: fail (exit 1) if any
                                                 # page failed or lacks core facts
    python scripts/ingest.py --refresh --check-only  # load + strict checks only; the
                                                     # index is not touched
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.chunk import chunk_documents  # noqa: E402
from src.ingest.embed import embed_texts  # noqa: E402
from src.ingest.load import DEFAULT_SOURCES, Document, load_corpus  # noqa: E402
from src.ingest.store import CHROMA_DIR, COLLECTION_NAME, rebuild_collection  # noqa: E402
from src.rag.validate import RETURN_FIGURE_RE  # noqa: E402
from src.schemes import SCHEMES, SHARED_SCHEME  # noqa: E402


def update_fetched_at(sources_csv: Path, docs: list[Document]) -> int:
    """Set fetched_at on rows whose URL loaded; other rows keep their old value."""
    fetched = {d.url: d.fetched_at for d in docs}
    with sources_csv.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    updated = 0
    for row in rows:
        url = (row.get("url") or "").strip()
        if url in fetched:
            row["fetched_at"] = fetched[url]
            updated += 1
    with sources_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return updated


# Text every document of a type must contain. If one is missing, the page probably
# changed layout or came back partial (e.g. a bot-protection page), so a strict build
# refuses to publish it. Values: label -> pattern (case-insensitive).
REQUIRED_TEXT = {
    "scheme_page": {"TER": r"\bTER\b", "min SIP": r"Min SIP", "exit load": r"Exit Load",
                    "benchmark": r"Benchmark", "riskometer": r"Riskometer", "AUM": r"\bAUM\b",
                    "fund managers": r"Fund Managers"},
    "kim": {"exit load": r"exit load", "minimum investment": r"minimum (application|investment|amount)",
            "riskometer": r"risk-?o-?meter", "benchmark": r"benchmark"},
    "factsheet": {"riskometer": r"risk-?o-?meter", "expense ratio": r"expense ratio"},
    "ter": {"total TER": r"Total TER"},
    "statement_guide": {"statement": r"statement"},
    "riskometer": {"risk levels": r"Very High"},
}
# Scheme-specific additions (the ELSS lock-in must come from HDFC's own documents).
REQUIRED_TEXT_ELSS = {"lock-in": r"lock[- ]?in"}
# Names each shared document must mention for all five schemes (TER file spelling for ELSS).
REQUIRED_SCHEMES = {
    "factsheet": ("HDFC Large Cap Fund", "HDFC Flexi Cap Fund", r"HDFC ELSS Tax ?Saver",
                  "HDFC Small Cap Fund", "HDFC Balanced Advantage Fund"),
    "ter": ("HDFC Large Cap Fund", "HDFC Flexi Cap Fund", r"HDFC ELSS - Tax Saver Fund",
            "HDFC Small Cap Fund", "HDFC Balanced Advantage Fund"),
}
# Performance content the loader must have dropped from scheme pages (PRD: no returns).
FORBIDDEN_TEXT = {"scheme_page": r"since inception|Scheme Returns|Historical Performance"}


# Fact cards every scheme must have after chunking (PRD §4 question types + A1 extras).
REQUIRED_CARDS = ("expense_ratio", "exit_load", "min_sip", "riskometer", "benchmark", "nav",
                  "aum", "fund_managers", "holdings", "holdings_breakdown", "overview")
REQUIRED_CARDS_ELSS = ("lock_in",)
REQUIRED_SHARED = ("statement_steps", "riskometer_levels", "definition")


def card_problems(chunks) -> list[str]:
    problems = []
    for scheme in SCHEMES:
        fields = {c.field for c in chunks if c.scheme == scheme}
        required = REQUIRED_CARDS + (REQUIRED_CARDS_ELSS if "ELSS" in scheme else ())
        missing = [f for f in required if f not in fields]
        if missing:
            problems.append(f"{scheme}: no card for {', '.join(missing)}")
    shared = {c.field for c in chunks if c.scheme == SHARED_SCHEME}
    missing = [f for f in REQUIRED_SHARED if f not in shared]
    if missing:
        problems.append(f"shared documents: no chunk for {', '.join(missing)}")
    for c in chunks:
        hit = RETURN_FIGURE_RE.search(c.text)
        if hit:
            problems.append(f"return figure in chunk {c.chunk_id} ({c.section_title[:60]}): "
                            f"{hit.group(0)[:60]!r}")
    return problems


# KIMs are revised on their own schedule; a newer KIM is detected by check_links.py instead.
DATED_DOC_TYPES = ("factsheet", "ter")


def stale_editions(sources_csv: Path, chunks, today: date | None = None) -> list[str]:
    """Dated documents (factsheet, TER file) older than their freshness limit
    (PRD §8). A warning in the build log, not a failure: a late edition must not stop
    the daily refresh of everything else. Fix: update the row's URL (README checklist)."""
    with sources_csv.open(encoding="utf-8", newline="") as handle:
        rows = {r["url"]: r for r in csv.DictReader(handle)}
    dates: dict[str, str] = {}
    for c in chunks:
        if c.doc_type in DATED_DOC_TYPES and c.doc_date:
            dates[c.url] = max(dates.get(c.url, ""), c.doc_date)
    warnings = []
    for url, as_of in dates.items():
        row = rows.get(url, {})
        limit = (row.get("freshness_limit_days") or "").strip()
        if not limit.isdigit():
            continue
        age = ((today or date.today()) - date.fromisoformat(as_of)).days
        if age > int(limit):
            warnings.append(f"{row.get('label') or url} is dated {as_of} ({age} days; limit "
                            f"{limit}): check its hub page for a newer edition and update "
                            "data/sources.csv")
    return warnings


# Document types every registered scheme needs in data/sources.csv.
REQUIRED_SCHEME_DOCS = ("scheme_page", "kim")


def registry_problems(sources_csv: Path) -> list[str]:
    """The scheme registry (src/schemes.py) and data/sources.csv must agree: every
    registered scheme has its scheme page and KIM rows, and every scheme in
    sources.csv is registered."""
    with sources_csv.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("role") or "") == "ingest"]
    problems = []
    for scheme in SCHEMES:
        have = {r["doc_type"] for r in rows if r["scheme"] == scheme}
        missing = [d for d in REQUIRED_SCHEME_DOCS if d not in have]
        if missing:
            problems.append(f"{scheme} is in the scheme registry but data/sources.csv has no "
                            f"{', '.join(missing)} row")
    for name in sorted({r["scheme"] for r in rows} - set(SCHEMES) - {SHARED_SCHEME}):
        problems.append(f"{name} is in data/sources.csv but not in the scheme registry "
                        "(src/schemes.py SCHEME_REGISTRY)")
    return problems


def strict_problems(result) -> list[str]:
    problems = [f"failed to load {e.url}: {e.message}" for e in result.errors]
    for doc in result.documents:
        required = dict(REQUIRED_TEXT.get(doc.doc_type, {}))
        if "ELSS" in doc.scheme and doc.doc_type in ("scheme_page", "kim"):
            required.update(REQUIRED_TEXT_ELSS)
        missing = [label for label, pattern in required.items()
                   if not re.search(pattern, doc.text, re.I)]
        missing += [name.replace(" ?", " ")
                    for name in REQUIRED_SCHEMES.get(doc.doc_type, ())
                    if not re.search(name, doc.text, re.I)]
        if missing:
            problems.append(f"{doc.scheme} {doc.doc_type}: missing {', '.join(missing)} ({doc.url})")
        forbidden = FORBIDDEN_TEXT.get(doc.doc_type)
        if forbidden and re.search(forbidden, doc.text, re.I):
            problems.append(f"{doc.scheme} {doc.doc_type}: performance text not removed ({doc.url})")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the hdfc_mf_faq Chroma index")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--refresh", action="store_true", help="ignore data/raw/ cache")
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 1 without touching the index if any page failed or lacks core facts "
             "(use in deployment builds so a bad fetch never goes live)",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="load, chunk and run the strict checks, then stop (no embedding or index "
             "changes)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # noisy font warnings
    started = time.perf_counter()

    print("1/4 loading ...")
    result = load_corpus(args.sources, use_cache=not args.refresh)
    for err in result.stale:
        print(f"  STALE {err.url} :: {err.message}")
    if not result.documents:
        for err in result.errors:
            print(f"  FAIL {err.url} :: {err.message}")
        raise SystemExit("no documents loaded; index left unchanged")

    print("2/4 chunking ...")
    chunks = chunk_documents(result.documents)
    for warning in stale_editions(args.sources, chunks):
        print(f"  STALE EDITION: {warning}")
    if args.strict or args.check_only:
        problems = registry_problems(args.sources) + strict_problems(result) + card_problems(chunks)
        for problem in problems:
            print(f"  STRICT: {problem}")
        if problems:
            raise SystemExit("strict mode: refusing to publish incomplete data; index left unchanged")
        if args.check_only:
            per_field = Counter(c.field or "(none)" for c in chunks)
            print(f"check passed: {len(result.documents)} pages loaded "
                  f"({len(result.stale)} from last good copy), {len(chunks)} chunks; index not touched")
            print("  chunks per field: " + ", ".join(f"{f} {n}" for f, n in per_field.most_common()))
            return

    print(f"3/4 embedding {len(chunks)} chunks ...")
    vectors = embed_texts([c.text for c in chunks])

    print("4/4 storing ...")
    collection = rebuild_collection(chunks, vectors)
    updated = update_fetched_at(args.sources, result.documents)

    per_url = Counter(c.url for c in chunks)
    print("\nSummary")
    print(f"  URLs ok:     {len(result.documents)}")
    print(f"  URLs stale (last good copy): {len(result.stale)}")
    print(f"  URLs failed: {len(result.errors)}")
    print(f"  seeds skipped (not fetched): {result.skipped_seeds}")
    for doc in result.documents:
        print(f"    ok   {per_url[doc.url]:4d} chunks  {doc.url}")
    for err in result.errors:
        print(f"    FAIL {err.url} :: {err.message}")
    print(f"  chunks stored: {collection.count()} in {COLLECTION_NAME!r} at {CHROMA_DIR}")
    print(f"  sources.csv fetched_at updated: {updated} rows")
    print(f"  took {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
