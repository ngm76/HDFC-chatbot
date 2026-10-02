"""Fact cards for the official corpus (Phase 14): one self-contained card per fact.

The problem statement asks for a chunking strategy chosen from the data. The
official corpus mixes structured documents with prose, so each type gets its own
parser and every supported fact becomes one card that names its scheme:

    HDFC Small Cap Fund Direct Growth: Expense ratio (TER, total expense ratio),
    Direct Plan: 0.79% as on 30 Sep 2026 ...

- scheme_page (hdfcfund.com, one fund): riskometer, min SIP, AUM, benchmark, exit
  load, lock-in, entry load, fund managers, inception date, factual FAQs, plus the
  shared glossary definitions on the page.
- kim (one fund): minimum application amount, exit load rules, ELSS lock-in,
  former name.
- factsheet (all funds): for each of the five schemes, Direct Plan NAV with its
  "as on" date, investment objective, inception date, fund manager details,
  holdings and holdings analysis (A1).
- ter (all funds): latest Direct and Regular total TER per scheme.

Only cards are taken from KIMs and the factsheet: their returns and risk-ratio
tables are never indexed (PRD: no performance claims). Prose documents (statement
guides, SEBI / AMFI pages) use the generic heading-aware splitter in chunk.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from src.schemes import SCHEMES, SHARED_SCHEME

CARD_DOC_TYPES = ("scheme_page", "kim", "factsheet", "ter")

# How each scheme is named inside the shared documents (factsheet headings, TER rows).
DOC_NAMES: dict[str, str] = {
    "HDFC Large Cap Fund Direct Growth": "HDFC Large Cap Fund",
    "HDFC Flexi Cap Fund Direct Growth": "HDFC Flexi Cap Fund",
    "HDFC ELSS Tax Saver Fund Direct Growth": "HDFC ELSS - Tax Saver Fund",
    "HDFC Small Cap Fund Direct Growth": "HDFC Small Cap Fund",
    "HDFC Balanced Advantage Fund Direct Growth": "HDFC Balanced Advantage Fund",
}
DIRECT_PLAN = "Direct Plan - Growth"
_MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
           "November|December")


@dataclass(frozen=True)
class OfficialCard:
    field: str  # machine name, e.g. "expense_ratio"
    label: str  # human label, used in the card text and section title
    text: str  # full card text (starts with the scheme name, or the label if shared)
    scheme: str  # internal scheme name, or SHARED_SCHEME
    doc_date: str = ""  # ISO date the document states for this fact, if any
    plan: str = ""


def _card(scheme: str, field: str, label: str, value: str | None, *,
          doc_date: str = "", plan: str = "") -> OfficialCard | None:
    value = " ".join((value or "").split()).strip().rstrip(".").strip()
    if not value or value == "--":
        return None
    subject = scheme if scheme != SHARED_SCHEME else ""
    text = f"{subject}: {label}: {value}." if subject else f"{label}: {value}."
    return OfficialCard(field, label, text, scheme, doc_date, plan)


def _iso(text: str) -> str:
    """'AUGUST 31, 2026' / 'May 30, 2025' / '31/08/2026' / '30-Sep-2026' -> ISO date."""
    text = " ".join(text.replace(",", ", ").split()).strip()
    for fmt in ("%B %d, %Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text.title() if "%B" in fmt else text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def human_date(iso: str) -> str:
    """'2026-08-31' -> '31 Aug 2026' (the PRD's DD Mon YYYY)."""
    return datetime.fromisoformat(iso).strftime("%d %b %Y") if iso else ""


def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


def _index(lines: list[str], label: str, start: int = 0) -> int | None:
    return next((i for i in range(start, len(lines)) if lines[i] == label), None)


# --- HDFC scheme pages ------------------------------------------------------------
_DEFINITION_LABELS = {  # panel label -> glossary term
    "TER": "expense ratio (TER, total expense ratio)",
    "Entry Load": "entry load",
    "Lock in": "lock-in period",
    "NAV": "NAV (net asset value)",
    "AUM": "AUM (assets under management)",
    "Benchmark": "benchmark",
}
# Manager list: "Mr. Ihab Dalwai" / "Nandita Menezes" (names, with or without a title),
# each optionally followed by a role line; all-caps tags ("OVERSEAS") are skipped.
_ROLE_RE = re.compile(r"Manager|Head|Analyst|Member|Equit|Fixed Income|Team|Investments|"
                      r"Dealer|Officer|\bCIO\b", re.I)
_NAME_RE = re.compile(r"^((Mr|Ms|Mrs|Dr)\.?\s)?[A-Z][a-zA-Z.'-]*( [A-Z][a-zA-Z.'-]*){1,3}$")


def _panel_value(lines: list[str], label: str, *, skip_long: bool = True) -> str | None:
    """First short value after a fact-panel label, skipping its definition text."""
    i = _index(lines, label)
    if i is None:
        return None
    for line in lines[i + 1 : i + 8]:
        if skip_long and len(line) > 80:
            continue  # the label's definition
        if line.startswith(("(", "Disclaimer", "Including")) or line == label:
            continue
        return line
    return None


def _definitions(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, term in _DEFINITION_LABELS.items():
        i = _index(lines, label)
        if i is None:
            continue
        definition = next((l for l in lines[i + 1 : i + 5] if len(l) > 80), None)
        if definition:
            out[term] = definition.replace("Ration", "Ratio")  # typo on HDFC's page
    return out


def _between(lines: list[str], start_label: str, stops: tuple[str, ...]) -> list[str]:
    i = _index(lines, start_label)
    if i is None:
        return []
    out = []
    for line in lines[i + 1 :]:
        if line in stops or line.startswith(stops):
            break
        out.append(line)
    return out


def scheme_page_cards(text: str, scheme: str) -> list[OfficialCard]:
    lines = _lines(text)
    cards: list[OfficialCard | None] = []

    def add(field: str, label: str, value: str | None, **kw) -> None:
        cards.append(_card(scheme, field, label, value, plan=kw.pop("plan", DIRECT_PLAN), **kw))

    kind = next((l for l in lines if re.match(r"an open[- ]?ended", l, re.I)), None)
    add("scheme_type", "Type of scheme (category)", kind)
    add("riskometer", "Riskometer (risk level)", _panel_value(lines, "Riskometer"))
    min_sip = _panel_value(lines, "Min SIP")
    add("min_sip", "Minimum SIP amount (per instalment)", (min_sip or "").replace("₹ ", "₹"))

    lock = _panel_value(lines, "Lock in")
    if lock and lock.upper() == "NA":
        lock = "no lock-in period (shown as NA on the scheme page)"
    add("lock_in", "Lock-in period", lock)

    entry = _panel_value(lines, "Entry Load")
    if entry and entry.upper() == "NA":
        entry = "none (shown as NA; mutual funds in India do not levy entry loads)"
    add("entry_load", "Entry load", entry)

    aum_i = _index(lines, "AUM")
    if aum_i is not None:
        window = lines[aum_i + 1 : aum_i + 6]
        date = next((_iso(l.strip("()")) for l in window if re.fullmatch(r"\(\d{2}/\d{2}/\d{4}\)", l)), "")
        value = next((l for l in window if re.match(r"^₹\s?[\d,]+(\.\d+)?\s?Cr", l)), None)
        if value:
            value = value.replace("Cr.", "Cr").replace("₹ ", "₹")
            add("aum", "Fund size (AUM, assets under management)",
                f"{value}, as on {human_date(date)}" if date else value, doc_date=date)

    bench_i = _index(lines, "Benchmark")
    if bench_i is not None:
        bench = next((l for l in lines[bench_i + 1 : bench_i + 5]
                      if len(l) <= 80 and not l.endswith("...")), None)
        add("benchmark", "Benchmark index (the index the fund is measured against)", bench)

    inception = _panel_value(lines, "Inception Date")
    if inception:
        # The Direct Plan's start, not the scheme's launch (that is the factsheet's
        # "date of allotment"), so it gets its own field.
        add("plan_inception_date", "Inception date of the Direct Plan",
            human_date(_iso(inception)) or inception)

    managers = _between(lines, "Fund Managers", ("Portfolio Allocation",))
    people: list[list[str]] = []  # [name, role]
    for line in managers:
        if line.isupper():
            continue
        if _ROLE_RE.search(line) and people and not people[-1][1]:
            people[-1][1] = line
        elif _NAME_RE.match(line) and not _ROLE_RE.search(line):
            people.append([line, ""])
    add("fund_managers", "Fund managers (the people who manage this fund)",
        "; ".join(f"{name} ({role})" if role else name for name, role in people))

    exit_lines = _between(lines, "Exit Load", ("Product Labelling", "Benchmark Riskometer", "FAQs"))
    add("exit_load", "Exit load (current)",
        "; ".join(l.lstrip("●•").strip().rstrip(".") for l in exit_lines))

    steps = _between(lines, next((l for l in lines if l.startswith("How to start investing")), "\x00"),
                     ("Inception Date", "Riskometer"))
    if steps:
        add("how_to_invest", "How to start investing (steps)", "; ".join(steps), plan="")

    faq = _between(lines, "FAQs", ("\x00",))
    question, answer = None, []
    for line in faq + ["?"]:
        if line.endswith("?"):
            if question and answer:
                add("scheme_faq", re.sub(r"^\d+\.\s*", "", question), " ".join(answer), plan="")
            question, answer = line, []
        else:
            answer.append(line)

    for term, definition in _definitions(lines).items():
        cards.append(_card(SHARED_SCHEME, "definition", f"Definition of {term} (what the term means)",
                           definition))
    return [c for c in cards if c]


# --- KIMs ---------------------------------------------------------------------------
_KIM_NOISE_RE = re.compile(r"^\d{1,3}$|- KIM$|^Page \d+", re.I)
_KIM_STOP_RE = re.compile(
    r"^(\d{1,2}\.|\([ivx]+\))?\s*(Recurring Expenses|Despatch of Redemption|Benchmark Index|"
    r"Dividend|IDCW Policy|Name of the Fund Manager|Plans|Applicable NAV|Waiver|Tax treatment|"
    r"Daily Net Asset|Load Structure|Minimum Application|Scheme Performance|Compounded|"
    r"Returns for|For Riskometer|Expenses of the Scheme)",
    re.I,
)
_KIM_SECTIONS = {
    "min_lumpsum": (re.compile(r"^(\d{1,2}\.)?\s*Minimum Application Amount", re.I),
                    "Minimum application amount (lump sum purchase, additional purchase and "
                    "redemption)"),
    "exit_load_rules": (re.compile(r"^(\d{1,2}\.|\([ivx]+\))?\s*Load Structure", re.I),
                        "Exit load rules in full (Key Information Memorandum)"),
}
MAX_SECTION_CHARS = 2000


def _kim_section(lines: list[str], start_re: re.Pattern[str]) -> str:
    start = next((i for i, l in enumerate(lines) if start_re.match(l)), None)
    if start is None:
        return ""
    body: list[str] = [start_re.sub("", lines[start]).strip(" /:-")]
    for line in lines[start + 1 :]:
        if _KIM_STOP_RE.match(line):
            break
        if not _KIM_NOISE_RE.search(line):
            body.append(line)
    text = " ".join(" ".join(body).split())
    text = re.sub(r"^Number of Units\s*", "", text)  # column-header residue
    if len(text) > MAX_SECTION_CHARS:  # cut at the last full sentence that fits
        cut = text.rfind(". ", 0, MAX_SECTION_CHARS)
        text = text[: cut + 1] if cut > 0 else text[:MAX_SECTION_CHARS]
    return text


def kim_date(url: str) -> str:
    m = re.search(r"dated%20(\w+)%20(\d{1,2}),%20(\d{4})", url)
    return _iso(f"{m.group(1)} {m.group(2)}, {m.group(3)}") if m else ""


def kim_cards(text: str, scheme: str, url: str) -> list[OfficialCard]:
    lines = _lines(text)
    joined = " ".join(lines)
    date = kim_date(url)
    when = f" (KIM dated {human_date(date)})" if date else ""
    cards: list[OfficialCard | None] = []
    for field, (start_re, label) in _KIM_SECTIONS.items():
        cards.append(_card(scheme, field, label + when, _kim_section(lines, start_re), doc_date=date))
    former = re.search(r"\(Formerly known as ([^)]+)\)", joined)
    if former:
        cards.append(_card(scheme, "former_name", "Former name of the scheme", former.group(1),
                           doc_date=date))
    if "ELSS" in scheme:
        rule = re.search(r"Units of the Scheme[^.]{0,200}?until completion of three years[^.]*", joined)
        kind = re.search(r"statutory lock[- ]?in of 3 years", joined, re.I)
        if rule or kind:
            value = "3 years (statutory lock-in)" + (f". {rule.group(0).strip()}" if rule else "")
            cards.append(_card(scheme, "lock_in", "Lock-in period (ELSS)" + when, value, doc_date=date))
    return [c for c in cards if c]


# --- Monthly factsheet -----------------------------------------------------------------
def _fund_block(lines: list[str], name: str) -> list[str]:
    """The fund's own pages: from its heading (followed by CATEGORY OF SCHEME) to the
    end of its portfolio ("Grand Total" and the page's footnotes)."""
    for i, line in enumerate(lines):
        if line != name:
            continue
        window = lines[i + 1 : i + 6]
        if "CATEGORY OF SCHEME" in window and not any("Contd from" in w for w in window):
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("Grand Total")), len(lines))
            tail = next((j for j in range(end + 1, min(end + 60, len(lines)))
                         if re.match(r"^\d{1,3} \| \w+ \d{4}$", lines[j])), min(end + 40, len(lines)))
            return lines[i:tail]
    return []


