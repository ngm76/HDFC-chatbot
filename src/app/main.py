"""Phase 9: Streamlit chat UI (architecture §3, PRD §6), Groww-style layout.

Run from the project root:  streamlit run src/app/main.py

Layout: a scheme picker on the left; fund cards with live figures (from the same
Chroma fact cards the chatbot answers from); a fact sheet for the selected fund;
quick-question pills; and the chat. Questions that name no fund are answered for
the selected fund. Styled to feel like a modern investing app, under our own
name and colours - not affiliated with Groww.

Chat history lives only in st.session_state (memory, per browser tab) and holds
the redacted question, never the raw input. Nothing is written to disk. The last
25 exchanges are passed to the pipeline as context for follow-up questions.
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
from src.rag.context import HISTORY_TURNS  # noqa: E402
from src.rag.facts import FundFacts, fund_facts  # noqa: E402
from src.rag.pipeline import Answer, ask  # noqa: E402
from src.schemes import SCHEMES  # noqa: E402

APP_NAME = "Mutual Funds FAQ"
WELCOME = (
    "Hi! Pick a scheme on the left or ask about any of five HDFC Mutual Fund schemes: "
    "expense ratio, exit load, minimum SIP, riskometer, benchmark, fund size, NAV, "
    "fund managers or holdings."
)
FACTS_ONLY_NOTE = "Facts-only. No investment advice."
STALE_AFTER_DAYS = 3  # the daily refresh normally keeps data under a day old
DISCLAIMER = (
    "Facts-only answers from public scheme pages. This is not investment "
    "advice. Mutual fund investments are subject to market risks. Read all "
    "scheme-related documents carefully."
)
AFFILIATION = "Not affiliated with Groww; facts are sourced from public Groww scheme pages."
# PRD §14 says to use the three that retrieve most reliably after the first eval;
# all three are retrieved at rank 1 from the Groww corpus (docs/eval_notes.md).
EXAMPLES = [
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the exit load on HDFC Small Cap Fund Direct Growth?",
    "What is the minimum SIP amount for HDFC Balanced Advantage Fund?",
]
# Quick questions for the selected fund: (pill label, question template).
QUICK_QUESTIONS = [
    ("Expense ratio", "What is the expense ratio of {fund}?"),
    ("Exit load", "What is the exit load of {fund}?"),
    ("Minimum SIP", "What is the minimum SIP amount for {fund}?"),
    ("Holdings analysis", "Can you give me the holdings analysis of {fund}?"),
    ("Top holdings", "What are the top holdings of {fund}?"),
    ("Fund managers", "Who are the fund managers of {fund}?"),
]
TAGS = {
    "HDFC Large Cap Fund Direct Growth": "Equity · Large Cap",
    "HDFC Flexi Cap Fund Direct Growth": "Equity · Flexi Cap",
    "HDFC ELSS Tax Saver Fund Direct Growth": "Equity · ELSS",
    "HDFC Small Cap Fund Direct Growth": "Equity · Small Cap",
    "HDFC Balanced Advantage Fund Direct Growth": "Hybrid · Dynamic",
}
ALL = "All schemes"
MIX_COLOURS = {"equity": "#0E9F6E", "debt": "#3B82F6", "cash and equivalents": "#9CA3AF"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea { font-family: 'Inter', sans-serif; }
footer, [data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 1.2rem; max-width: 1100px; }

.topbar { display:flex; justify-content:space-between; align-items:center;
          padding: 4px 0 14px; border-bottom: 1px solid #EEF0F3; margin-bottom: 14px; }
.brand { font-size: 22px; font-weight: 700; color:#111827; }
.brand .dot { display:inline-block; width:12px; height:12px; border-radius:50%;
              background:#0E9F6E; margin-right:8px; vertical-align:middle; }
.note-pill { font-size:12px; font-weight:600; color:#0E9F6E; background:#E9F8F1;
             border-radius:999px; padding:5px 12px; }
.welcome { color:#4B5563; font-size:14px; margin: 0 0 14px; }

.fund-card { border:1px solid #E5E7EB; border-radius:14px; padding:12px 14px; background:#fff;
             min-height:118px; transition: box-shadow .15s; }
.fund-card:hover { box-shadow: 0 4px 14px rgba(17,24,39,.08); }
.fund-card.active { border-color:#0E9F6E; background:#F2FBF7; }
.fund-name { font-weight:600; font-size:14px; color:#111827; line-height:1.3; min-height:36px; }
.tag { display:inline-block; font-size:11px; color:#6B7280; background:#F3F4F6;
       border-radius:6px; padding:2px 7px; margin:4px 0 8px; }
.nav { font-size:17px; font-weight:700; color:#111827; }
.sub { font-size:12px; color:#6B7280; }

.sheet { border:1px solid #E5E7EB; border-radius:16px; padding:18px 20px; background:#fff; margin:6px 0 4px; }
.sheet-title { font-size:19px; font-weight:700; color:#111827; }
.risk { display:inline-block; font-size:11px; font-weight:600; color:#B91C1C; background:#FEF2F2;
        border-radius:999px; padding:3px 10px; margin-left:8px; vertical-align:middle; }
.tiles { display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin:14px 0; }
.tile { background:#F7F8FA; border-radius:12px; padding:10px 12px; }
.tile .k { font-size:12px; color:#6B7280; }
.tile .v { font-size:17px; font-weight:700; color:#111827; margin-top:2px; }
.row { display:flex; gap:12px; padding:8px 0; border-top:1px solid #F1F2F4; font-size:13.5px; }
.row .k { width:150px; flex-shrink:0; color:#6B7280; }
.row .v { color:#111827; }
.mixbar { display:flex; height:10px; border-radius:999px; overflow:hidden; margin:6px 0 6px; }
.legend { font-size:12px; color:#4B5563; }
.legend span { margin-right:12px; }
.legend i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; }
.holding { display:flex; justify-content:space-between; font-size:13px; padding:4px 0;
           border-bottom:1px dashed #F1F2F4; }
.src-pill { display:inline-block; font-size:12px; font-weight:600; color:#0E9F6E !important;
            border:1px solid #BFE9D7; border-radius:999px; padding:2px 10px; text-decoration:none; }
.muted { font-size:12px; color:#6B7280; margin-left:8px; }

.stButton > button { border-radius:999px; border:1px solid #D1D5DB; font-size:13px; }
.stButton > button:hover { border-color:#0E9F6E; color:#0E9F6E; }
[data-testid="stChatMessage"] { border-radius:16px; padding:10px 14px; background:#F7F8FA; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background:#E9F8F1; flex-direction: row-reverse; text-align:right; }
.footer { font-size:11.5px; color:#9CA3AF; text-align:center; margin-top:18px; line-height:1.5; }
@media (max-width: 760px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
</style>
"""


