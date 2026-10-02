"""Structured key facts for one scheme, read from its fact cards in Chroma.

Used by the UI's fund cards and fact sheet, so the figures shown always match
what the chatbot answers from (same cards, same data refresh).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ingest.chunk import PARENT_SEP
from src.rag.retrieve import _collection

_ROW_RE = re.compile(r"(?P<name>[^;]+?) \([^)]*\): (?P<pct>-?\d+(?:\.\d+)?%)")
_MIX_RE = re.compile(r"(?P<name>[a-z][a-z ]*?)(?: \([^)]*\))? (?P<pct>\d+\.\d+)% \(")


@dataclass
class FundFacts:
    scheme: str
    url: str = ""
    fetched_at: str = ""
    values: dict[str, str] = field(default_factory=dict)  # field -> value text
    nav: str = ""
    nav_date: str = ""
    holdings_count: str = ""
    top_holdings: list[tuple[str, str]] = field(default_factory=list)  # (name, "x.xx%")
    asset_mix: list[tuple[str, float]] = field(default_factory=list)  # (class, percent)

    def get(self, key: str, default: str = "—") -> str:
        return self.values.get(key) or default


def _value(text: str, section_title: str, scheme: str) -> str:
    """Card text is "<scheme>: <label>: <value>." → value."""
    label = section_title.split(PARENT_SEP, 1)[-1]
    prefix = f"{scheme}: {label}: "
    value = text[len(prefix):] if text.startswith(prefix) else text.split(": ", 2)[-1]
    return value.rstrip(".").strip()


def fund_facts(scheme: str) -> FundFacts:
    cards = _collection().get(where={"scheme": scheme}, include=["documents", "metadatas"])
    facts = FundFacts(scheme)
    for text, meta in zip(cards["documents"], cards["metadatas"]):
        facts.url = facts.url or meta.get("url", "")
        facts.fetched_at = facts.fetched_at or meta.get("fetched_at", "")
        name = meta.get("field", "")
        title = meta.get("section_title", "")
        value = _value(text, title, scheme)
        if name == "holdings_breakdown":
            if "summary" in title:  # the asset-class card
                facts.asset_mix = [
                    (m.group("name").strip(), float(m.group("pct")))
                    for m in _MIX_RE.finditer(value)
                ]
                facts.values["asset_mix"] = value
            continue
        if name in ("holdings_more", "fund_manager_profile", "fund_manager_other_schemes",
                    "definition"):
            continue
        facts.values[name] = value

    nav = facts.values.get("nav", "")
    if ", as on " in nav:
        facts.nav, facts.nav_date = nav.split(", as on ", 1)
    else:
        facts.nav = nav
    holdings = facts.values.get("holdings", "")
    count = re.match(r"(\d[\d,]*) holdings in total", holdings)
    facts.holdings_count = count.group(1) if count else ""
    top = holdings.split("by % of assets: ", 1)[-1]
    facts.top_holdings = [(m.group("name").strip(), m.group("pct")) for m in _ROW_RE.finditer(top)]
    return facts