# AMFI industry names, used to split "ICICI Bank Ltd. Banks 10.05" into name / industry.
AMFI_INDUSTRIES = (
    "Aerospace & Defense", "Agricultural Food & Other Products",
    "Agricultural, Commercial & Construction Vehicles", "Auto Components", "Automobiles",
    "Banks", "Beverages", "Capital Markets", "Cement & Cement Products",
    "Chemicals & Petrochemicals", "Cigarettes & Tobacco Products", "Commercial Services & Supplies",
    "Construction", "Consumable Fuels", "Consumer Durables", "Diversified",
    "Diversified FMCG", "Diversified Metals", "Electrical Equipment", "Engineering Services",
    "Entertainment", "Fertilizers & Agrochemicals", "Finance", "Financial Technology (Fintech)",
    "Food Products", "Gas", "Healthcare Equipment & Supplies", "Healthcare Services",
    "Household Products", "IT - Hardware", "IT - Services", "IT - Software",
    "Industrial Manufacturing", "Industrial Products", "Insurance", "Leisure Services",
    "Media", "Metals & Minerals Trading", "Minerals & Mining", "Non - Ferrous Metals",
    "Ferrous Metals", "Oil", "Other Construction Materials", "Other Consumer Services",
    "Other Utilities", "Paper, Forest & Jute Products", "Personal Products",
    "Petroleum Products", "Pharmaceuticals & Biotechnology", "Power",
    "Printing & Publication", "Realty", "Retailing", "Telecom - Equipment & Accessories",
    "Telecom - Services", "Textiles & Apparels", "Transport Infrastructure",
    "Transport Services",
)
_INDUSTRIES = sorted(AMFI_INDUSTRIES, key=len, reverse=True)
_RATING_RE = re.compile(
    r"\s((Sovereign)|((CRISIL|ICRA|CARE|IND|FITCH|BRICKWORK)\s*-\s*[A-Z]{1,3}[+-]?\d?\+?"
    r"(\((CE|SO)\))?)(\s*/\s*(CRISIL|ICRA|CARE|IND|FITCH)\s*-\s*[A-Z]{1,3}[+-]?\d?\+?(\((CE|SO)\))?)*)$"
)
_SECTION_CLASSES = (  # portfolio sub-heading -> asset class
    (re.compile(r"^EQUITY & EQUITY RELATED", re.I), "equity"),
    (re.compile(r"^(DEBT & DEBT RELATED|Government Securities|Credit Exposure|Corporate Debt|"
                r"Treasury Bills?|Securitised|Zero Coupon)", re.I), "debt"),
    (re.compile(r"^(UNITS ISSUED BY (REIT|INVIT)|Units issued by (ReIT|InvIT))", re.I), "reits and invits"),
    (re.compile(r"^(MONEY MARKET INSTRUMENTS|CD|CP|TREPS)$", re.I), "money market"),
    (re.compile(r"^MUTUAL FUND UNITS", re.I), "mutual fund units"),
)
_ROW_END_RE = re.compile(r"\s(-?\d+\.\d{2}|@)(?:\s+-?\d+\.\d{2})?$")
_SECOND_COL = r"(?:\s+-?\d+\.\d{2})?"  # optional "% exposure of derivative" column
# Wrapped column-header lines ("/Rating % to", "NAV (Hedged &", "% exposure", ...).
_HEADER_TAIL_RE = re.compile(r"^(/Rating|% to|NAV\b|\(?Hedged|Unhedged|% exposure|of$|of Derivative|"
                             r"Derivative$)", re.I)
