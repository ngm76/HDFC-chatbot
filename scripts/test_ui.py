"""Headless UI test (Phases 19 and 22) with Streamlit's AppTest; no browser needed.

Checks the PRD §9 states: welcome line, pinned facts-only note, the three example
chips and input hint; an answer with its source label and freshness line; the PII
block (warning shown, nothing added to the chat); clarify chips that re-ask for the
chosen fund; feedback controls. Uses the offline extractive generator, so it costs
no LLM tokens. Run from the project root:  python scripts/test_ui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["GENERATOR"] = "extractive"

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(PROJECT_ROOT / "src" / "app" / "main.py")
failures = 0


def check(name: str, ok: bool) -> None:
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


def html_text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    check("app runs without exceptions", not at.exception)
    page = html_text(at)
    check("welcome line (PRD §9)", "Hi! Ask me facts about 5 HDFC Mutual Fund schemes" in page)
    check("pinned facts-only note", "Facts-only. No investment advice." in page)
    labels = [b.label for b in at.button]
    check("three example chips", all(q in labels for q in (
        "What is the exit load on HDFC Small Cap Fund?",
        "How long is the HDFC ELSS Tax Saver lock-in?",
        "How do I download my capital gains statement?")))
    check("input hint", at.chat_input[0].placeholder ==
          "Ask a factual question. Don't share PAN, Aadhaar or account details.")
    check("no Groww source wording", "Source: Groww" not in page)

    # Example chip -> answer with a source label and a freshness line
    next(b for b in at.button if b.label.startswith("How long is the HDFC ELSS")).click().run()
    page = html_text(at)
    check("answer shows a readable source label", "Source: HDFC ELSS Tax Saver Fund" in page)
    check("answer shows 'Last updated from sources: DD Mon YYYY'",
          "Last updated from sources: " in page and " 2026" in page)
    check("feedback control on the answer", len(at.get("feedback")) >= 1)

    # PII block: warning shown, nothing added to the chat history
    before = len(at.session_state["history"])
    at.chat_input[0].set_value("My PAN is ABCDE1234F, show my ELSS lock-in date").run()
    check("PII block warning shown", any("For your safety" in w.value for w in at.warning))
    check("PII message not added to the chat", len(at.session_state["history"]) == before)
    check("raw PII not rendered anywhere", "ABCDE1234F" not in html_text(at) + " ".join(
        w.value for w in at.warning) + " ".join(i.value for i in at.info))

    # Ambiguous name -> chips -> answer for the chosen fund
    at.chat_input[0].set_value("What is the expense ratio of HDFC cap fund?").run()
    chips = [b for b in at.button if b.key and b.key.startswith("chip-")]
    check("clarify chips shown", {c.label for c in chips} >= {"HDFC Large Cap Fund", "HDFC Small Cap Fund"})
    next(c for c in chips if c.label == "HDFC Small Cap Fund").click().run()
    last_q, last_a = at.session_state["history"][-1]
    check("chip re-asks for the chosen fund", last_a.payload["source_url"] is not None
          and "Small Cap" in (last_a.payload["source_label"] or "") + last_a.payload["text"])
    check("no exceptions after interactions", not at.exception)

    print(f"\n{'all passed' if not failures else f'{failures} failed'}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
