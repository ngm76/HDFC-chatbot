"""Streamlit chat UI (Phases 9 and 19, PRD §9, architecture §12).

Run from the project root:  streamlit run src/app/main.py

A single chat screen, per PRD §9: welcome line, a pinned "Facts-only. No investment
advice." note, the most asked questions as tappable chips, the input hint, answer
bubbles (body, source label opening in a new tab, freshness line), the PII block
state (inline warning, input cleared, nothing sent or stored), chips for ambiguous
fund names, and 👍 / 👎 feedback with an optional reason. No transaction calls to
action.

Chat history lives only in st.session_state (per browser tab) and holds the
redacted question, never the raw input. Feedback is session-only (Addendum A3).
Nothing is written to disk. The last 25 exchanges are passed to the pipeline as
context for follow-up questions.
"""

from __future__ import annotations

import html
import sys
from datetime import date
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.guards.common import corpus_last_fetched  # noqa: E402
from src.ingest.official import human_date  # noqa: E402
from src.rag.context import HISTORY_TURNS  # noqa: E402
from src.rag.pipeline import Answer, ask  # noqa: E402

APP_NAME = "Mutual Funds FAQ"
# PRD §9 copy, verbatim.
WELCOME = (
    "Hi! Ask me facts about 5 HDFC Mutual Fund schemes – expense ratio, exit load, "
    "SIP minimums, lock-in, riskometer, benchmark or statements."
)
FACTS_ONLY_NOTE = "Facts-only. No investment advice."
INPUT_HINT = "Ask a factual question. Don't share PAN, Aadhaar or account details."
# Most asked questions: the PRD §9 examples first, then the most common question
# types in the golden set. A fixed list: the app does not record what users ask.
MOST_ASKED = [
    "What is the exit load on HDFC Small Cap Fund?",
    "How long is the HDFC ELSS Tax Saver lock-in?",
    "How do I download my capital gains statement?",
    "What is the expense ratio of HDFC Flexi Cap Fund?",
    "What is the minimum SIP amount for HDFC Balanced Advantage Fund?",
    "What is the riskometer level of HDFC Large Cap Fund?",
    "What is the benchmark of HDFC Small Cap Fund?",
    "How do I get my CAS?",
]
FEEDBACK_REASONS = ["Wrong", "Outdated", "Not helpful"]
STALE_AFTER_DAYS = 3  # the daily refresh normally keeps data under a day old
DISCLAIMER = (
    "Facts-only answers from official HDFC Mutual Fund, SEBI and AMFI pages. This is "
    "not investment advice. Mutual fund investments are subject to market risks. Read "
    "all scheme-related documents carefully."
)
AFFILIATION = "A prototype; not affiliated with HDFC Mutual Fund, SEBI or AMFI."

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea { font-family: 'Inter', sans-serif; }
footer, [data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 1.2rem; max-width: 860px; }

