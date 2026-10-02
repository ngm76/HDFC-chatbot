"""Phase 8 check: print the JSON answer payload for a few questions.

Run from the project root:
    python scripts/debug_ask.py                 # 2 factual + 1 advice question
    python scripts/debug_ask.py "your question"
Uses Claude if ANTHROPIC_API_KEY is set (or in .env), else the extractive fallback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.generate import generator_mode  # noqa: E402
from src.rag.pipeline import ask  # noqa: E402

QUESTIONS = [
    "What is the exit load on HDFC Small Cap Fund Direct Growth?",
    "What is the lock-in for HDFC ELSS Tax Saver?",
    "Should I buy HDFC Small Cap Fund?",
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"generator: {generator_mode()}")
    for question in sys.argv[1:] or QUESTIONS:
        answer = ask(question)
        print("=" * 80)
        print(f"Q: {answer.redacted_query}")
        if answer.pii_warning:
            print(f"PII warning: {answer.pii_warning}")
        print(json.dumps(answer.payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
