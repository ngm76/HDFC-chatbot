"""Phase 2: load the public pages listed in data/sources.csv.

Fetches role=ingest only: the five Groww scheme pages named in
docs/problemstatement.txt. role=reference rows (AMFI education page, HDFC
factsheet) are refusal links only and are never fetched. No chunking or embeddings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
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

# groww.in: the corpus named in the problem statement (robots.txt allows the
# /mutual-funds/<scheme> pages). The official hosts stay allowed for reference rows.
ALLOWED_HOST_SUFFIXES = (
    "groww.in",
    "hdfcfund.com",
    "amfiindia.com",
    "sebi.gov.in",
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


def _pdf_to_text(payload: bytes) -> str:
    from io import BytesIO

    reader = PdfReader(BytesIO(payload))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return _normalize_text("\n\n".join(pages))


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
    """Return (payload, content_type, fetched_at ISO date)."""
    if use_cache:
        cached = _read_cache(url)
        if cached is not None:
            meta = _cache_path(url).with_suffix(".meta")
            content_type = ""
            if meta.is_file():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if line.startswith("content_type="):
                        content_type = line.split("=", 1)[1]
            return cached, content_type, _cached_on(url)

    response = client.get(url, follow_redirects=True)
    final_url = str(response.url)
    if not _host_allowed(final_url):
        raise PermissionError(f"redirected to disallowed host: {final_url}")
    response.raise_for_status()
    payload = response.content
    content_type = response.headers.get("content-type", "")
    if use_cache:
        _write_cache(url, payload, content_type)
    return payload, content_type, date.today().isoformat()


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
            try:
                payload, content_type, fetched_at = fetch_url(
                    url, client=client, use_cache=use_cache
                )
                if not payload:
                    raise ValueError("empty response body")
                text = extract_text(payload, content_type)
                if is_groww_url(url):
                    text = _clean_groww(text)
                if len(text) < MIN_TEXT_CHARS:
                    raise ValueError(
                        f"extracted text too short ({len(text)} chars); not indexing"
                    )
                result.documents.append(
                    Document(
                        text=text,
                        url=url,
                        scheme=scheme,
                        doc_type=doc_type,
                        fetched_at=fetched_at,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — collect per-URL failures
                message = f"{type(exc).__name__}: {exc}"
                result.errors.append(LoadError(url, message))
                logger.warning("failed %s: %s", url, message)

    return result


def load_documents(
    sources_csv: str | Path | None = None,
    *,
    use_cache: bool = True,
    limit: int | None = None,
) -> list[Document]:
    return load_corpus(sources_csv, use_cache=use_cache, limit=limit).documents


def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Phase 2 loader (ingest URLs only)")
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
    print(f"ok={len(result.documents)} errors={len(result.errors)}")
    for doc in result.documents:
        print(f"OK {doc.url} chars={len(doc.text)} scheme={doc.scheme!r}")
    for err in result.errors:
        print(f"ERR {err.url} :: {err.message}")
    if not result.documents:
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