def _short(scheme: str) -> str:
    return scheme.removesuffix(" Direct Growth")


@st.cache_resource(show_spinner="Loading the search index…")
def _warm_up() -> None:
    """Load the embedding model and Chroma collection once per server process."""
    from src.rag.retrieve import retrieve

    retrieve("warm up")


@st.cache_data(show_spinner=False)
def _facts(scheme: str) -> FundFacts:
    return fund_facts(scheme)


def _staleness_note() -> str | None:
    """A warning when the scheme pages were last fetched more than STALE_AFTER_DAYS
    ago (e.g. the scheduled refresh has been failing)."""
    last = corpus_last_fetched()
    if not last:
        return None
    age = (date.today() - date.fromisoformat(last)).days
    if age <= STALE_AFTER_DAYS:
        return None
    return (
        f"Data last refreshed on {last} ({age} days ago). Figures such as NAV, fund "
        "size and holdings may have changed since."
    )


def _select(scheme: str) -> None:
    st.session_state.scheme_choice = _short(scheme)


def _ask_later(question: str) -> None:
    st.session_state.pending = question


def render_fund_cards(selected: str | None) -> None:
    cols = st.columns(len(SCHEMES))
    for col, scheme in zip(cols, SCHEMES):
        f = _facts(scheme)
        active = " active" if scheme == selected else ""
        with col:
            st.markdown(
                f'<div class="fund-card{active}">'
                f'<div class="fund-name">{html.escape(_short(scheme))}</div>'
                f'<div class="tag">{html.escape(TAGS.get(scheme, ""))}</div>'
                f'<div class="nav">{html.escape(f.nav or "—")}</div>'
                f'<div class="sub">NAV{" · " + html.escape(f.nav_date) if f.nav_date else ""}'
                f' · TER {html.escape(f.get("expense_ratio"))}</div></div>',
                unsafe_allow_html=True,
            )
            st.button("View facts", key=f"card-{scheme}", on_click=_select, args=(scheme,),
                      use_container_width=True)


