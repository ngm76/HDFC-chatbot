"""Phase 6 check: print the top chunks for a few queries.

Run from the project root after `python scripts/ingest.py`:
    python scripts/debug_retrieve.py                  # default query set
    python scripts/debug_retrieve.py "your question"  # one custom query
    python scripts/debug_retrieve.py -i               # ask questions interactively
Scores are shown even when below MIN_SCORE, to help tune the floor.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.retrieve import MIN_SCORE, TOP_K, detect_schemes, retrieve  # noqa: E402

QUERIES = [
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the exit load for HDFC Small Cap Fund?",
    "What is the lock-in period of HDFC ELSS Tax Saver?",
    "What is the minimum SIP amount for HDFC Balanced Advantage Fund?",
    "What is the benchmark of HDFC Flexi Cap Fund?",
    "How do I download my capital gains statement?",
    # Off-topic: should fall below the floor.
    "What is the weather in Mumbai today?",
    "How do I apply for an HDFC Bank credit card?",
    "Recipe for paneer butter masala",
]


def show(query: str) -> None:
    print("=" * 90)
    print(f"Q: {query}")
    print(f"   schemes detected: {detect_schemes(query) or 'none (no filter)'}")
    kept = retrieve(query)
    raw = kept or retrieve(query, min_score=-1.0)
    status = f"{len(kept)} chunks kept" if kept else f"MISS (best < {MIN_SCORE})"
    print(f"   {status}")
    for i, c in enumerate(raw, 1):
        preview = " ".join(c["text"].split())[:160]
        print(f"   #{i} score={c['score']:.3f}  [{c['section_title'][:40]}]  scheme={c['scheme']}")
        print(f"       {c['url']}")
        print(f"       fetched_at={c['fetched_at']}  {preview}...")


def interactive() -> None:
    print("Type a question (empty line or Ctrl+C to quit).")
    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query:
            break
        show(query)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # chunks contain ₹; cp1252 consoles choke
    print(f"k={TOP_K}  min_score={MIN_SCORE}")
    args = sys.argv[1:]
    if args in (["-i"], ["--interactive"]):
        interactive()
    else:
        for q in args or QUERIES:
            show(q)


if __name__ == "__main__":
    main()
