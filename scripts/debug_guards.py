"""Phase 7 check: run the guard pipeline over labelled cases.

Run from the project root:  python scripts/debug_guards.py
Exits non-zero if any case gets the wrong outcome or if raw PII survives into
the decision. Only redacted text is ever printed. All PII below is fake.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.guards.pipeline import run_guards  # noqa: E402

# (message, expected outcome, expected PII types, raw PII strings that must not survive)
CASES: list[tuple[str, str, list[str], list[str]]] = [
    # Required by the implementation guide
    ("Should I buy HDFC Small Cap?", "advice", [], []),
    ("Which fund had better returns?", "performance", [], []),
    ("My PAN is ABCDE1234F, what is the exit load of HDFC Small Cap Fund?", "allow", ["PAN"], ["ABCDE1234F"]),
    # Advice
    ("Which is the best HDFC fund for me?", "advice", [], []),
    ("Is it a good time to invest in HDFC Flexi Cap?", "advice", [], []),
    ("Can you recommend a tax saving fund?", "advice", [], []),
    ("How much should I invest in ELSS every month?", "advice", [], []),
    ("Should I sell my Balanced Advantage units?", "advice", [], []),
    # Performance
    ("What are the 5 year returns of HDFC Large Cap Fund?", "performance", [], []),
    ("What is the CAGR of HDFC Small Cap Fund?", "performance", [], []),
    ("Did HDFC Flexi Cap beat its benchmark?", "performance", [], []),
    ("How has HDFC BAF performed since inception?", "performance", [], []),
    # Out of scope
    ("What is the exit load of SBI Bluechip Fund?", "out_of_scope", [], []),
    ("How do I apply for an HDFC Bank credit card?", "out_of_scope", [], []),
    ("What is the expense ratio of HDFC Mid Cap Fund?", "out_of_scope", [], []),
    ("What is the NAV of HDFC Large Cap Fund today?", "out_of_scope", [], []),
    ("What are the top holdings of HDFC Small Cap Fund?", "allow", [], []),
    ("what are the holdings in HDFC Balanced Advantage Fund", "allow", [], []),
    ("What is the current AUM of HDFC Large Cap Fund?", "allow", [], []),
    # Company names inside our schemes' holdings / custodian are not other AMCs
    ("Does HDFC Small Cap Fund hold Tata Steel?", "allow", [], []),
    ("How much ICICI Bank does HDFC Balanced Advantage Fund hold?", "allow", [], []),
    ("Is HDFC Bank the custodian of HDFC Large Cap Fund?", "allow", [], []),
    ("What is the exit load of Tata Small Cap Fund?", "out_of_scope", [], []),
    # Allowed factual / process questions (must not be over-blocked)
    ("What is the expense ratio of HDFC Large Cap Fund Direct Growth?", "allow", [], []),
    ("What is the lock-in for HDFC ELSS Tax Saver?", "allow", [], []),
    ("What is the minimum SIP amount for HDFC Balanced Advantage Fund?", "allow", [], []),
    ("What is the benchmark of HDFC Flexi Cap Fund?", "allow", [], []),
    ("What is the riskometer level of HDFC Small Cap Fund?", "allow", [], []),
    ("How do I download my capital gains statement for my tax return?", "allow", [], []),
    ("How are capital gains from ELSS taxed?", "allow", [], []),
    ("How do I get my HDFC Mutual Fund account statement?", "allow", [], []),
    ("What is a folio number?", "allow", [], []),
    # PII variants (fake values)
    ("Email the factsheet to test.user@example.com please", "allow", ["EMAIL"], ["test.user@example.com"]),
    ("My Aadhaar is 2345 6789 0123, how do I do KYC?", "allow", ["AADHAAR"], ["2345 6789 0123"]),
    ("Call me on +91 98765 43210 about SIP", "clarify", ["PHONE"], ["98765 43210"]),
    ("My OTP is 482913, why is it not working?", "allow", ["OTP"], ["482913"]),
    ("Folio no: 12345678/90 statement please", "allow", ["ACCOUNT"], ["12345678/90"]),
    ("Should I buy more? my PAN is abcde1234f", "advice", ["PAN"], ["abcde1234f"]),
    # About the assistant: fixed answer listing the covered schemes
    ("which all mutual funds you can access?", "about", [], []),
    ("Which funds do you cover?", "about", [], []),
    ("What schemes are available?", "about", [], []),
    ("List the funds", "about", [], []),
    ("What can you do?", "about", [], []),
    ("How many schemes do you support?", "about", [], []),
    # ...but these stay advice / facts
    ("Which fund should I invest in?", "advice", [], []),
    ("Which funds are best for me?", "advice", [], []),
    ("What is the fund size of HDFC Small Cap Fund?", "allow", [], []),
    ("Who is the fund manager of HDFC Small Cap Fund?", "allow", [], []),
    ("What is the NAV of HDFC Flexi Cap Fund Direct Growth?", "allow", [], []),
    # Fund-fact question with no fund named: ask which fund
    ("What is the expense ratio?", "clarify", [], []),
    ("What is the exit load?", "clarify", [], []),
    ("Who is the fund manager?", "clarify", [], []),
    ("What is the minimum SIP amount?", "clarify", [], []),
    ("What are the holdings?", "clarify", [], []),
    # Definitions are the same for every fund: no fund needed
    ("What is an expense ratio?", "allow", [], []),
    ("What does exit load mean?", "allow", [], []),
    # ...but general questions without a per-fund fact still go to retrieval
    ("How do I download my account statement?", "allow", [], []),
    ("Who is the registrar for these funds?", "allow", [], []),
]


def outcome(decision) -> str:
    if decision.allowed:
        return "allow"
    return decision.payload["refusal_reason"] or "about"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    failures = 0
    for message, expected, expected_pii, raw_pii in CASES:
        d = run_guards(message)
        got = outcome(d)
        visible = " ".join(
            str(x) for x in (d.query, d.pii_warning, *(d.payload or {}).values())
        )
        leaked = [p for p in raw_pii if p in visible]
        ok = got == expected and d.pii_types == expected_pii and not leaked
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {got:<12} {d.query}")
        if not ok:
            print(f"      expected {expected} pii={expected_pii}; got pii={d.pii_types}"
                  f"{' LEAKED RAW PII' if leaked else ''}")

    print("\nSample refusal payloads:")
    for message in ["Should I buy HDFC Small Cap?", "What is the CAGR of HDFC Small Cap Fund?",
                    "What is the exit load of SBI Bluechip Fund?"]:
        print(f"\n  {message}\n  {run_guards(message).payload}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
