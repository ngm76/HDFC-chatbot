"""The mutual fund schemes this assistant covers: the single place to change them.

To add, remove or rename a scheme, edit SCHEME_REGISTRY below. Everything else is
derived from it: scheme detection (exact, former names, misspellings), the clarify
chips, the about / out-of-scope / non-mutual-fund replies, the UI's "Schemes
covered" row and welcome count, the factsheet and TER card builders, and the KIM
new-edition check. The registry cannot download pages, so each scheme also needs
its `scheme_page` and `kim` rows in data/sources.csv; `scripts/ingest.py --strict`
fails if the two disagree (see README "How to change the list of schemes").

Matching levels:
- detect_schemes: exact patterns, including short forms and former names;
- fuzzy_schemes: misspellings ("hdfc smal cap") when nothing matched exactly;
- ambiguous_schemes: names that fit several schemes ("HDFC cap fund") → chips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

SHARED_SCHEME = "ALL"
PLAN = "Direct Plan - Growth"


@dataclass(frozen=True)
class Scheme:
    name: str  # official scheme name, as users and answers show it
    category: str  # shown in the UI and the about reply
    # Regexes that name the scheme in a question (short forms, former names).
    patterns: tuple[str, ...]
    # Former names: (regex, display name). Answers add "X was formerly called Y".
    former_names: tuple[tuple[str, str], ...] = ()
    # Spellings matched with tolerance for typos (ratio >= FUZZY_MIN_RATIO). Keep
    # very short forms ("baf") and names with numbers out: they match only exactly.
    fuzzy: tuple[str, ...] = ()
    # How the scheme is named inside the monthly factsheet and the TER workbook.
    doc_name: str = ""
    # How the scheme is named in KIM file names ("KIM - <kim_name> dated …").
    kim_name: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Internal scheme value used in data/sources.csv and the Chroma metadata."""
        return f"{self.name} Direct Growth"


# ------------------------------------------------------------------------------------
# SINGLE POINT OF CONTACT: the schemes the assistant covers.
# ------------------------------------------------------------------------------------
SCHEME_REGISTRY: tuple[Scheme, ...] = (
    Scheme(
        name="HDFC Large Cap Fund", category="large cap",
        patterns=(r"\blarge[\s-]?cap\b(?!\s*(and|&)\s*mid)", r"\btop[\s-]?100\b"),
        # Source: the Large Cap KIM ("Formerly known as HDFC Top 100 Fund").
        former_names=((r"\bhdfc\s+top[\s-]?100(\s+fund)?\b", "HDFC Top 100 Fund"),),
        fuzzy=("large cap", "largecap"),
        doc_name="HDFC Large Cap Fund", kim_name="HDFC Large Cap Fund",
    ),
    Scheme(
        name="HDFC Flexi Cap Fund", category="flexi cap",
        patterns=(r"\bflexi[\s-]?cap\b", r"\bhdfc\s+equity\s+fund\b"),
        # Renamed from HDFC Equity Fund on 29 Jan 2021 (data/schemes.md).
        former_names=((r"\bhdfc\s+equity\s+fund\b", "HDFC Equity Fund"),),
        fuzzy=("flexi cap", "flexicap"),
        doc_name="HDFC Flexi Cap Fund", kim_name="HDFC Flexi Cap Fund",
    ),
    Scheme(
        name="HDFC ELSS Tax Saver Fund", category="ELSS",
        patterns=(r"\belss\b", r"\btax[\s-]?saver\b", r"\btaxsaver\b"),
        former_names=((r"\bhdfc\s+tax\s?saver\b(?!\s+fund)", "HDFC TaxSaver"),),
        fuzzy=("tax saver", "taxsaver"),
        doc_name="HDFC ELSS - Tax Saver Fund", kim_name="HDFC ELSS Tax Saver",
    ),
    Scheme(
        name="HDFC Small Cap Fund", category="small cap",
        patterns=(r"\bsmall[\s-]?cap\b",),
        fuzzy=("small cap", "smallcap"),
        doc_name="HDFC Small Cap Fund", kim_name="HDFC Small Cap Fund",
    ),
    Scheme(
        name="HDFC Balanced Advantage Fund", category="hybrid",
        patterns=(r"\bbalanced\s+advantage\b", r"\bbaf\b"),
        fuzzy=("balanced advantage", "balance advantage"),
        doc_name="HDFC Balanced Advantage Fund", kim_name="HDFC Balanced Advantage Fund",
    ),
)
# ------------------------------------------------------------------------------------

# Derived views (do not edit; change SCHEME_REGISTRY instead).
BY_KEY: dict[str, Scheme] = {s.key: s for s in SCHEME_REGISTRY}
SCHEMES: tuple[str, ...] = tuple(BY_KEY)
SCHEME_PATTERNS: dict[str, re.Pattern[str]] = {
    s.key: re.compile("|".join(s.patterns), re.I) for s in SCHEME_REGISTRY
}
SCHEME_CATEGORIES: dict[str, str] = {s.key: s.category for s in SCHEME_REGISTRY}
FORMER_NAMES: dict[str, list[tuple[re.Pattern[str], str]]] = {
    s.key: [(re.compile(rx, re.I), shown) for rx, shown in s.former_names]
    for s in SCHEME_REGISTRY if s.former_names
}
DOC_NAMES: dict[str, str] = {s.key: s.doc_name or s.name for s in SCHEME_REGISTRY}
KIM_NAME_PATTERNS: dict[str, str] = {
    s.key: rf"KIM - {re.escape(s.kim_name or s.name)} dated" for s in SCHEME_REGISTRY
}
_ALIASES: dict[str, tuple[str, ...]] = {s.key: s.fuzzy for s in SCHEME_REGISTRY}
FUZZY_MIN_RATIO = 0.85

# "HDFC cap fund" / "the cap fund": fits every registered "… Cap Fund".
_AMBIGUOUS_CAP_RE = re.compile(r"\b(hdfc|the)\s+cap\s+fund\b", re.I)
_CAP_SCHEMES = tuple(s.key for s in SCHEME_REGISTRY if " Cap " in f" {s.name} ")


def short_name(scheme: str) -> str:
    return scheme.removesuffix(" Direct Growth")


def scheme_names() -> list[str]:
    return [s.name for s in SCHEME_REGISTRY]


def scheme_list_text() -> str:
    """'A, B, C and D' for replies that list the covered schemes."""
    names = scheme_names()
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def detect_schemes(text: str) -> list[str]:
    """Schemes (internal names) the text mentions, in the order they are mentioned."""
    hits = [(m.start(), name) for name, pattern in SCHEME_PATTERNS.items()
            if (m := pattern.search(text))]
    return [name for _, name in sorted(hits)]


def former_name_used(text: str) -> tuple[str, str] | None:
    """(former name, current scheme) when the text uses a scheme's former name."""
    for scheme, names in FORMER_NAMES.items():
        for pattern, former in names:
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
    if not fuzzy and _AMBIGUOUS_CAP_RE.search(text) and len(_CAP_SCHEMES) > 1:
        return list(_CAP_SCHEMES)
    return []
