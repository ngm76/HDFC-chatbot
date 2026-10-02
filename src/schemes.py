"""The five in-scope schemes and how queries name them (PRD FR-2, §8).

Shared by retrieval (scheme filter) and guards (performance links, scope checks),
so both agree on what "names a scheme" means. Keys match the `scheme` column in
data/sources.csv and the Chroma metadata.

Three levels of matching:
- detect_schemes: exact patterns, including short forms and former names
  ("HDFC Top 100", "HDFC Equity Fund", "HDFC Taxsaver", "BAF");
- fuzzy_schemes: misspellings ("hdfc smal cap", "flexy cap") matched with high
  confidence when nothing matched exactly;
- ambiguous_schemes: names that fit several schemes ("HDFC cap fund"), which the
  clarify guard turns into chips.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

SHARED_SCHEME = "ALL"

SCHEME_PATTERNS: dict[str, re.Pattern[str]] = {
    "HDFC Large Cap Fund Direct Growth": re.compile(
        r"\blarge[\s-]?cap\b(?!\s*(and|&)\s*mid)|\btop[\s-]?100\b", re.I
    ),
    "HDFC Flexi Cap Fund Direct Growth": re.compile(
        r"\bflexi[\s-]?cap\b|\bhdfc\s+equity\s+fund\b", re.I
    ),
    "HDFC ELSS Tax Saver Fund Direct Growth": re.compile(
        r"\belss\b|\btax[\s-]?saver\b|\btaxsaver\b", re.I
    ),
    "HDFC Small Cap Fund Direct Growth": re.compile(r"\bsmall[\s-]?cap\b", re.I),
    "HDFC Balanced Advantage Fund Direct Growth": re.compile(
        r"\bbalanced\s+advantage\b|\bbaf\b", re.I
    ),
}

SCHEMES = tuple(SCHEME_PATTERNS)

# Category of each scheme, as listed in docs/problemstatement.txt.
SCHEME_CATEGORIES: dict[str, str] = {
    "HDFC Large Cap Fund Direct Growth": "large cap",
    "HDFC Flexi Cap Fund Direct Growth": "flexi cap",
    "HDFC ELSS Tax Saver Fund Direct Growth": "ELSS",
    "HDFC Small Cap Fund Direct Growth": "small cap",
    "HDFC Balanced Advantage Fund Direct Growth": "hybrid",
}

# Former names (PRD §8 "Scheme renames"): answered under the current name, with the
# former name mentioned once. Sources: the Large Cap KIM ("Formerly known as HDFC
# Top 100 Fund"), data/schemes.md (HDFC Equity Fund renamed 29 Jan 2021, HDFC
# TaxSaver renamed to HDFC ELSS Tax Saver).
FORMER_NAMES: dict[str, tuple[re.Pattern[str], str]] = {
    "HDFC Large Cap Fund Direct Growth": (re.compile(r"\bhdfc\s+top[\s-]?100(\s+fund)?\b", re.I),
                                          "HDFC Top 100 Fund"),
    "HDFC Flexi Cap Fund Direct Growth": (re.compile(r"\bhdfc\s+equity\s+fund\b", re.I),
                                          "HDFC Equity Fund"),
    "HDFC ELSS Tax Saver Fund Direct Growth": (re.compile(r"\bhdfc\s+tax\s?saver\b(?!\s+fund)", re.I),
                                               "HDFC TaxSaver"),
}

# Words that name each scheme, for fuzzy matching of misspellings. Short forms
# ("baf", "elss") and names with numbers ("top 100", too close to "top 10") are
# matched only exactly.
_ALIASES: dict[str, tuple[str, ...]] = {
    "HDFC Large Cap Fund Direct Growth": ("large cap", "largecap"),
    "HDFC Flexi Cap Fund Direct Growth": ("flexi cap", "flexicap"),
    "HDFC ELSS Tax Saver Fund Direct Growth": ("tax saver", "taxsaver"),
    "HDFC Small Cap Fund Direct Growth": ("small cap", "smallcap"),
    "HDFC Balanced Advantage Fund Direct Growth": ("balanced advantage", "balance advantage"),
}
FUZZY_MIN_RATIO = 0.85

# "HDFC cap fund" / "the cap fund": fits Large, Flexi and Small Cap.
_AMBIGUOUS_CAP_RE = re.compile(r"\b(hdfc|the)\s+cap\s+fund\b", re.I)
_CAP_SCHEMES = ("HDFC Large Cap Fund Direct Growth", "HDFC Flexi Cap Fund Direct Growth",
                "HDFC Small Cap Fund Direct Growth")


def short_name(scheme: str) -> str:
    return scheme.removesuffix(" Direct Growth")


def detect_schemes(text: str) -> list[str]:
    """Schemes (internal names) the text mentions, in SCHEME_PATTERNS order."""
    return [name for name, pattern in SCHEME_PATTERNS.items() if pattern.search(text)]


def former_name_used(text: str) -> tuple[str, str] | None:
    """(former name, current scheme) when the text uses a scheme's former name."""
    for scheme, (pattern, former) in FORMER_NAMES.items():
        if pattern.search(text):
            return former, scheme
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def fuzzy_schemes(text: str) -> list[str]:
    """Schemes whose alias closely matches a run of words in the text (misspellings).
    Only used when detect_schemes finds nothing."""
    words = _words(text)
    found: list[str] = []
    for scheme, aliases in _ALIASES.items():
        for alias in aliases:
            n = len(alias.split())
            for i in range(len(words) - n + 1):
                window = " ".join(words[i : i + n])
                for candidate in (window, window.replace(" ", "")):
                    if SequenceMatcher(None, candidate, alias).ratio() >= FUZZY_MIN_RATIO:
                        if scheme not in found:
                            found.append(scheme)
    return found


def ambiguous_schemes(text: str) -> list[str]:
    """Candidate schemes when the name fits more than one (for clarify chips)."""
    if detect_schemes(text):
        return []
    fuzzy = fuzzy_schemes(text)
    if len(fuzzy) > 1:
        return fuzzy
    if not fuzzy and _AMBIGUOUS_CAP_RE.search(text):
        return list(_CAP_SCHEMES)
    return []
