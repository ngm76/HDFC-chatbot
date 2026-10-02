"""Run a scripted multi-turn conversation to check follow-up handling.

Run from the project root:
    python scripts/debug_chat.py            # uses the configured generator (Groq)
    python scripts/debug_chat.py --no-llm   # extractive fallback: checks context
                                            # handling + retrieval, no API calls
Each turn prints the carried-over fund (if any), the answer, and the top card.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if "--no-llm" in sys.argv:
    os.environ["GENERATOR"] = "extractive"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.context import HISTORY_TURNS  # noqa: E402
from src.rag.pipeline import ask  # noqa: E402

CONVERSATION = [
    "What is the exit load of HDFC Small Cap Fund?",
    "And its expense ratio?",                 # fund carried over
    "Who manages it?",                        # fund carried over
    "Does it hold Tata Steel?",               # carried over; 'Tata' is a holding, not an AMC
    "Does it hold Infosys?",                  # definite "not among the 87 holdings"
    "What about Large Cap?",                  # topic carried over, fund switched
    "What is the minimum SIP?",               # carried over (Large Cap now)
    "Should I buy it?",                       # still refused as advice
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    history: list[tuple[str, str]] = []
    print(f"context window: last {HISTORY_TURNS} exchanges\n")
    for question in CONVERSATION:
        answer = ask(question, history[-HISTORY_TURNS:])
        p = answer.payload
        top = answer.retrieved[0] if answer.retrieved else None
        print(f"Q: {answer.redacted_query}")
        if answer.context_note:
            print(f"   ↪ {answer.context_note}")
        kind = p["refusal_reason"] or "answer"
        print(f"   [{kind}] {p['text'][:220]}")
        if top:
            print(f"   top card: {top['field']} / {top['scheme']}")
        print()
        history.append((answer.redacted_query, p["text"]))


if __name__ == "__main__":
    main()
