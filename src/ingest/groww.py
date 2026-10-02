"""Chunking for Groww scheme pages: one self-contained fact card per field.

The problem statement asks for a chunking strategy chosen from the data. Groww
scheme pages are short, structured label/value pages (after `_clean_groww` in
load.py), so instead of splitting text by size they are parsed into fields and
each field becomes one chunk that always names the fund, e.g.

    HDFC Small Cap Fund Direct Growth: Expense ratio (TER): 0.78%.

One overview card per fund lists the key facts together, for "tell me about X"
questions. Every card records its `field`, so retrieval can be checked field by
field (scripts/eval_gold.py --matrix).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


def is_groww_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "groww.in" or host.endswith(".groww.in")

_SINCE_RE = re.compile(r"^[A-Z][a-z]{2} \d{4}$")  # "Jun 2023"
_DATE_RE = re.compile(r"^\d{2} [A-Z][a-z]{2} \d{4}$")  # "08 May 2015"
_NAV_RE = re.compile(r"^NAV:\s*(\d{1,2}) (\w{3}) '(\d{2})$")
_RISK_RE = re.compile(r"\brated ([A-Za-z ]+?) risk\b", re.I)


@dataclass(frozen=True)
class FactCard:
    field: str  # machine name, e.g. "expense_ratio"
    label: str  # human label, used in the card text and section title
    text: str  # full card text (starts with the fund name)


def _next(lines: list[str], i: int) -> str | None:
    return lines[i + 1] if i + 1 < len(lines) else None


def _first_after(lines: list[str], label: str, start: int = 0) -> str | None:
    """Value on the line after the first `label` at or after `start`."""
    for i in range(start, len(lines)):
        if lines[i] == label:
            return _next(lines, i)
    return None


def _index(lines: list[str], label: str, start: int = 0) -> int | None:
    return next((i for i in range(start, len(lines)) if lines[i] == label), None)


def _managers(lines: list[str]) -> list[dict[str, str]]:
    """Parse the "Fund management" block: name, since, education, experience, and
    the other schemes each manager runs ("Also manages these schemes")."""
    start = _index(lines, "Fund management")
    end = _index(lines, "About", start or 0) if start is not None else None
    if start is None:
        return []
    block = lines[start + 1 : end]
    managers: list[dict[str, str]] = []
    in_others = False
    for i, line in enumerate(block):
        since = block[i + 1] if i + 1 < len(block) else ""
        if _SINCE_RE.match(since) and not _SINCE_RE.match(line):
            managers.append({"name": line, "since": since})
            in_others = False
        elif managers and line in ("Education", "Experience") and i + 1 < len(block):
            managers[-1][line.lower()] = block[i + 1]
        elif managers and line == "Also manages these schemes":
            in_others = True
        elif managers and in_others and line.startswith("HDFC "):
            others = managers[-1].get("other_schemes", "")
            managers[-1]["other_schemes"] = f"{others}; {line}" if others else line
    return managers


_PCT_RE = re.compile(r"^-?\d+(\.\d+)?%$")
HOLDINGS_PER_CARD = 25


def _holdings(lines: list[str]) -> tuple[str | None, list[tuple[str, str, str, str]]]:
    """(number of holdings, rows as (name, sector, instrument, "x.xx%"))."""
    start = next((i for i, l in enumerate(lines) if l.startswith("Holdings (")), None)
    if start is None:
        return None, []
    count = lines[start + 1] if start + 1 < len(lines) and lines[start + 1].isdigit() else None
    header = _index(lines, "Assets", start)
    rows: list[tuple[str, str, str, str]] = []
    i = (header + 1) if header is not None else start + 1
    while i + 3 < len(lines) and _PCT_RE.match(lines[i + 3]):
        rows.append(tuple(lines[i : i + 4]))  # type: ignore[arg-type]
        i += 4
    return count, rows


def _row_text(row: tuple[str, str, str, str]) -> str:
    name, sector, instrument, pct = row
    return f"{name} ({sector}, {instrument}): {pct}"


# Asset class of each instrument type Groww lists (anything else → "other").
_ASSET_CLASS = [
    ("equity", re.compile(r"^equity$", re.I)),
    ("cash and equivalents", re.compile(r"repo|net (current assets|payables|receivables)|"
                                        r"cash|treps|fixed deposit", re.I)),
    ("debt", re.compile(r"goi|government|bond|debenture|ncd|state development|"
                        r"certificate of deposit|commercial paper|t-?bill|treasury|"
                        r"securitised|debt|zero coupon", re.I)),
]


def _asset_class(instrument: str) -> str:
    return next((name for name, pattern in _ASSET_CLASS if pattern.search(instrument)),
                "other (REITs, InvITs, derivatives, etc.)")


def _sum_by(rows: list[tuple[str, str, str, str]], key, always: tuple[str, ...] = ()) -> str:
    """"group x.xx% (n holdings); ..." from the listed weights, largest first.
    Groups in `always` are shown even at 0.00% (e.g. "debt 0.00%" for an all-equity fund)."""
    totals: dict[str, float] = {g: 0.0 for g in always}
    counts: dict[str, int] = {g: 0 for g in always}
    for row in rows:
        group = key(row)
        totals[group] = totals.get(group, 0.0) + float(row[3].rstrip("%"))
        counts[group] = counts.get(group, 0) + 1
    ordered = sorted(totals, key=lambda g: -totals[g])
    return "; ".join(
        f"{g} {totals[g]:.2f}% ({counts[g]} holding{'s' if counts[g] != 1 else ''})"
        for g in ordered
    )


# Glossary terms Groww defines ("Understand terms"). The returns definitions are
# skipped: returns questions are refused before retrieval (performance guard).
_GLOSSARY_TERMS = ("Expense ratio", "Exit load", "Stamp duty", "Tax")


def _glossary(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        if line != "Understand terms":
            continue
        j = i + 1
        while j + 1 < len(lines) and lines[j] not in ("Understand terms", "Exit Load"):
            if lines[j] in _GLOSSARY_TERMS and lines[j] not in out:
                out[lines[j]] = lines[j + 1]
                j += 2
            else:
                j += 1
    return out


_FUND_HOUSE_LABELS = {
    "Rank (total assets)": "rank by total assets",
    "Total AUM": "total AUM of the fund house across all its schemes (not this fund's size)",
    "Date of Incorporation": "date of incorporation",
    "Launch Date": "launch date",
    "Phone": "phone",
    "Website": "website",
    "Address": "address",
    "Custodian": "custodian",
}


def _labelled_values(lines: list[str], start: int, stop_label: str, labels: dict[str, str]) -> list[str]:
    """"label value" pairs between `start` and `stop_label`, for known labels."""
    stop = _index(lines, stop_label, start) or len(lines)
    parts = []
    for i in range(start, stop - 1):
        if lines[i] in labels and "[email" not in lines[i + 1]:
            parts.append(f"{labels[lines[i]]} {lines[i + 1]}")
    return parts


def _exit_load_history(lines: list[str]) -> list[tuple[str, str]]:
    """(effective date, rule) pairs from the "Exit Load" history block."""
    start = _index(lines, "Exit Load")
    if start is None:
        return []
    history = []
    i = start + 1
    while i + 1 < len(lines) and _DATE_RE.match(lines[i]):
        history.append((lines[i], lines[i + 1]))
        i += 2
    return history


def _strip_exit_prefix(rule: str | None) -> str | None:
    """"Exit load of 1% if redeemed within 1 year" -> "1% if redeemed within 1 year"."""
    if rule is None:
        return None
    return re.sub(r"^exit load of\s+", "", rule.strip().rstrip("."), flags=re.I)


def _nav(lines: list[str]) -> tuple[str, str] | None:
    """(value, date) from "NAV: 25 Sep '26" followed by the value line."""
    for i, line in enumerate(lines):
        m = _NAV_RE.match(line)
        if m and _next(lines, i):
            day, month, yy = m.groups()
            return lines[i + 1], f"{int(day)} {month} 20{yy}"
    return None


def fact_cards(text: str, fund: str) -> list[FactCard]:
    """Parse one cleaned Groww page into fact cards for `fund`."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    cards: list[FactCard] = []

    def add(field: str, label: str, value: str | None, extra: str = "") -> None:
        value = (value or "").strip().rstrip(".").strip()
        if value and value != "--":
            cards.append(FactCard(field, label, f"{fund}: {label}: {value}{extra}."))

    nav = _nav(lines)
    if nav:
        add("nav", "NAV (net asset value) per unit", nav[0], f", as on {nav[1]}")
    add("expense_ratio", "Expense ratio (TER, total expense ratio)", _first_after(lines, "Expense ratio"))
    add("aum", "Fund size (AUM, assets under management)", _first_after(lines, "Fund size (AUM)"))
    add("min_sip", "Minimum SIP amount", _first_after(lines, "Min. for SIP"))
    first = _first_after(lines, "Min. for 1st investment")
    second = _first_after(lines, "Min. for 2nd investment")
    if first:
        add("min_lumpsum", "Minimum investment (lump sum)",
            f"{first} for the first investment" + (f", {second} for later investments" if second else ""))

    current = _first_after(lines, "Exit load", (_index(lines, "Exit load, stamp duty and tax") or 0))
    add("exit_load", "Exit load (current)", _strip_exit_prefix(current))
    history = [(d, _strip_exit_prefix(r)) for d, r in _exit_load_history(lines)]
    history = [(d, r) for d, r in history if r and r != "--"]
    if history:
        rules = "; ".join(f"from {d}: {r}" for d, r in history)
        add("exit_load_history", "Exit load history (earlier rules, not current)", rules)

    add("stamp_duty", "Stamp duty on investment", _first_after(lines, "Stamp duty on investment:"))
    add("tax", "Tax on redemption (capital gains tax)", _first_after(lines, "Tax implication"))

    about = " ".join(lines)
    risk = _RISK_RE.search(about)
    if risk:
        add("riskometer", "Riskometer (risk level)", risk.group(1).strip())
    add("benchmark", "Benchmark index (the index the fund is measured against)",
        _first_after(lines, "Fund benchmark"))
    add("objective", "Investment objective", _first_after(lines, "Investment Objective"))

    managers = _managers(lines)
    if managers:
        names = "; ".join(f"{m['name']} (since {m['since']})" for m in managers)
        add("fund_managers", "Fund managers (the people who manage this fund)", names)
        for m in managers:
            details = ". ".join(
                f"{k.title()}: {m[k].rstrip('.')}" for k in ("education", "experience") if m.get(k)
            )
            add("fund_manager_profile", f"Fund manager {m['name']}",
                f"managing since {m['since']}" + (f". {details}" if details else ""))
            if m.get("other_schemes"):
                add("fund_manager_other_schemes",
                    f"Other schemes also managed by fund manager {m['name']}", m["other_schemes"])

    # One headline holdings card (count + top 10) so "what are the holdings" and
    # "how many holdings" both land on it; a card that is mostly company names
    # alone embeds as "banks and companies", not "holdings".
    count, rows = _holdings(lines)
    if rows:
        total = f"{count} holdings in total. " if count else ""
        add("holdings", "Holdings (portfolio: the stocks, bonds and other instruments the "
            "fund holds, as listed on Groww)",
            f"{total}Top 10 holdings by % of assets: " + "; ".join(map(_row_text, rows[:10])))
        for n in range(10, len(rows), HOLDINGS_PER_CARD):
            group = rows[n : n + HOLDINGS_PER_CARD]
            add("holdings_more", f"More holdings, numbers {n + 1}–{n + len(group)} by % of "
                "assets (portfolio, as listed on Groww)", "; ".join(map(_row_text, group)))

        # Holdings analysis. Groww's page states no allocation totals, only each
        # holding's weight, so these are sums of the listed weights, computed here
        # exactly and labelled as such (portfolio arithmetic, not returns).
        basis = (f"calculated by adding up the % of assets of the {len(rows)} holdings "
                 "listed on Groww; totals may not be exactly 100% due to rounding")
        add("holdings_breakdown",
            f"Holdings analysis summary: asset allocation ratio of equity vs debt vs "
            f"cash ({basis})",
            _sum_by(rows, lambda r: _asset_class(r[2]),
                    always=("equity", "debt", "cash and equivalents")))
        add("holdings_breakdown",
            f"Detailed breakdown by instrument type, e.g. debentures, government "
            f"securities ({basis})",
            _sum_by(rows, lambda r: r[2]))
        add("holdings_breakdown",
            f"Sector allocation, % of assets in each sector ({basis})",
            _sum_by(rows, lambda r: r[1]))
    elif count:
        add("holdings", "Holdings (portfolio, as listed on Groww)", f"{count} holdings in total")

    for term, definition in _glossary(lines).items():
        add("definition", f"Definition of {term.lower()} (what the term means)", definition)

    fund_house = _first_after(lines, "Fund house")
    house_i = _index(lines, "Fund house")
    rta = _first_after(lines, "Registrar & Transfer Agent")
    rta_i = _index(lines, "Registrar & Transfer Agent")
    if fund_house and house_i is not None:
        details = _labelled_values(lines, house_i, "Registrar & Transfer Agent", _FUND_HOUSE_LABELS)
        add("fund_house", "Fund house (AMC, the asset management company)",
            fund_house + (f". Details: {'; '.join(details)}" if details else ""))
    if rta and rta_i is not None:
        rta_details = _labelled_values(lines, rta_i, "\x00", {"Website": "website", "Address": "address"})
        add("registrar", "Registrar and transfer agent (RTA, where to get account and "
            "capital gains statements)",
            rta + (f"; {'; '.join(rta_details)}" if rta_details else ""))

    # Overview card: the headline facts together.
    by_field = {c.field: c.text.split(": ", 2)[-1].rstrip(".") for c in cards}
    headline = [
        ("NAV", "nav"), ("expense ratio", "expense_ratio"), ("fund size (AUM)", "aum"),
        ("minimum SIP", "min_sip"), ("exit load", "exit_load"), ("riskometer", "riskometer"),
        ("benchmark", "benchmark"), ("fund managers", "fund_managers"),
    ]
    summary = "; ".join(f"{label} {by_field[f]}" for label, f in headline if f in by_field)
    if summary:
        cards.insert(0, FactCard("overview", "Key facts", f"{fund}: Key facts: {summary}."))
    return cards
