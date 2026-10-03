"""Link health and new-edition check for data/sources.csv (Phase 18, PRD §8, §11).

1. Fetches every URL in data/sources.csv (ingest, reference and help rows) and
   reports any 4xx/5xx or network error. Exit code 1 if any link is broken.
2. Dated documents change URL with each edition (factsheet monthly, TER file
   monthly, KIMs when revised). Their HDFC MF hub pages list the current files, so
   each hub is scanned and a newer edition than the one in sources.csv is reported
   as a warning (update the row; see the monthly checklist in README.md).

Runs daily in .github/workflows/refresh-data.yml (annotations show in the Actions
log). Run locally from the project root:  python scripts/check_links.py
"""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_CSV = PROJECT_ROOT / "data" / "sources.csv"
USER_AGENT = "Mozilla/5.0 facts-only-research-prototype"  # same as the loader
TIMEOUT = 30.0
IN_ACTIONS = bool(os.getenv("GITHUB_ACTIONS"))

FILES = r"https://files\.hdfcfund\.com/s3fs-public/"
HUBS = {
    "ter": ("https://www.hdfcfund.com/statutory-disclosure/total-expense-ratio-of-mutual-fund-schemes/reports",
            re.compile(FILES + r"ter/HDFCMF_SCHEMES_TER_[\d-]+\.xlsx?")),
    "factsheet": ("https://www.hdfcfund.com/mutual-funds/factsheets",
                  re.compile(FILES + r"[^\"'\s<>]*?HDFC%20MF%20Factsheet%20-%20[A-Za-z]+%20\d{4}[^\"'\s<>]*?\.pdf")),
    "kim": ("https://www.hdfcfund.com/mutual-funds/fund-documents/kim",
            re.compile(FILES + r"KIM/[^\"'\s<>]+?\.pdf")),
}
# How each scheme appears in KIM file names.
KIM_NAMES = {
    "HDFC Large Cap Fund Direct Growth": r"KIM - HDFC Large Cap Fund dated",
    "HDFC Flexi Cap Fund Direct Growth": r"KIM - HDFC Flexi Cap Fund dated",
    "HDFC ELSS Tax Saver Fund Direct Growth": r"KIM - HDFC ELSS Tax Saver dated",
    "HDFC Small Cap Fund Direct Growth": r"KIM - HDFC Small Cap Fund dated",
    "HDFC Balanced Advantage Fund Direct Growth": r"KIM - HDFC Balanced Advantage Fund dated",
}
_DATED_RE = re.compile(r"dated\s+(\w+)\s+(\d{1,2}),\s*(\d{4})", re.I)
_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}


def _say(level: str, message: str) -> None:
    print(f"::{level}::{message}" if IN_ACTIONS else f"{level.upper():8} {message}")


def _edition_key(url: str) -> tuple[int, int, int]:
    """Sortable (year, month, day) from a file name: TER dd-mm-yyyy, KIM 'dated
    Month d, yyyy', factsheet 'Month yyyy'."""
    name = unquote(url)
    m = re.search(r"TER_(\d{2})-(\d{2})-(\d{4})", name)
    if m:
        return int(m.group(3)), int(m.group(2)), int(m.group(1))
    m = _DATED_RE.search(name)
    if m:
        return int(m.group(3)), _MONTHS.get(m.group(1).lower(), 0), int(m.group(2))
    m = re.search(r"Factsheet - ([A-Za-z]+) (\d{4})", name)
    if m:
        return int(m.group(2)), _MONTHS.get(m.group(1).lower(), 0), 0
    return (0, 0, 0)


def check_links(client: httpx.Client, rows: list[dict[str, str]]) -> int:
    broken = 0
    for row in rows:
        url = row["url"]
        try:
            with client.stream("GET", url) as response:
                status = response.status_code
        except httpx.HTTPError as exc:
            broken += 1
            _say("error", f"unreachable ({type(exc).__name__}): {url}")
            continue
        if status >= 400:
            broken += 1
            _say("error", f"HTTP {status}: {url}")
        else:
            print(f"ok {status}  {url}")
    return broken


def newer_editions(client: httpx.Client, rows: list[dict[str, str]]) -> int:
    found = 0
    for doc_type, (hub, pattern) in HUBS.items():
        try:
            listed = set(pattern.findall(client.get(hub).text))
        except httpx.HTTPError as exc:
            _say("warning", f"could not read the {doc_type} hub page ({type(exc).__name__}): {hub}")
            continue
        for row in (r for r in rows if r["doc_type"] == doc_type and r["role"] == "ingest"):
            candidates = listed
            if doc_type == "kim":
                name = KIM_NAMES.get(row["scheme"], "")
                candidates = {u for u in listed if re.search(name, unquote(u), re.I)}
            if doc_type == "factsheet":
                candidates = {u for u in listed if "Index" not in unquote(u)}
            newest = max(candidates, key=_edition_key, default=None)
            if newest and _edition_key(newest) > _edition_key(row["url"]):
                found += 1
                _say("warning", f"newer edition of '{row.get('label') or row['url']}' is listed: "
                                f"{newest} (update data/sources.csv)")
    return found


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with SOURCES_CSV.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("url") or "").strip()]
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        broken = check_links(client, rows)
        newer = newer_editions(client, rows)
    print(f"\n{len(rows)} links checked: {broken} broken; {newer} newer edition(s) listed")
    raise SystemExit(1 if broken else 0)


if __name__ == "__main__":
    main()