_TABLE_HEADER_RE = re.compile(r"^Company(/Instrument)?\s+Industry")
# Lines after which the next rows are not holdings (page breaks, returns tables).
_PAUSE_RE = re.compile(r"Contd (on next|from previous) page|PERFORMANCE", re.I)
_CASH_RE = re.compile(r"^Cash,\s*Cash Equivalents and Net Current Assets\s+(-?\d+\.\d{2})")
_SUB_TOTAL_RE = re.compile(r"^Sub Total\s+(-?\d+\.\d{2})" + _SECOND_COL + "$")
_TOTAL_RE = re.compile(r"^Total\s+-?\d+\.\d{2}" + _SECOND_COL + "$")


@dataclass(frozen=True)
class Holding:
    name: str
    group: str  # AMFI industry for equity, rating for debt ("" if unknown)
    asset_class: str
    pct: str  # "10.05" or "<0.01"


def _section_class(line: str) -> str | None:
    return next((cls for pattern, cls in _SECTION_CLASSES if pattern.match(line)), None)


def portfolio(block: list[str]) -> tuple[list[Holding], dict[str, float], dict[str, float]]:
    """(holdings, asset class -> stated %, instrument sub-heading -> stated %).

    The % figures per asset class are the factsheet's own "Sub Total" and cash lines,
    not sums computed here. Pages are two-column PDFs, so continuation pages are
    skipped until the next "Company/Instrument" table header, and so are the returns
    tables that share those pages."""
    holdings: list[Holding] = []
    by_class: dict[str, float] = {}
    by_heading: dict[str, float] = {}
    active = False
    asset_class, heading, partial = "", "", ""
    for line in block:
        if _TABLE_HEADER_RE.match(line):
            active, partial = True, ""
            continue
        if _PAUSE_RE.search(line):
            active, partial = False, ""
            continue
        if not active or (not partial and _HEADER_TAIL_RE.match(line)):
            continue
        if line.startswith("Grand Total"):
            break
        sub = _SUB_TOTAL_RE.match(line)
        if sub:
            value = float(sub.group(1))
            by_class[asset_class or "other"] = by_class.get(asset_class or "other", 0.0) + value
            if heading:
                by_heading[heading] = by_heading.get(heading, 0.0) + value
            partial = ""
            continue
        if _TOTAL_RE.match(line):
            continue
        cash = _CASH_RE.match(line)
        if cash:
            by_class["cash and equivalents"] = by_class.get("cash and equivalents", 0.0) + float(cash.group(1))
            continue
        cls = _section_class(line) if not partial else None
        if cls:
            asset_class = cls
            heading = line if not line.isupper() or cls != "equity" else "Equity & equity related"
            continue
        partial = f"{partial} {line}".strip()
        end = _ROW_END_RE.search(partial)
        if not end:
            continue
        pct = "<0.01" if end.group(1) == "@" else end.group(1)
        rest = partial[: end.start()].lstrip("•").strip()
        rest = re.sub(r"[£$#^*]+(?=\s|$)", "", rest).strip()
        group = ""
        rating = _RATING_RE.search(" " + rest)
        if rating and asset_class != "equity":
            group, rest = rating.group(1), (" " + rest)[: rating.start()].strip()
        else:
            for industry in _INDUSTRIES:
                if rest.lower().endswith(" " + industry.lower()):
                    group, rest = industry, rest[: -len(industry)].strip()
                    break
        holdings.append(Holding(rest, group, asset_class or "other", pct))
        partial = ""
    return holdings, by_class, by_heading


