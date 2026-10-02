"""Scope guard (PRD FR-14, FR-15, §6 precedence 4): questions the corpus cannot answer.

Reasons, each with its own short message and one link:
- other_amc: another fund house's scheme -> AMFI investor page
- other_scheme: an HDFC scheme outside the five -> HDFC MF schemes listing (§8)
- plan: Regular Plan or IDCW details (answers are Direct Plan - Growth, FR-3) ->
  the scheme's page
- live_data: today's / live NAV or prices -> the factsheet (latest stated NAV)
- non_mf: not about mutual funds (loans, cards, stocks, general chat) -> one-line
  redirect to Groww help, no third-party link (FR-15)

Generic mutual-fund process questions with no scheme named (statements, KYC,
definitions) stay in scope. Extra fields kept by Addendum A1 (NAV, AUM, fund
managers, holdings) are answerable, not out of scope.
"""

from __future__ import annotations

import re

from src.guards.common import (
    AnswerPayload,
    educational_source,
    factsheet_source,
    help_source,
    make_payload,
    scheme_page_source,
    schemes_listing_source,
)
from src.schemes import SCHEMES, ambiguous_schemes, detect_schemes, fuzzy_schemes, short_name

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
    r"share\s+price|stock\s+price|stock\s+market\s+tips?|crypto\w*|bitcoin|gold\s+rate|"
    r"weather|joke|recipe|movie|cricket)\b",
    re.I,
)

# Words that make a message about mutual funds. A message with none of them (and no
# scheme name) is not a mutual-fund question (FR-15).
_MF_VOCAB_RE = re.compile(
    r"\b(mutual|funds?|schemes?|sip|swp|stp|nav|aum|expense|ter|exit|entry|load|lock[\s-]?in|"
    r"riskometer|risk|benchmark|index|statements?|cas|elss|kyc|folio|redeem\w*|redemption|"
    r"units?|amc|hdfc|invest\w*|portfolio|holdings?|holds?|manager|managers|direct|regular|"
    r"idcw|dividend|growth|lump\s*sum|tax\w*|capital\s+gains?|stamp\s+duty|registrar|rta|"
    r"cams|kfin\w*|sebi|amfi|equity|debt|hybrid|allotment|nominee|nomination|switch)\b",
    re.I,
)

# Another fund house's *scheme*: its name followed by a fund name within a few
# words ("Tata Small Cap Fund", "Aditya Birla Sun Life Flexi Cap Fund"). A company
# name without "fund" ("Tata Steel", "ICICI Bank") is a holding, not a scheme.
# A fund-house name followed by a scheme category is that house's scheme even
# without "fund" ("SBI Small Cap", "Axis ELSS").
_CATEGORY = (r"(?:small|large|mid|flexi|multi)[\s-]?cap|elss|tax\s?saver|bluechip|"
             r"balanced\s+advantage|focused|value|index|liquid|gilt|hybrid")
_OTHER_AMC_SCHEME_RE = re.compile(
    rf"(?:{_OTHER_AMC_RE.pattern})\s+(?:[\w&'-]+\s+){{0,4}}(?:fund|scheme|etf|fof)\b|"
    rf"(?:{_OTHER_AMC_RE.pattern})\s+(?:[\w&'-]+\s+){{0,1}}(?:{_CATEGORY})\b",
    re.I,
)

# Live / real-time figures. Holdings are NOT here: they are in the factsheet.
_LIVE_DATA_RE = re.compile(
    r"\b(today'?s?|live|right\s+now|yesterday'?s?)\s+(nav|price|aum)\b|"
    r"\bnav\s+(today|now|right\s+now)\b|"
    r"\bnav\b.*\b(today|now|currently|this\s+(morning|week))\b",
    re.I,
)

# "HDFC <something> Fund/ETF/FOF" naming a scheme outside the five. The AMC's own
# name ("HDFC Mutual Fund", "HDFC MF") is not a scheme.
_HDFC_SCHEME_RE = re.compile(
    r"\bhdfc\s+(?!mutual\s+fund\b|mf\b|amc\b)[a-z0-9&\-\s]{2,60}?\b(fund|etf|fof|plan)\b|"
    # HDFC categories outside the five, even without "fund" ("HDFC Mid Cap Opportunities")
    r"\bhdfc\s+(mid[\s-]?cap|multi[\s-]?cap|large\s+(and|&)\s+mid|focused|value|nifty|sensex|"
    r"index|gilt|liquid|overnight|money\s+market|arbitrage|hybrid|children|retirement|banking|"
    r"infra\w*|pharma\w*|defence|manufacturing|business\s+cycle|dividend\s+yield|gold|silver|"
    r"corporate\s+bond|short\s+term|credit\s+risk|equity\s+savings|multi[\s-]?asset|"
    r"transportation|technology|housing|mnc|psu|bse|etf|fof)\b",
    re.I,
)

