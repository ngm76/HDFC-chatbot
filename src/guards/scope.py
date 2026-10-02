"""Scope guard: questions the corpus cannot answer (architecture §8 "out of corpus").

Other AMCs, other HDFC schemes, non-mutual-fund HDFC products (HDFC Bank,
HDFC Life, loans, cards), and live data (today's NAV, live prices).
Generic process questions with no scheme named (statements, KYC) stay in scope.
"""

from __future__ import annotations

import re

from src.guards.common import AnswerPayload, educational_source, make_payload
from src.schemes import SCHEMES, detect_schemes

_OTHER_AMC_RE = re.compile(
    r"\b(sbi|icici(\s+prudential)?|axis|nippon(\s+india)?|kotak|aditya\s+birla|absl|"
    r"uti|mirae(\s+asset)?|parag\s+parikh|ppfas|tata|dsp|franklin(\s+templeton)?|"
    r"motilal(\s+oswal)?|quant|canara\s+robeco|edelweiss|bandhan|invesco|hsbc|pgim|"
    r"sundaram|lic\s+mf|baroda\s+bnp|mahindra\s+manulife|navi|whiteoak|bajaj\s+finserv|"
    r"groww\s+(mutual\s+fund|mf)|zerodha|samco|jm\s+financial|360\s*one|"
    r"trust\s*mf|helios|old\s+bridge|shriram)\b",
    re.I,
)

_NON_MF_RE = re.compile(
    r"\b(hdfc\s+bank|hdfc\s+life|hdfc\s+ergo|hdfc\s+securities|hdfc\s+credila|"
    r"credit\s+card|debit\s+card|home\s+loan|personal\s+loan|car\s+loan|loan|"
    r"fixed\s+deposit|\bfd\b|savings\s+account|insurance|net\s*banking|"
    r"share\s+price|stock\s+price)\b",
    re.I,
)

# Another fund house's *scheme*: its name followed by a fund name within a few
# words ("Tata Small Cap Fund", "Aditya Birla Sun Life Flexi Cap Fund"). A company
# name without "fund" ("Tata Steel", "ICICI Bank") is a holding, not a scheme.
_OTHER_AMC_SCHEME_RE = re.compile(
    rf"(?:{_OTHER_AMC_RE.pattern})\s+(?:[\w&'-]+\s+){{0,4}}(?:fund|scheme|etf|fof)\b",
    re.I,
)

# Live / real-time figures. Holdings are NOT here: the fund's holdings as listed on
# its Groww page are in the corpus and answered from the last ingest.
_LIVE_DATA_RE = re.compile(
    r"\b(today'?s?|live|right\s+now|yesterday'?s?)\s+(nav|price|aum)\b|"
    r"\bnav\s+(today|now|right\s+now)\b|"
    r"\bnav\b.*\b(today|now|currently|this\s+(morning|week))\b",
    re.I,
)

# "HDFC <something> Fund/ETF/FOF" naming a scheme outside the five. The AMC's own
# name ("HDFC Mutual Fund", "HDFC MF") is not a scheme.
_HDFC_SCHEME_RE = re.compile(
    r"\bhdfc\s+(?!mutual\s+fund\b|mf\b|amc\b)[a-z0-9&\-\s]{2,60}?\b(fund|etf|fof|plan)\b",
    re.I,
)

_SCHEME_LIST = ", ".join(s.removesuffix(" Direct Growth") for s in SCHEMES)

REFUSAL_TEXT = (
    "This prototype only answers factual questions about five HDFC Mutual Fund "
    f"schemes ({_SCHEME_LIST}) using their public scheme pages. It can't answer "
    "questions about other funds, other companies' products or live data such as "
    "today's NAV."
)


def out_of_scope_reason(text: str, context_scheme: str | None = None) -> str | None:
    """Short reason code if the question is outside the corpus, else None.

    When the question names one of the five schemes, names like Tata, ICICI,
    Kotak, SBI, HDFC Bank or LIC are companies in its holdings or its custodian
    ("Does HDFC Small Cap Fund hold Tata Steel?"), not other fund houses or
    products, so those two checks are skipped.
    """
    if _OTHER_AMC_SCHEME_RE.search(text):  # "Tata Small Cap Fund", "SBI Bluechip Fund"
        return "other_amc"
    names_our_scheme = bool(detect_schemes(text)) or context_scheme is not None
    if _NON_MF_RE.search(text) and not names_our_scheme:
        return "non_mf_product"
    if _OTHER_AMC_RE.search(text) and not names_our_scheme:
        return "other_amc"
    if _LIVE_DATA_RE.search(text):
        return "live_data"
    if _HDFC_SCHEME_RE.search(text) and not detect_schemes(text):
        return "other_scheme"
    return None


def refusal() -> AnswerPayload:
    return make_payload(
        REFUSAL_TEXT, educational_source(), refusal=True, refusal_reason="out_of_scope"
    )
