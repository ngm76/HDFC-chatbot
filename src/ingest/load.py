"""Load the official pages listed in data/sources.csv (Phases 2 and 13).

Fetches role=ingest rows only: the official HDFC MF, SEBI and AMFI / Mutual Funds
Sahi Hai corpus (PRD §4). role=help rows (the two Groww help links, Addendum A5) are
links only and are never fetched. Handles HTML, PDF and the TER .xlsx workbook.

A copy of every page that loads cleanly is kept in data/raw/. If a later fetch fails
or comes back unusable, that last good copy is used instead and reported (PRD §8).
No chunking or embeddings here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.ingest.groww import is_groww_url

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = PROJECT_ROOT / "data" / "sources.csv"
RAW_CACHE_DIR = PROJECT_ROOT / "data" / "raw"

# The PRD §4 allowlist: only these publishers can be ingested or cited. Subdomains
# count (files.hdfcfund.com, investor.sebi.gov.in). groww.in is not here: Groww is
# only the two help links (role=help), which are never fetched.
ALLOWED_HOST_SUFFIXES = (
    "hdfcfund.com",
    "sebi.gov.in",
    "amfiindia.com",
    "mutualfundssahihai.com",
)

BLOCKED_HOST_SUFFIXES: tuple[str, ...] = ()

# files.hdfcfund.com rejects UAs containing "bot" or "python-httpx" (403), so a
# generic browser-like UA is used. Fetch volume is tiny and cached under data/raw/.
USER_AGENT = "Mozilla/5.0 facts-only-research-prototype"
FETCH_TIMEOUT = 30.0
MIN_TEXT_CHARS = 40


@dataclass(frozen=True)
class Document:
    text: str
    url: str
    scheme: str
    doc_type: str
    fetched_at: str


@dataclass
class LoadError:
    url: str
    message: str


@dataclass
class LoadResult:
    documents: list[Document] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)
    # Pages served from their last good copy because the fresh fetch failed.
    stale: list[LoadError] = field(default_factory=list)
    skipped_seeds: int = 0
    skipped_disallowed: int = 0


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if any(host == b or host.endswith("." + b) for b in BLOCKED_HOST_SUFFIXES):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return RAW_CACHE_DIR / digest


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _html_to_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "footer", "header", "aside"]):
        tag.decompose()
    root = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    return _normalize_text(root.get_text("\n", strip=True))


# --- Groww scheme pages -------------------------------------------------------
# Groww's HTML has no <main>/<nav> markup to strip, so the page text is trimmed by
# its section labels instead. Kept: every fact on the page (fund fields, holdings,
# glossary, fund managers and the other schemes they manage, fund house, registrar).
# Dropped: site menus and the footer link farm, and what the problem statement
# rules out: returns / return calculator / rankings / "compare similar funds"
# ("No performance claims") and Groww's star rating (an opinion).
GROWW_KEEP_FROM = ("Holdings (", "Minimum investments", "Understand terms", "Exit Load",
                   "Exit load, stamp duty and tax", "Fund management", "About", "Fund house")
GROWW_DROP_FROM = ("Return calculator", "Returns and rankings", "Check past data",
                   "Compare similar funds")
GROWW_DROP_LINES = ("See All", "View details", "Compare")
# Groww's auto-generated "About" sentence reports the AMC's total AUM as the fund's
# AUM and names a single fund manager, so it contradicts the page's own fields.
GROWW_TEMPLATE_RE = re.compile(r"^HDFC .+ is a .+ Scheme launched by .+AUM", re.I)


def _clean_groww(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    start = next((i for i, l in enumerate(lines) if l.startswith("NAV:")), 0)
    end = next(
        (i for i, l in enumerate(lines)
         if i > start and l == "Home" and i + 1 < len(lines) and lines[i + 1] == ">"),
        len(lines),
    )
    kept: list[str] = []
    keeping = True
    skip_next = False
    for line in lines[start:end]:
        if skip_next:
            skip_next = False
            continue
        if line.startswith(GROWW_KEEP_FROM):
            keeping = True
        elif line.startswith(GROWW_DROP_FROM):
            keeping = False
        if not keeping:
            continue
        if line == "Rating":  # Groww's own star rating: an opinion, not a fact
            skip_next = True
            continue
        if line in GROWW_DROP_LINES or GROWW_TEMPLATE_RE.match(line):
            continue
        if re.fullmatch(r"[A-Z]{2,3}", line):  # fund-manager avatar initials ("DM", "CS")
            continue
        kept.append(line)
    return "\n".join(kept)


# --- HDFC MF scheme pages ------------------------------------------------------
# hdfcfund.com/explore/mutual-funds/<scheme>/direct. Kept: the fact panel (riskometer,
# min SIP, TER, lock-in, AUM, benchmark), fund managers, exit load and the factual
# FAQ answers. Dropped: what the PRD rules out. That is returns ("Returns since
# inception", "NAV and Historical Performance"), suitability and opinion content
# ("Product Suitability", FAQs like "Is this suitable for retirement planning?"),
# plus marketing and button text. NAV and holdings are rendered by JavaScript
# ("NA" in the HTML), so those come from the factsheet.
HDFC_SCHEME_PATH = "/explore/mutual-funds/"
HDFC_DROP_SECTIONS = (  # (first line, line that ends the dropped block)
    ("NAV and Historical Performance", "Fund Managers"),
    ("Downloads", "Exit Load"),
    ("Product Suitability", "FAQs"),
    ("Ideal for", "Entry Load"),  # "Wealth Creation / 3 Years and above": suitability
)
HDFC_DROP_LINES = ("INVEST NOW", "Read More", "Click here", "Graph", "Table",
                   "to view the Total Expense Ratio")
HDFC_DROP_LINE_RE = re.compile(
    r"performing scheme|view performance of other schemes|Past performance|^Since inception",
    re.I,
)
# Intro blocks that pitch the fund ("Who can consider ...?", "Why invest in ...?") run
# until the next question heading or the "How to start investing" steps.
HDFC_ADVICE_BLOCK_RE = re.compile(r"^(Who can consider|Who should consider|Why invest)", re.I)
HDFC_BLOCK_END_RE = re.compile(r"\?$|^How to start investing", re.I)
# FAQ questions that ask for a fact. All others (suitability, "which is better",
# "is this risky", horizons, portfolio role) are advice and are dropped.
HDFC_FACT_FAQ_RE = re.compile(
    r"minimum|benchmark|exit load|lock[- ]?in|expense|\bTER\b|riskometer|statement"
    r"|^(\d+\.\s*)?(what is HDFC|how to (invest|redeem)|can i invest)|different from",
    re.I,
)


def is_hdfc_scheme_page(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host == "hdfcfund.com" and parsed.path.startswith(HDFC_SCHEME_PATH)


def _clean_hdfc_scheme(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # "Returns" / "since inception" / "13.18%": the since-inception return
        if line == "Returns" and i + 1 < len(lines) and lines[i + 1] == "since inception":
            i += 3
            continue
        if HDFC_ADVICE_BLOCK_RE.match(line):
            i = next((j for j in range(i + 1, len(lines))
                      if HDFC_BLOCK_END_RE.search(lines[j])
                      and not HDFC_ADVICE_BLOCK_RE.match(lines[j])), len(lines))
            continue
        end = next((e for start, e in HDFC_DROP_SECTIONS if line == start), None)
        if end:
            i = next((j for j in range(i + 1, len(lines)) if lines[j] == end), len(lines))
            continue
        if line == "FAQs":
            kept.append(line)
            kept.extend(_factual_faqs(lines[i + 1:]))
            break
        if line not in HDFC_DROP_LINES and not HDFC_DROP_LINE_RE.search(line):
            kept.append(line)
        i += 1
    return "\n".join(kept)


def _factual_faqs(lines: list[str]) -> list[str]:
    """Keep question/answer pairs whose question asks for a fact."""
    kept: list[str] = []
    keep = False
    for line in lines:
        if line.endswith("?"):
            keep = bool(HDFC_FACT_FAQ_RE.search(line))
        if keep and not HDFC_DROP_LINE_RE.search(line):
            kept.append(line)
    return kept


# --- PDFs ----------------------------------------------------------------------
def _is_garbled(line: str) -> bool:
    """Mojibake from non-Unicode fonts (e.g. the Hindi header on SEBI circulars):
    mostly Latin-1 supplement characters."""
    chars = line.replace(" ", "")
    if len(chars) < 4:
        return False
    odd = sum(1 for ch in chars if "\x80" <= ch <= "\xff")
    return odd / len(chars) >= 0.3


def _pdf_to_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    pages = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        pages.append("\n".join(l for l in page_text.splitlines() if not _is_garbled(l)))
    return _normalize_text("\n\n".join(pages))


# --- Spreadsheets (TER disclosure) ---------------------------------------------
# HDFC's TER file is named .xls but is an Office Open XML (.xlsx) workbook. It is
# read with the standard library (zipfile + the sheet XML), so no extra dependency:
# one line per row, cells joined by " | ".
_XLSX_CELL_RE = re.compile(r'<c ([^>]*?)(?:/>|>(?:<v>(.*?)</v>)?)', re.S)


def _looks_like_xlsx(payload: bytes) -> bool:
    if payload[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(BytesIO(payload)) as book:
            return "xl/workbook.xml" in book.namelist()
    except zipfile.BadZipFile:
        return False


def _xlsx_to_text(payload: bytes) -> str:
    with zipfile.ZipFile(BytesIO(payload)) as book:
        names = book.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            xml = book.read("xl/sharedStrings.xml").decode("utf-8")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", si))
                      for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]
        sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        lines: list[str] = []
        for sheet in sheets:
            xml = book.read(sheet).decode("utf-8")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
                cells = []
                for attrs, value in _XLSX_CELL_RE.findall(row):
                    if 't="s"' in attrs and value:
                        value = shared[int(value)]
                    cells.append(" ".join(html.unescape(value or "").split()))
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def _looks_like_pdf(payload: bytes, content_type: str) -> bool:
    if payload[:5] == b"%PDF-":
        return True
    return "application/pdf" in content_type.lower()


def _looks_like_html(payload: bytes, content_type: str) -> bool:
    ct = content_type.lower()
    if "text/html" in ct or "application/xhtml" in ct:
        return True
    snippet = payload[:512].lstrip().lower()
    return snippet.startswith(b"<!doctype html") or snippet.startswith(b"<html")


def extract_text(payload: bytes, content_type: str) -> str:
    if _looks_like_pdf(payload, content_type):
        return _pdf_to_text(payload)
    if _looks_like_xlsx(payload):
        return _xlsx_to_text(payload)
    if _looks_like_html(payload, content_type):
        return _html_to_text(payload)
    raise ValueError(f"unsupported content type: {content_type or 'unknown'}")


def _read_cache(url: str) -> bytes | None:
    path = _cache_path(url)
    if path.is_file() and path.stat().st_size > 0:
        return path.read_bytes()
    return None


def _cached_on(url: str) -> str:
    """Date the cached copy was fetched, so fetched_at is not reset by cache hits."""
    mtime = _cache_path(url).stat().st_mtime
    return date.fromtimestamp(mtime).isoformat()


def _write_cache(url: str, payload: bytes, content_type: str) -> None:
    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    path.write_bytes(payload)
    path.with_suffix(".meta").write_text(
        f"url={url}\ncontent_type={content_type}\n", encoding="utf-8"
    )


def fetch_url(
    url: str,
    *,
    client: httpx.Client,
    use_cache: bool = True,
) -> tuple[bytes, str, str]:
    """Return (payload, content_type, fetched_at ISO date).

    With use_cache, a cached copy is returned without fetching. Fresh downloads are
    not cached here: load_corpus caches a page only once its text checks out, so the
    cache always holds the last good copy."""
    if use_cache:
        cached = cached_copy(url)
        if cached is not None:
            return cached

    response = client.get(url, follow_redirects=True)
    final_url = str(response.url)
    if not _host_allowed(final_url):
        raise PermissionError(f"redirected to disallowed host: {final_url}")
    response.raise_for_status()
    payload = response.content
    content_type = response.headers.get("content-type", "")
    return payload, content_type, date.today().isoformat()


def cached_copy(url: str) -> tuple[bytes, str, str] | None:
    """The last good copy of url as (payload, content_type, fetched_at), if any."""
    cached = _read_cache(url)
    if cached is None:
        return None
    meta = _cache_path(url).with_suffix(".meta")
    content_type = ""
    if meta.is_file():
        for line in meta.read_text(encoding="utf-8").splitlines():
            if line.startswith("content_type="):
                content_type = line.split("=", 1)[1]
    return cached, content_type, _cached_on(url)


def _page_text(url: str, payload: bytes, content_type: str) -> str:
    """Extract and clean a page's text; raise if it is unusable."""
    if not payload:
        raise ValueError("empty response body")
    text = extract_text(payload, content_type)
    if is_hdfc_scheme_page(url):
        text = _clean_hdfc_scheme(text)
    elif is_groww_url(url):  # MVP corpus only; groww.in is no longer on the allowlist
        text = _clean_groww(text)
    if len(text) < MIN_TEXT_CHARS:
        raise ValueError(f"extracted text too short ({len(text)} chars); not indexing")
    return text