def _pct(h: Holding) -> float:
    return 0.0 if h.pct.startswith("<") else float(h.pct)


def _fmt_mix(totals: dict[str, float], counts: dict[str, int] | None = None, notes: dict[str, str] | None = None) -> str:
    parts = []
    for name in sorted(totals, key=lambda g: -totals[g]):
        if counts is not None and name in counts:
            n = counts[name]
            extra = f"{n} holding{'s' if n != 1 else ''}"
        else:
            extra = (notes or {}).get(name, "as stated")
        parts.append(f"{name} {totals[name]:.2f}% ({extra})")
    return "; ".join(parts)


def _managers_table(block: list[str]) -> list[str]:
    start = next((i for i, l in enumerate(block) if l.startswith("Name Since")), None)
    end = next((i for i, l in enumerate(block) if l.startswith("DATE OF ALLOTMENT")), None)
    if start is None or end is None:
        return []
    joined = " ".join(block[start + 1 : end])
    pattern = re.compile(
        rf"(?P<name>[A-Z][A-Za-z.'\- ]+?)\s*(?P<roles>(?:\((?:[^()]|\([^()]*\))*\)\s*)*)"
        rf"(?P<since>(?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}})\s*Over (?P<exp>\d+) years"
    )
    out = []
    for m in pattern.finditer(joined):
        roles = " ".join(m.group("roles").split())
        since = _iso(m.group("since"))
        out.append(f"{m.group('name').strip()}{' ' + roles if roles else ''}: managing this fund "
                   f"since {human_date(since) or m.group('since')}, total experience over "
                   f"{m.group('exp')} years")
    return out