.topbar { display:flex; justify-content:space-between; align-items:center;
          padding: 8px 0 12px; border-bottom: 1px solid #EEF0F3; margin-bottom: 14px;
          position: sticky; top: 0; z-index: 999; background: #fff; }
.brand { font-size: 22px; font-weight: 700; color:#111827; }
.brand .dot { display:inline-block; width:12px; height:12px; border-radius:50%;
              background:#0E9F6E; margin-right:8px; vertical-align:middle; }
.note-pill { font-size:12px; font-weight:600; color:#0E9F6E; background:#E9F8F1;
             border-radius:999px; padding:5px 12px; }
.welcome { color:#4B5563; font-size:14px; margin: 0 0 14px; }
.asked-title { font-size:13px; font-weight:600; color:#374151; margin: 4px 0 8px; }

.src-pill { display:inline-block; font-size:12px; font-weight:600; color:#0E9F6E !important;
            border:1px solid #BFE9D7; border-radius:999px; padding:2px 10px; text-decoration:none; }
.fresh { display:block; font-size:12px; color:#6B7280; margin-top:6px; }

.stButton > button { border-radius:999px; border:1px solid #D1D5DB; font-size:13px;
                     text-align:left; justify-content:flex-start; }
.stButton > button:hover { border-color:#0E9F6E; color:#0E9F6E; }
[data-testid="stChatMessage"] { border-radius:16px; padding:10px 14px; background:#F7F8FA; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background:#E9F8F1; flex-direction: row-reverse; text-align:right; }
.footer { font-size:11.5px; color:#9CA3AF; text-align:center; margin-top:18px; line-height:1.5; }
</style>
"""


def _dmy(iso: str | None) -> str:
    """'2026-10-02' -> '02 Oct 2026' (PRD §7 DD Mon YYYY)."""
    try:
        return human_date(iso) if iso else ""
    except ValueError:
        return iso or ""


@st.cache_resource(show_spinner="Loading the search index…")
def _warm_up() -> None:
    """Load the embedding model and Chroma collection once per server process."""
    from src.rag.retrieve import retrieve

    retrieve("warm up")


def _staleness_note() -> str | None:
    """A warning when the sources were last fetched more than STALE_AFTER_DAYS ago
    (e.g. the scheduled refresh has been failing)."""
    last = corpus_last_fetched()
    if not last:
        return None
    age = (date.today() - date.fromisoformat(last)).days
    if age <= STALE_AFTER_DAYS:
        return None
    return (
        f"Data last refreshed on {_dmy(last)} ({age} days ago). Figures such as NAV, fund "
        "size and holdings may have changed since."
    )


def _ask_later(question: str, scheme: str | None = None) -> None:
    st.session_state.pending = (question, scheme)


def render_most_asked() -> None:
    """Most asked questions as tappable chips (two columns)."""
    cols = st.columns(2)
    for i, question in enumerate(MOST_ASKED):
        with cols[i % 2]:
            st.button(question, key=f"asked-{i}", on_click=_ask_later, args=(question,),
                      use_container_width=True, help=f"Ask: {question}")


def render_feedback(index: int) -> None:
    """👍 / 👎 with an optional reason; kept in this session only (Addendum A3)."""
    rating = st.feedback("thumbs", key=f"fb-{index}")
    if rating == 0:
        st.pills("What went wrong? (optional)", FEEDBACK_REASONS, key=f"fb-reason-{index}")
    elif rating == 1:
        st.caption("Thanks for the feedback.")


def render_answer(answer: Answer, index: int, question: str) -> None:
    payload = answer.payload
    if answer.context_note:
        st.caption(f"↪ {answer.context_note}")
    if payload["refusal"]:
        st.info(payload["text"])
    else:
        st.markdown(payload["text"])
    if payload.get("chips"):
        cols = st.columns(len(payload["chips"]))
        for col, chip in zip(cols, payload["chips"]):
            with col:
                st.button(chip, key=f"chip-{index}-{chip}", on_click=_ask_later,
                          args=(question, f"{chip} Direct Growth"),
                          help=f"Answer this question for {chip}")
    parts = []
    if payload["source_url"]:
        label = payload.get("source_label") or "Source"
        parts.append(
            f'<a class="src-pill" href="{html.escape(payload["source_url"])}" target="_blank" '
            f'rel="noopener" aria-label="Source: {html.escape(label)} (opens in a new tab)">'
            f'Source: {html.escape(label)} ↗</a>'
        )
    if payload["last_updated_from_sources"]:
        parts.append(
            f'<span class="fresh">Last updated from sources: '
            f'{html.escape(_dmy(payload["last_updated_from_sources"]))}</span>'
        )
    if parts:
        st.markdown("".join(parts), unsafe_allow_html=True)
    if payload["refusal_reason"] != "clarify":
        render_feedback(index)


def render_pii_block(answer: Answer) -> None:
    """PRD §9 PII block state: inline warning above the input; nothing was sent or kept."""
    payload = answer.payload
    st.warning(payload["text"], icon="🔒")
    if payload["source_url"]:
        label = payload.get("source_label") or "Help centre"
        st.markdown(
            f'<a href="{html.escape(payload["source_url"])}" target="_blank" rel="noopener" '
            f'aria-label="{html.escape(label)} (opens in a new tab)">{html.escape(label)} ↗</a>',
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🟢", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)

    # --- Header (the facts-only note is pinned: sticky header) -------------------
    st.markdown(
        f'<div class="topbar"><div class="brand"><span class="dot"></span>{APP_NAME}</div>'
        f'<div class="note-pill" role="note">{FACTS_ONLY_NOTE}</div></div>'
        f'<div class="welcome">{html.escape(WELCOME)}</div>',
        unsafe_allow_html=True,
    )
    stale = _staleness_note()
    if stale:
        st.warning(stale, icon="⏳")
    _warm_up()

    history: list[tuple[str, Answer]] = st.session_state.setdefault("history", [])

    # The input is pinned to the bottom wherever it is called, so the question is
    # handled first and the page is then drawn from the updated history.
    typed = st.chat_input(INPUT_HINT)
    pending = st.session_state.pop("pending", None)
    question, scheme = (typed, None) if typed else (pending or (None, None))
    if question:
        # Last HISTORY_TURNS exchanges (redacted questions + answer texts) as context
        # for follow-ups; session memory only.
        turns = [(q, a.payload["text"]) for q, a in history][-HISTORY_TURNS:]
        with st.spinner("Looking it up…"):
            answer = ask(question, turns, selected_scheme=scheme)
        if answer.payload["refusal_reason"] == "pii":
            # Blocked: not shown as a chat message and not kept in history.
            st.session_state.pii_block = answer
        else:
            st.session_state.pop("pii_block", None)
            # Store only the redacted question; the raw input is dropped here.
            history.append((answer.redacted_query, answer))

    # --- Most asked questions: prominent on an empty chat, then tucked away ------
    if not history:
        st.markdown('<div class="asked-title">Most asked questions</div>', unsafe_allow_html=True)
        render_most_asked()
    else:
        with st.expander("Most asked questions"):
            render_most_asked()
        if st.button("Clear chat", key="clear-chat"):
            history.clear()
            st.session_state.pop("pii_block", None)
            st.rerun()

    # --- Chat ----------------------------------------------------------------------
    for i, (asked, answer) in enumerate(history):
        with st.chat_message("user"):
            st.write(asked)
        with st.chat_message("assistant"):
            render_answer(answer, i, asked)

    blocked = st.session_state.get("pii_block")
    if blocked:
        render_pii_block(blocked)

    st.markdown(f'<div class="footer">{DISCLAIMER}<br>{AFFILIATION}</div>',
                unsafe_allow_html=True)


main()