def _iter_ingest_rows(sources_csv: Path) -> tuple[list[dict[str, str]], int]:
    ingest: list[dict[str, str]] = []
    skipped_seeds = 0
    with sources_csv.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            role = (row.get("role") or "").strip().lower()
            url = (row.get("url") or "").strip()
            if role == "seed":
                skipped_seeds += 1
                continue
            if role != "ingest":
                continue
            if not url:
                continue
            ingest.append(row)
    return ingest, skipped_seeds


def load_corpus(
    sources_csv: str | Path | None = None,
    *,
    use_cache: bool = True,
    limit: int | None = None,
) -> LoadResult:
    """Load ingest URLs. Failures are collected; empty bodies are skipped."""
    path = Path(sources_csv) if sources_csv else DEFAULT_SOURCES
    result = LoadResult()
    rows, result.skipped_seeds = _iter_ingest_rows(path)
    if limit is not None:
        rows = rows[:limit]

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    with httpx.Client(headers=headers, timeout=FETCH_TIMEOUT) as client:
        for row in rows:
            url = (row.get("url") or "").strip()
            scheme = (row.get("scheme") or "").strip()
            doc_type = (row.get("doc_type") or "").strip()
            if not _host_allowed(url):
                result.skipped_disallowed += 1
                result.errors.append(
                    LoadError(url, "host not on the source allowlist")
                )
                logger.warning("skip disallowed host: %s", url)
                continue
            from_cache = use_cache and _read_cache(url) is not None
            try:
                payload, content_type, fetched_at = fetch_url(
                    url, client=client, use_cache=use_cache
                )
                text = _page_text(url, payload, content_type)
                if not from_cache:  # a fresh download that checks out: the new last good copy
                    _write_cache(url, payload, content_type)
            except Exception as exc:  # noqa: BLE001 — collect per-URL failures
                message = f"{type(exc).__name__}: {exc}"
                fallback = _last_good(url)
                if fallback is None:
                    result.errors.append(LoadError(url, message))
                    logger.warning("failed %s: %s", url, message)
                    continue
                text, fetched_at = fallback
                result.stale.append(
                    LoadError(url, f"{message}; using last good copy from {fetched_at}")
                )
                logger.warning("failed %s: %s; using last good copy from %s",
                               url, message, fetched_at)
            result.documents.append(
                Document(
                    text=text,
                    url=url,
                    scheme=scheme,
                    doc_type=doc_type,
                    fetched_at=fetched_at,
                )
            )

    return result