def render_fact_sheet(scheme: str) -> None:
    f = _facts(scheme)
    e = html.escape
    risk = f.get("riskometer", "")
    tiles = [
        ("NAV" + (f" · {f.nav_date}" if f.nav_date else ""), f.nav or "—"),
        ("Expense ratio", f.get("expense_ratio")),
        ("Fund size (AUM)", f.get("aum")),
        ("Min SIP", f.get("min_sip")),
    ]
    rows = [
        ("Exit load", f.get("exit_load")),
        ("Benchmark", f.get("benchmark")),
        ("Fund managers", f.get("fund_managers")),
        ("Min lump sum", f.get("min_lumpsum")),
        ("Holdings", f"{f.holdings_count} in total" if f.holdings_count else "—"),
    ]
    mix_bar = "".join(
        f'<div style="width:{max(p, 0):.2f}%;background:{MIX_COLOURS.get(n, "#F59E0B")}"></div>'
        for n, p in f.asset_mix
    )
    legend = "".join(
        f'<span><i style="background:{MIX_COLOURS.get(n, "#F59E0B")}"></i>{e(n)} {p:.2f}%</span>'
        for n, p in f.asset_mix
    )
    holdings = "".join(
        f'<div class="holding"><span>{e(name)}</span><span>{e(pct)}</span></div>'
        for name, pct in f.top_holdings[:5]
    )
    st.markdown(
        f'<div class="sheet">'
        f'<span class="sheet-title">{e(scheme)}</span>'
        + (f'<span class="risk">{e(risk)} risk</span>' if risk else "")
        + f'<div class="sub" style="margin-top:4px">{e(TAGS.get(scheme, ""))}</div>'
        f'<div class="tiles">'
        + "".join(f'<div class="tile"><div class="k">{e(k)}</div><div class="v">{e(v)}</div></div>'
                  for k, v in tiles)
        + "</div>"
        + "".join(f'<div class="row"><div class="k">{e(k)}</div><div class="v">{e(v)}</div></div>'
                  for k, v in rows)
        + (f'<div class="row" style="display:block"><div class="k">Asset mix '
           f'(calculated from listed holdings)</div><div class="mixbar">{mix_bar}</div>'
           f'<div class="legend">{legend}</div></div>' if f.asset_mix else "")
        + (f'<div class="row" style="display:block"><div class="k">Top holdings</div>'
           f'{holdings}</div>' if holdings else "")
        + f'<div style="margin-top:12px"><a class="src-pill" href="{e(f.url)}" target="_blank">'
          f'Source: Groww ↗</a><span class="muted">Updated {e(f.fetched_at)}</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_quick_questions(selected: str | None) -> None:
    if selected:
        items = [(label, q.format(fund=_short(selected))) for label, q in QUICK_QUESTIONS]
    else:
        items = [(q, q) for q in EXAMPLES]
        st.caption("Try an example:")
    cols = st.columns(len(items))
    for i, (col, (label, question)) in enumerate(zip(cols, items)):
        with col:
            st.button(label, key=f"quick-{i}-{label}", on_click=_ask_later, args=(question,),
                      use_container_width=True)


def render_answer(answer: Answer) -> None:
    payload = answer.payload
    if answer.pii_warning:
        st.warning(answer.pii_warning, icon="🔒")
    if answer.context_note:
        st.caption(f"↪ {answer.context_note}")
    if payload["refusal"]:
        st.info(payload["text"])
    else:
        st.markdown(payload["text"])
    parts = []
    if payload["source_url"]:
        parts.append(
            f'<a class="src-pill" href="{html.escape(payload["source_url"])}" '
            f'target="_blank">Source ↗</a>'
        )
    if payload["last_updated_from_sources"]:
        parts.append(
            f'<span class="muted">Last updated from sources: '
            f'{html.escape(payload["last_updated_from_sources"])}</span>'
        )
    if parts:
        st.markdown("".join(parts), unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🟢", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    # --- Left: scheme picker -------------------------------------------------
    options = [ALL] + [_short(s) for s in SCHEMES]
    with st.sidebar:
        st.markdown(f'<div class="brand"><span class="dot"></span>{APP_NAME}</div>',
                    unsafe_allow_html=True)
        st.caption("Pick a scheme to see its facts and ask about it.")
        choice = st.radio(
            "Schemes",
            options,
            key="scheme_choice",
            captions=["Ask about any fund"] + [TAGS[s] for s in SCHEMES],
        )
        st.divider()
        if st.button("Clear chat", use_container_width=True):
            st.session_state.history = []
        st.caption(
            f"Follow-up questions use the last {HISTORY_TURNS} exchanges of this chat as "
            "context (kept only in this browser session)."
        )
    selected = None if choice == ALL else f"{choice} Direct Growth"

    # --- Header ----------------------------------------------------------------
    st.markdown(
        f'<div class="topbar"><div class="brand"><span class="dot"></span>{APP_NAME}</div>'
        f'<div class="note-pill">{FACTS_ONLY_NOTE}</div></div>'
        f'<div class="welcome">{html.escape(WELCOME)}</div>',
        unsafe_allow_html=True,
    )
    stale = _staleness_note()
    if stale:
        st.warning(stale, icon="⏳")

    _warm_up()
    render_fund_cards(selected)
    if selected:
        render_fact_sheet(selected)
    render_quick_questions(selected)

    # --- Chat ------------------------------------------------------------------
    history: list[tuple[str, Answer]] = st.session_state.setdefault("history", [])
    for question, answer in history:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            render_answer(answer)

    placeholder = f"Ask about {_short(selected)}…" if selected else "Ask about an HDFC scheme…"
    typed = st.chat_input(placeholder)
    question = typed or st.session_state.pop("pending", None)
    if question:
        # Last HISTORY_TURNS exchanges (redacted questions + answer texts) as context
        # for follow-ups; session memory only.
        turns = [(q, a.payload["text"]) for q, a in history][-HISTORY_TURNS:]
        with st.spinner("Looking it up…"):
            answer = ask(question, turns, selected_scheme=selected)
        # Store and show only the redacted question; the raw input is dropped here.
        history.append((answer.redacted_query, answer))
        with st.chat_message("user"):
            st.write(answer.redacted_query)
        with st.chat_message("assistant"):
            render_answer(answer)

    st.markdown(f'<div class="footer">{DISCLAIMER}<br>{AFFILIATION}</div>',
                unsafe_allow_html=True)


main()
