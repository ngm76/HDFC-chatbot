"""Guard checks (Phases 7 and 15): run the guard pipeline over labelled cases.

Covers every PRD §6 example and §8 edge case, plus regressions. Run from the
project root:  python scripts/debug_guards.py
Exits non-zero if any case gets the wrong outcome, raw PII survives into the
decision, a non-answer response has no link, or a PII message reaches retrieval
or the model. Only redacted text is ever printed. All PII below is fake.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.guards.pipeline import run_guards  # noqa: E402

# Outcomes: allow | pii | advice | performance | out_of_scope | non_mf | about | clarify
# (message, expected outcome, expected PII types, raw PII strings that must not survive)
CASES: list[tuple[str, str, list[str], list[str]]] = [
    # --- PRD §6 examples, in precedence order -----------------------------------------
    ("My PAN is ABCDE1234F, show my ELSS lock-in date", "pii", ["PAN"], ["ABCDE1234F"]),
    ("OTP is 482913, why isn't my statement coming?", "pii", ["OTP"], ["482913"]),
    ("Should I buy HDFC Small Cap now?", "advice", [], []),
    ("Which is better for me, Flexi Cap or Large Cap?", "advice", [], []),
    ("What were HDFC Flexi Cap's 5-year returns?", "performance", [], []),
    ("Has Balanced Advantage beaten its benchmark?", "performance", [], []),
    ("What's the exit load on SBI Small Cap?", "out_of_scope", [], []),
    # PRD lists fund managers as unsupported; Addendum A1 keeps them answerable.
    ("Who manages HDFC Large Cap Fund?", "allow", [], []),
    ("What is the expense ratio of HDFC ELSS Tax Saver Direct Growth?", "allow", [], []),
    ("How do I download my capital gains statement from HDFC MF?", "allow", [], []),
    # Mixed message -> highest precedence (advice), refusal offers the fact
    ("What's the exit load and should I exit now?", "advice", [], []),
    # --- PRD §8 edge cases -------------------------------------------------------------
    ("Exit load on HDFC Top 100?", "allow", [], []),  # former name
    ("What is the lock-in of HDFC Taxsaver?", "allow", [], []),
    ("Expense ratio of HDFC Equity Fund?", "allow", [], []),
    ("What's the expense ratio of HDFC Flexi Cap?", "allow", [], []),  # Direct default
    ("What is the expense ratio of HDFC Flexi Cap regular plan?", "out_of_scope", [], []),
    ("What is the IDCW payout of HDFC Balanced Advantage Fund?", "out_of_scope", [], []),
    ("What is the difference between direct and regular plan?", "allow", [], []),
    ("Exit loads of Small Cap vs Flexi Cap?", "allow", [], []),  # factual comparison
    ("Which has lower risk, so should I pick it?", "advice", [], []),  # merit comparison
    ("HDFC Mid Cap Opportunities exit load?", "out_of_scope", [], []),  # not in corpus
    ("hdfc smallcap exit load", "allow", [], []),
    ("BAF minimum SIP", "allow", [], []),
    ("exit load of hdfc smal cap fund", "allow", [], []),  # misspelling, one match
    ("What is the expense ratio of HDFC cap fund?", "clarify", [], []),  # several -> chips
    ("How do I get my CAS?", "allow", [], []),
    # --- Advice (bias to advice when unsure) -----------------------------------------
    ("Which is the best HDFC fund for me?", "advice", [], []),
    ("Is it a good time to invest in HDFC Flexi Cap?", "advice", [], []),
    ("Can you recommend a tax saving fund?", "advice", [], []),
    ("How much should I invest in ELSS every month?", "advice", [], []),
    ("Should I sell my Balanced Advantage units?", "advice", [], []),
    ("Which fund should I invest in?", "advice", [], []),
    ("Which funds are best for me?", "advice", [], []),
    ("Is HDFC Small Cap good for my retirement?", "advice", [], []),
    # --- Performance -------------------------------------------------------------------
    ("Which fund had better returns?", "performance", [], []),
    ("What are the 5 year returns of HDFC Large Cap Fund?", "performance", [], []),
    ("What is the CAGR of HDFC Small Cap Fund?", "performance", [], []),
    ("How has HDFC BAF performed since inception?", "performance", [], []),
    ("What is the ranking of HDFC Small Cap Fund?", "performance", [], []),
    # --- Out of scope / non-MF -----------------------------------------------------------
    ("What is the exit load of SBI Bluechip Fund?", "out_of_scope", [], []),
    ("What is the exit load of Tata Small Cap Fund?", "out_of_scope", [], []),
    ("What is the expense ratio of HDFC Mid Cap Fund?", "out_of_scope", [], []),
    ("What is the NAV of HDFC Large Cap Fund today?", "out_of_scope", [], []),
    ("How do I apply for an HDFC Bank credit card?", "non_mf", [], []),
    ("What's the weather today?", "non_mf", [], []),
    ("Tell me a joke", "non_mf", [], []),
    ("What is the Tata Steel share price?", "non_mf", [], []),
    # --- Allowed facts (must not be over-blocked) ------------------------------------------
    ("What are the top holdings of HDFC Small Cap Fund?", "allow", [], []),
    ("what are the holdings in HDFC Balanced Advantage Fund", "allow", [], []),
    ("What is the current AUM of HDFC Large Cap Fund?", "allow", [], []),
    ("Does HDFC Small Cap Fund hold Tata Steel?", "allow", [], []),
    ("How much ICICI Bank does HDFC Balanced Advantage Fund hold?", "allow", [], []),
    ("Is HDFC Bank the custodian of HDFC Large Cap Fund?", "allow", [], []),
    ("What is the expense ratio of HDFC Large Cap Fund Direct Growth?", "allow", [], []),
    ("What is the lock-in for HDFC ELSS Tax Saver?", "allow", [], []),
    ("What is the minimum SIP amount for HDFC Balanced Advantage Fund?", "allow", [], []),
    ("What is the benchmark of HDFC Flexi Cap Fund?", "allow", [], []),
    ("What is the riskometer level of HDFC Small Cap Fund?", "allow", [], []),
    ("How do I download my capital gains statement for my tax return?", "allow", [], []),
    ("How are capital gains from ELSS taxed?", "allow", [], []),
    ("How do I get my HDFC Mutual Fund account statement?", "allow", [], []),
    ("What is a folio number?", "allow", [], []),
    ("What is the fund size of HDFC Small Cap Fund?", "allow", [], []),
    ("Who is the fund manager of HDFC Small Cap Fund?", "allow", [], []),
    ("What is the NAV of HDFC Flexi Cap Fund Direct Growth?", "allow", [], []),
    ("What is an expense ratio?", "allow", [], []),
    ("What does exit load mean?", "allow", [], []),
    ("How do I download my account statement?", "allow", [], []),
    ("Who is the registrar for these funds?", "allow", [], []),
    ("What are the top 10 holdings of HDFC Large Cap Fund?", "allow", [], []),
    # --- PII variants: always blocked (fake values; Aadhaar passes the Verhoeff check) ----
    ("My PAN is ABCDE1234F, what is the exit load of HDFC Small Cap Fund?", "pii", ["PAN"], ["ABCDE1234F"]),
    ("Email the factsheet to test.user@example.com please", "pii", ["EMAIL"], ["test.user@example.com"]),
    ("My Aadhaar is 2345 6789 0124, how do I do KYC?", "pii", ["AADHAAR"], ["2345 6789 0124"]),
    ("My Aadhaar is 2345 6789 0123, how do I do KYC?", "pii", ["ACCOUNT"], ["2345 6789 0123"]),
    ("Call me on +91 98765 43210 about SIP", "pii", ["PHONE"], ["98765 43210"]),
    ("My OTP is 482913, why is it not working?", "pii", ["OTP"], ["482913"]),
    ("Folio no: 12345678/90 statement please", "pii", ["ACCOUNT"], ["12345678/90"]),
    ("Should I buy more? my PAN is abcde1234f", "pii", ["PAN"], ["abcde1234f"]),
    # --- About the assistant / greetings ----------------------------------------------------
    ("which all mutual funds you can access?", "about", [], []),
    ("Which funds do you cover?", "about", [], []),
    ("What schemes are available?", "about", [], []),
    ("List the funds", "about", [], []),
    ("What can you do?", "about", [], []),
    ("How many schemes do you support?", "about", [], []),
    ("hi", "about", [], []),
    ("Thank you!", "about", [], []),
    # --- Fund-fact question with no fund named: ask which fund ----------------------------
    ("What is the expense ratio?", "clarify", [], []),
    ("What is the exit load?", "clarify", [], []),
    ("Who is the fund manager?", "clarify", [], []),
    ("What is the minimum SIP amount?", "clarify", [], []),
    ("What are the holdings?", "clarify", [], []),
]


def outcome(decision) -> str:
    if decision.allowed:
        return "allow"
    reason = decision.payload["refusal_reason"]
    return reason or "about"


def pii_never_reaches_retrieval() -> bool:
    """ask() with PII must return the block without calling retrieval or the model."""
    import src.rag.pipeline as rag

    def boom(*_a, **_k):
        raise AssertionError("PII message reached retrieval / generation")

    saved = rag.retrieve, rag.generate, rag.absence_answer
    rag.retrieve = rag.generate = rag.absence_answer = boom
    try:
        answer = rag.ask("My PAN is ABCDE1234F, what is the exit load of HDFC Small Cap Fund?")
    finally:
        rag.retrieve, rag.generate, rag.absence_answer = saved
    return (answer.payload["refusal_reason"] == "pii" and "ABCDE1234F" not in answer.redacted_query
            and bool(answer.payload["source_url"]))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    failures = 0
    for message, expected, expected_pii, raw_pii in CASES:
        d = run_guards(message)
        got = outcome(d)
        visible = " ".join(str(x) for x in (d.query, d.pii_warning, *(d.payload or {}).values()))
        leaked = [p for p in raw_pii if p in visible]
        no_link = not d.allowed and not ((d.payload or {}).get("source_url")
                                         and (d.payload or {}).get("source_label"))
        ok = got == expected and d.pii_types == expected_pii and not leaked and not no_link
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {got:<12} {d.query}")
        if not ok:
            print(f"      expected {expected} pii={expected_pii}; got pii={d.pii_types}"
                  f"{' LEAKED RAW PII' if leaked else ''}{' NO LINK' if no_link else ''}")

    ok = pii_never_reaches_retrieval()
    failures += not ok
    print(f"\n{'PASS' if ok else 'FAIL'}  PII message never reaches retrieval or the model")

    print("\nSample payloads:")
    for message in ["My PAN is ABCDE1234F, show my ELSS lock-in date",
                    "Which is better for me, Flexi Cap or Large Cap?",
                    "What's the exit load and should I exit now?",
                    "What were HDFC Flexi Cap's 5-year returns?",
                    "HDFC Mid Cap Opportunities exit load?",
                    "What is the expense ratio of HDFC Flexi Cap regular plan?",
                    "How do I apply for an HDFC Bank credit card?",
                    "What is the expense ratio of HDFC cap fund?"]:
        p = run_guards(message).payload
        print(f"\n  Q: {run_guards(message).query}\n  A: {p['text']}\n  link: {p['source_url']}"
              + (f"\n  chips: {p['chips']}" if p.get("chips") else ""))

    total = len(CASES) + 1
    print(f"\n{total - failures}/{total} passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