# Regular Plan / IDCW questions (FR-14). Not "direct vs regular" explainers: the
# Mutual Funds Sahi Hai page on the difference is in the corpus.
_PLAN_RE = re.compile(
    r"\bregular\s+(plan|option|growth)\b|\bidcw\b|\bdividend\s+(option|plan|payout|reinvest\w*)\b",
    re.I,
)
_PLAN_EXPLAINER_RE = re.compile(
    r"\bdirect\s+(vs\.?|versus|and|or)\s+regular\b|\bregular\s+(vs\.?|versus|and|or)\s+direct\b|"
    r"\bdifference\b|\bwhat\s+(is|are)\s+(an?\s+)?(idcw|regular\s+plan)",
    re.I,
)

_SCHEME_LIST = ", ".join(short_name(s) for s in SCHEMES)
COVERAGE = f"I cover five HDFC Mutual Fund schemes (Direct Plan - Growth): {_SCHEME_LIST}."

TEXTS = {
    "other_amc": f"{COVERAGE} I can't answer questions about other fund houses' schemes. "
                 "AMFI's investor page has information for investors on all mutual funds.",
    "other_scheme": f"{COVERAGE} For other HDFC Mutual Fund schemes, please see the HDFC "
                    "Mutual Fund schemes listing.",
    "plan": "I answer for the Direct Plan - Growth option of five HDFC Mutual Fund schemes, "
            "so I can't give Regular Plan or IDCW details. The linked official page shows "
            "the scheme's details for every plan and option.",
    "live_data": "I don't have live data such as today's NAV. I can share the latest NAV "
                 "stated in the HDFC Mutual Fund monthly factsheet if you ask for it.",
    "non_mf": "I can only help with facts about HDFC Mutual Fund schemes; for anything else, "
              "please visit Groww Help.",
}


def is_non_mf(text: str) -> bool:
    """Not a mutual-fund question (FR-15)."""
    if detect_schemes(text) or fuzzy_schemes(text):
        return False
    if _NON_MF_RE.search(text):
        return True
    return not _MF_VOCAB_RE.search(text)


def out_of_scope_reason(text: str, context_scheme: str | None = None) -> str | None:
    """Short reason code if the question is outside the corpus, else None.

    When the question names one of the five schemes, names like Tata, ICICI,
    Kotak, SBI, HDFC Bank or LIC are companies in its holdings or its custodian
    ("Does HDFC Small Cap Fund hold Tata Steel?"), not other fund houses or
    products, so those checks are skipped.
    """
    if _OTHER_AMC_SCHEME_RE.search(text):  # "Tata Small Cap Fund", "SBI Bluechip Fund"
        return "other_amc"
    names_our_scheme = bool(detect_schemes(text)) or context_scheme is not None
    if _OTHER_AMC_RE.search(text) and not names_our_scheme and not _NON_MF_RE.search(text):
        return "other_amc"
    if not names_our_scheme and is_non_mf(text):
        return "non_mf"
    if _PLAN_RE.search(text) and not _PLAN_EXPLAINER_RE.search(text):
        return "plan"
    if _LIVE_DATA_RE.search(text):
        return "live_data"
    if (_HDFC_SCHEME_RE.search(text) and not detect_schemes(text) and not fuzzy_schemes(text)
            and not ambiguous_schemes(text)):  # "HDFC cap fund" -> clarify chips instead
        return "other_scheme"
    return None


def refusal(reason: str, text: str = "", context_scheme: str | None = None) -> AnswerPayload:
    schemes = detect_schemes(text) or ([context_scheme] if context_scheme else [])
    scheme = schemes[0] if len(schemes) == 1 else None
    if reason == "non_mf":
        source = help_source("non_mf_redirect")
    elif reason == "other_scheme":
        source = schemes_listing_source()
    elif reason == "plan":
        source = (scheme_page_source(scheme) if scheme else None) or schemes_listing_source()
    elif reason == "live_data":
        source = factsheet_source(scheme)
    else:
        source = educational_source()
    return make_payload(TEXTS.get(reason, TEXTS["other_amc"]), source,
                        refusal=True, refusal_reason=reason if reason == "non_mf" else "out_of_scope")