def factsheet_cards(text: str) -> list[OfficialCard]:
    lines = _lines(text)
    cards: list[OfficialCard | None] = []
    for scheme in SCHEMES:
        block = _fund_block(lines, DOC_NAMES[scheme])
        if not block:
            continue
        joined = " ".join(block)
        as_on = re.search(r"\(As On ([A-Za-z]+ \d{1,2}, \d{4})\)", joined)
        date = _iso(as_on.group(1)) if as_on else ""
        when = f"as on {human_date(date)}" if date else ""

        def add(field: str, label: str, value: str | None, plan: str = "") -> None:
            cards.append(_card(scheme, field, label, value, doc_date=date, plan=plan))

        nav = re.search(r"Direct Plan - Growth Option\s+([\d,]+\.\d+)", joined)
        if nav:
            add("nav", "NAV (net asset value) per unit, Direct Plan - Growth",
                f"₹{nav.group(1)}, {when} (monthly factsheet)", plan=DIRECT_PLAN)
        else:
            # Some pages lose the option names in the PDF text ("Direct Plan - Tax
            # Saver Fund 94.510"), so which value is Growth cannot be read. Both are
            # stated, never guessed.
            values = re.findall(r"Direct Plan - [A-Za-z ]+?\s([\d,]+\.\d+)", joined)
            if values:
                add("nav", "NAV (net asset value) per unit, Direct Plan",
                    f"the factsheet lists {len(values)} Direct Plan values ("
                    + " and ".join(f"₹{v}" for v in values)
                    + f"), {when}, for its Growth and IDCW options; its text does not label "
                    "which is which, so check the linked factsheet")
        objective = re.search(r"INVESTMENT OBJECTIVE:\s*(.+?)\s*FUND MANAGER", joined)
        if objective:
            add("objective", "Investment objective", objective.group(1))
        allotted = re.search(r"DATE OF ALLOTMENT/INCEPTION DATE\s+((?:%s) \d{1,2},\s*\d{4})" % _MONTHS, joined)
        if allotted:
            add("inception_date", "Date of allotment (inception date) of the scheme",
                human_date(_iso(allotted.group(1))))
        for profile in _managers_table(block):
            name = profile.split(":")[0].split(" (")[0]
            add("fund_manager_profile", f"Fund manager {name} (factsheet {when})", profile)
        overseas = re.search(r"¥\s*(Fund Manager for Overseas Investments:.+?)(?=\s€|\s\$\$|\s\^\s|Please refer|$)", joined)
        if overseas:
            add("fund_manager_profile", f"Fund manager for overseas investments and recent changes (factsheet {when})",
                overseas.group(1))

        holdings, by_class, by_heading = portfolio(block)
        if not holdings:
            continue
        ranked = sorted(holdings, key=_pct, reverse=True)

        def row(h: Holding) -> str:
            return f"{h.name} ({h.group or h.asset_class}): {h.pct}%"

        add("holdings", f"Holdings (portfolio: the stocks, bonds and other instruments the fund holds, "
            f"factsheet {when})",
            f"{len(holdings)} holdings in total. Top 10 holdings by % of net assets: "
            + "; ".join(map(row, ranked[:10])))
        for n in range(10, len(ranked), 25):
            group = ranked[n : n + 25]
            add("holdings_more", f"More holdings, numbers {n + 1}–{n + len(group)} by % of net assets "
                f"(factsheet {when})", "; ".join(map(row, group)))

        counts: dict[str, int] = {}
        for h in holdings:
            counts[h.asset_class] = counts.get(h.asset_class, 0) + 1
        for cls in ("equity", "debt", "cash and equivalents"):
            by_class.setdefault(cls, 0.0)
        stated = sum(by_class.values())
        if abs(stated - 100) <= 1.0:  # the stated subtotals reconcile to the Grand Total
            add("holdings_breakdown",
                f"Holdings analysis summary: asset allocation ratio of equity vs debt vs cash "
                f"(from the factsheet portfolio subtotals, {when}; a class with several "
                f"subtotals, e.g. government securities and corporate debt, is their sum)",
                _fmt_mix(by_class, counts, {"cash and equivalents": "cash, cash equivalents and net current assets"}))
        if by_heading:
            add("holdings_breakdown",
                f"Detailed breakdown by instrument type, e.g. government securities, corporate "
                f"debt, REITs (as stated in the factsheet subtotals, {when})",
                _fmt_mix(by_heading))
        sectors: dict[str, float] = {}
        sector_counts: dict[str, int] = {}
        for h in holdings:
            if h.asset_class == "equity" and h.group:
                sectors[h.group] = sectors.get(h.group, 0.0) + _pct(h)
                sector_counts[h.group] = sector_counts.get(h.group, 0) + 1
        if sectors:
            add("holdings_breakdown",
                f"Sector allocation of equity holdings, % of net assets in each sector (calculated by "
                f"adding up the % of net assets of the equity holdings listed in the factsheet, {when}; "
                f"totals may differ slightly due to rounding)",
                _fmt_mix(sectors, sector_counts))
    return [c for c in cards if c]


