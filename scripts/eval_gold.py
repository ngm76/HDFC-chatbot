"""Phase 10: gold-set evaluation (architecture §5, §12; PRD §10).

For each gold question: is the expected fact in the top-k retrieved chunks (and
at what rank), does the final answer contain it, and is the one citation an
official URL? Expected facts were read off the official pages in data/chroma.

Run from the project root:
    python scripts/eval_gold.py                   # full: retrieval + answers (uses the LLM)
    python scripts/eval_gold.py --retrieval-only  # retrieval ranks only, no API calls
    python scripts/eval_gold.py --matrix          # every fund × field, top-1 check, no API calls
Prints a Markdown table (paste into docs/eval_notes.md).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.generate import generator_mode  # noqa: E402
from src.rag.pipeline import ask  # noqa: E402
from src.rag.retrieve import TOP_K, retrieve  # noqa: E402

# The official corpus (PRD §4 allowlist): answers must cite one of these hosts.
CORPUS_HOSTS = ("hdfcfund.com", "sebi.gov.in", "amfiindia.com", "mutualfundssahihai.com")

# Figures that change with each data refresh (NAV daily; AUM, TER and holdings
# monthly). For these, a test expects the value on the *current* fact card
# (pattern "card:<field>") instead of a hard-coded number, so the evaluation stays
# valid after every refresh. It then checks routing and quoting, not the market.
CARD = "card"

# (category, question, regex the answer must match | "card:<field>", expected in words)
# Stable facts were read off the HDFC MF documents; volatile ones come from the current cards.
GOLD: list[tuple[str, str, str, str]] = [
    ("Expense ratio", "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
     "card:expense_ratio", "current TER"),
    ("Expense ratio", "What is the expense ratio of HDFC Small Cap Fund Direct Growth?",
     "card:expense_ratio", "current TER"),
    ("Lock-in", "What is the lock-in for HDFC ELSS Tax Saver?",
     r"\b(3|three)[\s-]*years?\b", "3 years (ELSS KIM and scheme page)"),
    ("Minimum SIP", "What is the minimum SIP amount for HDFC ELSS Tax Saver?",
     r"(₹|Rs\.?)\s*500\b", "₹500"),
    ("Minimum SIP", "What is the minimum SIP amount for HDFC Balanced Advantage Fund?",
     r"(₹|Rs\.?)\s*100\b", "₹100"),
    ("Exit load", "What is the exit load on HDFC Small Cap Fund Direct Growth?",
     r"\b1(\.00)?\s*%.*\b1\s*year", "1% if redeemed within 1 year"),
    ("Exit load", "What is the exit load of HDFC ELSS Tax Saver?",
     r"\bnil\b", "Nil"),
    ("Riskometer", "What is the riskometer level of HDFC Large Cap Fund?",
     r"very\s+high", "Very High"),
    ("Benchmark", "What is the benchmark of HDFC Small Cap Fund?",
     r"BSE\s*250\s*Small\s*Cap", "BSE 250 SmallCap TRI"),
    ("Benchmark", "What is the benchmark of HDFC Flexi Cap Fund?",
     r"NIFTY\s*500", "NIFTY 500 TRI"),
    # HDFC MF's capital-gains statement guide: request it from CAMS or KFintech.
    ("Statement", "How do I download my capital gains statement?",
     r"\b(CAMS|KFintech)\b", "request it from CAMS or KFintech (HDFC MF guide)"),
    ("AUM", "What is the fund size of HDFC Small Cap Fund?", "card:aum", "current AUM"),
    ("AUM", "What is the AUM of HDFC Large Cap Fund?", "card:aum", "current AUM"),
    ("NAV", "What is the NAV of HDFC Flexi Cap Fund Direct Growth?", "card:nav", "current NAV"),
    ("NAV", "What is the NAV of HDFC Small Cap Fund Direct Growth?", "card:nav", "current NAV"),
    # Both managers must appear: an answer naming only one is incomplete.
    ("Fund manager", "Who is the fund manager of HDFC Small Cap Fund?",
     r"Chirag\s+Setalvad.*Dhruv\s+Muchhal|Dhruv\s+Muchhal.*Chirag\s+Setalvad",
     "Chirag Setalvad + Dhruv Muchhal"),
    # Added after a user asked this and got "not in sources" (holdings were dropped).
    ("Holdings", "what are the holdings in HDFC Balanced Advantage Fund",
     r"ICICI\s+Bank", "ICICI Bank Ltd 5.32% (top holding)"),
    ("Definition", "What is an expense ratio?",
     r"costs\s+for\s+running\s+and\s+managing",
     "the costs for running and managing a scheme, as a % of its average NAV"),
    # Holdings analysis: the factsheet's stated portfolio subtotals.
    ("Holdings analysis", "Can you give me the holdings analysis of HDFC Balanced Advantage Fund?",
     "card:holdings_breakdown", "current equity % (factsheet subtotals)"),
    ("Holdings analysis", "What is the equity vs debt ratio of HDFC Small Cap Fund?",
     "card:holdings_breakdown", "current equity % (factsheet subtotals)"),
]


_NUMBER_RE = re.compile(r"[\d,]*\d(?:\.\d+)?%?")


def card_pattern(scheme: str, field: str) -> tuple[str, str]:
    """(regex for the first figure on the scheme's current `field` card, that figure).
    For holdings_breakdown the asset-class summary card is used (first figure =
    equity %)."""
    from src.rag.retrieve import _collection

    cards = _collection().get(where={"$and": [{"scheme": scheme}, {"field": field}]},
                              include=["documents"])["documents"]
    if field == "holdings_breakdown":
        cards = [c for c in cards if "asset allocation" in c] or cards
    if not cards:
        return r"(?!x)x", "no card"  # never matches
    if field == "holdings_breakdown":
        equity = re.search(r"\bequity (\d+\.\d+%)", cards[0])
        if equity:
            return re.escape(equity.group(1)), f"equity {equity.group(1)}"
    value = cards[0].split(": ", 2)[-1]
    number = _NUMBER_RE.search(value)
    if not number:
        return re.escape(value[:20]), value[:20]
    token = number.group(0)
    return re.escape(token).replace(r"\,", ",?"), token


def resolve_pattern(question: str, pattern: str) -> tuple[str, str | None]:
    """Turn "card:<field>" into a concrete regex for the question's fund."""
    if not pattern.startswith("card:"):
        return pattern, None
    from src.schemes import detect_schemes

    schemes = detect_schemes(question)
    return card_pattern(schemes[0], pattern.split(":", 1)[1]) if schemes else (r"(?!x)x", None)


# Retrieval matrix: every fund × every field. Stable values are read off the official
# HDFC MF scheme pages (Phase 14 corpus, 2026-10-02). field -> question template.
MATRIX_QUESTIONS: dict[str, str] = {
    "expense_ratio": "What is the expense ratio of {fund}?",
    "aum": "What is the fund size of {fund}?",
    "nav": "What is the NAV of {fund}?",
    "min_sip": "What is the minimum SIP amount for {fund}?",
    "exit_load": "What is the exit load of {fund}?",
    "riskometer": "What is the riskometer level of {fund}?",
    "benchmark": "What is the benchmark of {fund}?",
    "fund_managers": "Who are the fund managers of {fund}?",
    "holdings": "What are the holdings in {fund}?",
    "holdings_count": "How many holdings does {fund} have?",
}
# Volatile fields ("card") are checked against the fund's current card; the rest
# are stable facts read off the HDFC MF scheme pages.
_VOLATILE = {"expense_ratio": CARD, "aum": CARD, "nav": CARD, "holdings": CARD,
             "holdings_count": CARD}
MATRIX_FACTS: dict[str, dict[str, str]] = {
    "HDFC Large Cap Fund": {
        **_VOLATILE, "min_sip": r"₹100\b", "exit_load": r"1\.00% is payable if Units are redeemed.{0,30}within 1 year",
        "riskometer": r"Very High", "benchmark": r"NIFTY 100",
        "fund_managers": r"Rahul Baijal.*Dhruv Muchhal|Dhruv Muchhal.*Rahul Baijal",
    },
    "HDFC Flexi Cap Fund": {
        **_VOLATILE, "min_sip": r"₹100\b", "exit_load": r"1\.00% is payable if Units are redeemed.{0,30}within 1 year",
        "riskometer": r"Very High", "benchmark": r"NIFTY 500",
        "fund_managers": r"Amit (B )?Ganatra.*Dhruv Muchhal|Dhruv Muchhal.*Amit (B )?Ganatra",
    },
    "HDFC ELSS Tax Saver Fund": {
        **_VOLATILE, "min_sip": r"₹500\b", "exit_load": r"\bNil\b",
        "riskometer": r"Very High", "benchmark": r"NIFTY 500",
        "fund_managers": r"Amar Kalkundrikar.*Dhruv Muchhal|Dhruv Muchhal.*Amar Kalkundrikar",
    },
    "HDFC Small Cap Fund": {
        **_VOLATILE, "min_sip": r"₹100\b", "exit_load": r"1\.00% is payable if Units are redeemed.{0,30}within 1 year",
        "riskometer": r"Very High", "benchmark": r"BSE 250 SmallCap",
        "fund_managers": r"Chirag Setalvad.*Dhruv Muchhal|Dhruv Muchhal.*Chirag Setalvad",
    },
    "HDFC Balanced Advantage Fund": {
        **_VOLATILE, "min_sip": r"₹100\b", "exit_load": r"15%",
        "riskometer": r"Very High", "benchmark": r"NIFTY 50 Hybrid Composite",
        "fund_managers": r"Anil Bamboli",
    },
}


# Matrix field -> fact-card field that should answer it (when they differ).
CARD_FIELD = {"holdings_count": "holdings"}


def run_matrix() -> None:
    """Top-1 must be the right fund's card for the asked field and contain the value."""
    print(f"retrieval matrix  k={TOP_K}\n")
    fields = list(MATRIX_QUESTIONS)
    print("| Fund | " + " | ".join(fields) + " |")
    print("|---|" + "---|" * len(fields))
    top1 = found = total = 0
    misses: list[str] = []
    for fund, facts in MATRIX_FACTS.items():
        cells = []
        for field in fields:
            question = MATRIX_QUESTIONS[field].format(fund=fund)
            chunks = retrieve(question)
            pattern = facts[field]
            if pattern == CARD:
                pattern, _ = card_pattern(f"{fund} Direct Growth", CARD_FIELD.get(field, field))
            fact = re.compile(pattern, re.I | re.S)
            rank = next((r for r, c in enumerate(chunks, 1) if fact.search(c["text"])), None)
            first = chunks[0] if chunks else None
            expected_field = CARD_FIELD.get(field, field)
            right_card = bool(first and first["field"] in (expected_field, "overview")
                              and first["scheme"].startswith(fund) and fact.search(first["text"]))
            total += 1
            found += rank is not None
            top1 += right_card
            cells.append("✅" if right_card else (f"#{rank}" if rank else "❌"))
            if not right_card:
                got = f"{first['field']} / {first['scheme']}" if first else "nothing"
                misses.append(f"  {question}  -> top-1: {got}; fact rank: {rank}")
        print(f"| {fund} | " + " | ".join(cells) + " |")
    print(f"\n**Top-1 correct card:** {top1}/{total} · **fact anywhere in top {TOP_K}:** {found}/{total}")
    if misses:
        print("\nNot top-1:\n" + "\n".join(misses))


def is_corpus_source(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in CORPUS_HOSTS)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--matrix" in sys.argv:  # every fund × field, retrieval only (no API calls)
        run_matrix()
        return
    retrieval_only = "--retrieval-only" in sys.argv  # no generator calls (saves API quota)
    if retrieval_only:
        print(f"retrieval only  k={TOP_K}\n")
        print("| # | Category | Question | Expected | Fact in top-k (rank) |")
        print("|---|---|---|---|---|")
        found = 0
        for i, (category, question, pattern, expected) in enumerate(GOLD, 1):
            pattern, current = resolve_pattern(question, pattern)
            expected = f"{expected}: {current}" if current else expected
            fact = re.compile(pattern, re.I | re.S)
            chunks = retrieve(question)
            rank = next((r for r, c in enumerate(chunks, 1) if fact.search(" ".join(c["text"].split()))), None)
            found += rank is not None
            print(f"| {i} | {category} | {question} | {expected} | {'✅ #' + str(rank) if rank else '❌'} |")
        print(f"\n**Totals:** fact retrieved {found}/{len(GOLD)}")
        return

    print(f"generator: {generator_mode()}  k={TOP_K}\n")
    print("| # | Category | Question | Expected | Fact in top-k (rank) | Answer has fact | Source cited | Cited page |")
    print("|---|---|---|---|---|---|---|---|")
    totals = {"retrieved": 0, "answered": 0, "cited": 0}
    for i, (category, question, pattern, expected) in enumerate(GOLD, 1):
        pattern, current = resolve_pattern(question, pattern)
        expected = f"{expected}: {current}" if current else expected
        fact = re.compile(pattern, re.I | re.S)
        chunks = retrieve(question)
        rank = next((r for r, c in enumerate(chunks, 1) if fact.search(" ".join(c["text"].split()))), None)
        payload = ask(question).payload
        answered = not payload["refusal"] and bool(fact.search(payload["text"]))
        cited = not payload["refusal"] and is_corpus_source(payload["source_url"])
        totals["retrieved"] += rank is not None
        totals["answered"] += answered
        totals["cited"] += cited
        page = (payload["source_url"] or "").rsplit("/", 1)[-1].replace("%20", " ")[:48]
        print(
            f"| {i} | {category} | {question} | {expected} | "
            f"{'✅ #' + str(rank) if rank else '❌'} | {'✅' if answered else '❌'} | "
            f"{'✅' if cited else '❌'} | {page} |"
        )
    n = len(GOLD)
    print(
        f"\n**Totals:** fact retrieved {totals['retrieved']}/{n} · answer contains fact "
        f"{totals['answered']}/{n} · official source cited {totals['cited']}/{n}"
    )


if __name__ == "__main__":
    main()