def _last_good(url: str) -> tuple[str, str] | None:
    """(text, fetched_at) from the cached last good copy, or None."""
    cached = cached_copy(url)
    if cached is None:
        return None
    payload, content_type, fetched_at = cached
    try:
        return _page_text(url, payload, content_type), fetched_at
    except Exception:  # noqa: BLE001 — an unusable cache is the same as none
        return None


def load_documents(
    sources_csv: str | Path | None = None,
    *,
    use_cache: bool = True,
    limit: int | None = None,
) -> list[Document]:
    return load_corpus(sources_csv, use_cache=use_cache, limit=limit).documents


def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Loader (role=ingest URLs only)")
    parser.add_argument(
        "--sources",
        type=Path,
        default=DEFAULT_SOURCES,
        help="Path to sources.csv",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max ingest URLs to fetch (default 1 for a smoke test)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch every ingest row (ignores --limit)",
    )
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    limit = None if args.all else args.limit
    result = load_corpus(args.sources, use_cache=not args.no_cache, limit=limit)
    print(f"skipped_seeds={result.skipped_seeds}")
    print(f"skipped_disallowed={result.skipped_disallowed}")
    print(f"ok={len(result.documents)} stale={len(result.stale)} errors={len(result.errors)}")
    for doc in result.documents:
        print(f"OK {doc.url} chars={len(doc.text)} scheme={doc.scheme!r}")
    for err in result.stale:
        print(f"STALE {err.url} :: {err.message}")
    for err in result.errors:
        print(f"ERR {err.url} :: {err.message}")
    if not result.documents:
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
