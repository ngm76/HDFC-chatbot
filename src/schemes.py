"""The five in-scope schemes and how queries name them.

Shared by retrieval (scheme filter) and guards (performance links, scope checks),
so both agree on what "names a scheme" means. Keys match the `scheme` column in
data/sources.csv and the Chroma metadata.
"""

from __future__ import annotations

import re

SHARED_SCHEME = "ALL"

SCHEME_PATTERNS: dict[str, re.Pattern[str]] = {
    "HDFC Large Cap Fund Direct Growth": re.compile(
        r"\blarge[\s-]?cap\b(?!\s*(and|&)\s*mid)", re.I
    ),
    "HDFC Flexi Cap Fund Direct Growth": re.compile(
        r"\bflexi[\s-]?cap\b|\bhdfc equity fund\b", re.I
    ),
    "HDFC ELSS Tax Saver Fund Direct Growth": re.compile(
        r"\belss\b|\btax[\s-]?saver\b|\btaxsaver\b", re.I
    ),
    "HDFC Small Cap Fund Direct Growth": re.compile(r"\bsmall[\s-]?cap\b", re.I),
    "HDFC Balanced Advantage Fund Direct Growth": re.compile(
        r"\bbalanced advantage\b|\bbaf\b", re.I
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


def detect_schemes(text: str) -> list[str]:
    """Schemes (internal names) the text mentions, in SCHEME_PATTERNS order."""
    return [name for name, pattern in SCHEME_PATTERNS.items() if pattern.search(text)]