# --- TER disclosure workbook ------------------------------------------------------------
def ter_cards(text: str) -> list[OfficialCard]:
    """Latest row per scheme. Columns: name | code | date | Regular BER, brokerage,
    transaction cost, statutory levies, total | Direct (same five)."""
    latest: dict[str, list[str]] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) < 13 or cells[0] not in DOC_NAMES.values():
            continue
        date = _iso(cells[2])
        if date and (cells[0] not in latest or date >= _iso(latest[cells[0]][2])):
            latest[cells[0]] = cells
    cards: list[OfficialCard | None] = []
    for scheme, name in DOC_NAMES.items():
        cells = latest.get(name)
        if not cells:
            continue
        date = _iso(cells[2])
        reg_total, direct = cells[7], cells[8:13]
        value = (f"Direct Plan: {direct[4]}% as on {human_date(date)} (base expense ratio "
                 f"{direct[0]}%, brokerage {direct[1]}%, transaction cost {direct[2]}%, statutory "
                 f"levies incl. GST {direct[3]}%). Regular Plan: {reg_total}% (Regular Plan values "
                 f"differ because they include distribution costs)")
        cards.append(_card(scheme, "expense_ratio", "Expense ratio (TER, total expense ratio)", value,
                           doc_date=date, plan=DIRECT_PLAN))
    return [c for c in cards if c]


def official_cards(text: str, doc_type: str, scheme: str, url: str) -> list[OfficialCard]:
    if doc_type == "scheme_page":
        return scheme_page_cards(text, scheme)
    if doc_type == "kim":
        return kim_cards(text, scheme, url)
    if doc_type == "factsheet":
        return factsheet_cards(text)
    if doc_type == "ter":
        return ter_cards(text)
    return []
