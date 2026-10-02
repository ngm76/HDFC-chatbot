"""Debug: load + chunk the corpus and write every chunk to data/debug/chunks.txt.

Run from the project root:  python scripts/dump_chunks.py
Uses the data/raw/ cache, so it only hits the network for uncached URLs.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.chunk import chunk_documents  # noqa: E402
from src.ingest.load import load_corpus  # noqa: E402

OUT = PROJECT_ROOT / "data" / "debug" / "chunks.txt"


def main() -> None:
    result = load_corpus()
    chunks = chunk_documents(result.documents)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    per_url = Counter(c.url for c in chunks)
    with OUT.open("w", encoding="utf-8") as f:
        f.write(f"documents={len(result.documents)}  chunks={len(chunks)}\n\n")
        f.write("Chunks per URL (min/avg/max chars):\n")
        for doc in result.documents:
            sizes = [len(c.text) for c in chunks if c.url == doc.url]
            f.write(
                f"  {per_url[doc.url]:4d}  {min(sizes)}/{sum(sizes) // len(sizes)}/"
                f"{max(sizes)}  {doc.url}\n"
            )
        for err in result.errors:
            f.write(f"  FAIL  {err.url} :: {err.message}\n")
        for i, c in enumerate(chunks, 1):
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"CHUNK {i}/{len(chunks)}  chars={len(c.text)}\n")
            for key, value in c.metadata().items():
                f.write(f"{key}: {value}\n")
            f.write("-" * 80 + "\n")
            f.write(c.text + "\n")

    print(f"wrote {len(chunks)} chunks to {OUT}")


if __name__ == "__main__":
    main()
