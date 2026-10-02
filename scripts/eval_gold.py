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

# The corpus is the five Groww scheme pages named in docs/problemstatement.txt.
CORPUS_HOSTS = ("groww.in",)

# (category, question, regex the answer must match, expected fact in words)
# Expected facts are read off the Groww pages ingested 2026-09-27 (NAV as of 25 Sep '26).
GOLD: list[tuple[str, str, str, str]] = [
    ("Expense ratio", "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
     r"1\.03\s*%", "1.03%"),
    ("Expense ratio", "What is the expense ratio of HDFC Small Cap Fund Direct Growth?",
     r"0\.78\s*%", "0.78%"),
    # Not on Groww's ELSS page: expected to miss in a Groww-only corpus.
    ("Lock-in", "What is the lock-in for HDFC ELSS Tax Saver?",
     r"\b(3|three)[\s-]*years?\b", "3 years (not on the Groww page)"),
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
    # Groww pages only name the registrar (CAMS); there is no download guide.
    ("Statement", "How do I download my capital gains statement?",
     r"\b(CAMS|camsonline)\b", "via the registrar CAMS (camsonline.com)"),
    ("AUM", "What is the fund size of HDFC Small Cap Fund?",
     r"41,?890\.86", "₹41,890.86 Cr"),
    ("AUM", "What is the AUM of HDFC Large Cap Fund?",
     r"39,?933\.37", "₹39,933.37 Cr"),
    ("NAV", "What is the NAV of HDFC Flexi Cap Fund Direct Growth?",
     r"2,?214\.57", "₹2,214.57 (25 Sep '26)"),
    ("NAV", "What is the NAV of HDFC Small Cap Fund Direct Growth?",
     r"159\.82", "₹159.82 (25 Sep '26)"),
    # Both managers must appear: an answer naming only one is incomplete.
    ("Fund manager", "Who is the fund manager of HDFC Small Cap Fund?",
     r"Chirag\s+Setalvad.*Dhruv\s+Muchhal|Dhruv\s+Muchhal.*Chirag\s+Setalvad",
     "Chirag Setalvad + Dhruv Muchhal"),
    # Added after a user asked this and got "not in sources" (holdings were dropped).
    ("Holdings", "what are the holdings in HDFC Balanced Advantage Fund",
     r"ICICI\s+Bank", "ICICI Bank Ltd 5.32% (top holding)"),
    ("Definition", "What is an expense ratio?",
     r"fee\s+payable", "A fee payable to a mutual fund house for managing investments"),
    # Holdings analysis: sums of the listed weights, computed at ingest.
    ("Holdings analysis", "Can you give me the holdings analysis of HDFC Balanced Advantage Fund?",
     r"73\.26\s*%.*23\.76\s*%|23\.76\s*%.*73\.26\s*%", "equity 73.26%, debt 23.76% (calculated)"),
    ("Holdings analysis", "What is the equity vs debt ratio of HDFC Small Cap Fund?",
     r"89\.64\s*%", "equity 89.64%, debt 0.00% (calculated)"),
]


# Retrieval matrix: every fund × every field. Values from the Groww pages ingested
# 2026-09-27 (NAV as of 25 Sep 2026). field -> (question template, fact card field).
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
MATRIX_FACTS: dict[str, dict[str, str]] = {
    "HDFC Large Cap Fund": {
        "expense_ratio": r"1\.03%", "aum": r"39,933\.37", "nav": r"1,189\.08",
        "min_sip": r"₹100\b", "exit_load": r"1% if redeemed within 1 year",
        "riskometer": r"Very High", "benchmark": r"NIFTY 100",
        "fund_managers": r"Rahul Baijal.*Dhruv Muchhal|Dhruv Muchhal.*Rahul Baijal",
        "holdings": r"ICICI Bank", "holdings_count": r"\b50 holdings in total",
    },
    "HDFC Flexi Cap Fund": {
        "expense_ratio": r"0\.77%", "aum": r"1,13,606\.47", "nav": r"2,214\.57",
        "min_sip": r"₹100\b", "exit_load": r"1% if redeemed within 1 year",
        "riskometer": r"Very High", "benchmark": r"NIFTY 500",
        "fund_managers": r"Amit Ganatra.*Dhruv Muchhal|Dhruv Muchhal.*Amit Ganatra",
        "holdings": r"ICICI Bank", "holdings_count": r"\b86 holdings in total",
    },
    "HDFC ELSS Tax Saver Fund": {
        "expense_ratio": r"1\.21%", "aum": r"15,991\.78", "nav": r"1,447\.38",
        "min_sip": r"₹500\b", "exit_load": r"\bNil\b",
        "riskometer": r"Very High", "benchmark": r"NIFTY 500",
        "fund_managers": r"Amar Kalkundrikar.*Dhruv Muchhal|Dhruv Muchhal.*Amar Kalkundrikar",
        "holdings": r"ICICI Bank", "holdings_count": r"\b65 holdings in total",
    },
    "HDFC Small Cap Fund": {
        "expense_ratio": r"0\.78%", "aum": r"41,890\.86", "nav": r"159\.82",
        "min_sip": r"₹100\b", "exit_load": r"1% if redeemed within 1 year",
        "riskometer": r"Very High", "benchmark": r"BSE 250 SmallCap",
        "fund_managers": r"Chirag Setalvad.*Dhruv Muchhal|Dhruv Muchhal.*Chirag Setalvad",
        "holdings": r"Firstsource Solutions", "holdings_count": r"\b87 holdings in total",
    },
    "HDFC Balanced Advantage Fund": {
        "expense_ratio": r"0\.78%", "aum": r"1,07,295\.79", "nav": r"557\.73",
        "min_sip": r"₹100\b", "exit_load": r"15%",
        "riskometer": r"Very High", "benchmark": r"NIFTY 50 Hybrid Composite",
        "fund_managers": r"Anil Bamboli",
        "holdings": r"ICICI Bank", "holdings_count": r"\b326 holdings in total",
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
            fact = re.compile(facts[field], re.I | re.S)
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
        f"{totals['answered']}/{n} · Groww source cited {totals['cited']}/{n}"
    )


if __name__ == "__main__":
    main()
