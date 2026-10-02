"""Phase 5: rebuild the vector index from data/sources.csv.

load → chunk → embed → store (architecture §4.1), then write fetched_at back to
sources.csv for every URL that loaded. Run from the project root:

    python scripts/ingest.py            # reuse cached downloads in data/raw/
    python scripts/ingest.py --refresh  # re-download every URL
"""

from __future__ import annotations

import argparse
import csv
import logging
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the hdfc_mf_faq Chroma index")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--refresh", action="store_true", help="ignore data/raw/ cache")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # noisy font warnings
    started = time.perf_counter()

    print("1/4 loading ...")
    result = load_corpus(args.sources, use_cache=not args.refresh)
    if not result.documents:
        for err in result.errors:
            print(f"  FAIL {err.url} :: {err.message}")
        raise SystemExit("no documents loaded; index left unchanged")

    print("2/4 chunking ...")
    chunks = chunk_documents(result.documents)

    print(f"3/4 embedding {len(chunks)} chunks ...")
    vectors = embed_texts([c.text for c in chunks])

    print("4/4 storing ...")
    collection = rebuild_collection(chunks, vectors)
    updated = update_fetched_at(args.sources, result.documents)

    per_url = Counter(c.url for c in chunks)
    print("\nSummary")
    print(f"  URLs ok:     {len(result.documents)}")
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
