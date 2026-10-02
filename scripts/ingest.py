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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.chunk import chunk_documents  # noqa: E402
from src.ingest.embed import embed_texts  # noqa: E402
from src.ingest.load import DEFAULT_SOURCES, Document, load_corpus  # noqa: E402
from src.ingest.store import CHROMA_DIR, COLLECTION_NAME, rebuild_collection  # noqa: E402
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
# A returns figure in an indexed chunk (PRD: no performance claims). Matches e.g.
# "Returns (%) 20.34", "CAGR 12.5%", "since inception 13.18%", "15% returns".
RETURN_FIGURE_RE = re.compile(
    r"\b(returns?|CAGR|XIRR)\b[^.\n]{0,20}?(?:\(%\))?\s*[:\-]?\s*-?\d+(?:\.\d+\s*%?|\s*%)"
    r"|\bsince inception\b[^.\n]{0,15}?\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*%\s*(?:p\.?a\.?\s*)?(?:returns?|CAGR)\b",
    re.I,
)


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
    if args.strict or args.check_only:
        problems = strict_problems(result) + card_problems(chunks)
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
