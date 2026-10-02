"""Phase 3: split loaded documents into retrieval chunks (architecture §5).

Groww scheme pages (the current corpus) are structured label/value pages, so
they are chunked by field into self-contained fact cards (src/ingest/groww.py);
the problem statement asks for a chunking strategy chosen from the data.

Any other document uses the generic path below: heading-aware recursive character split. Loaded text is plain (HTML get_text /
PDF extract_text), so headings are detected per line: markdown-style `#`,
ALL-CAPS labels, HDFC scheme-name lines, and FAQ field labels (exit load,
expense ratio, SIP, ...). Sections are then packed into chunks of
MIN_CHARS..MAX_CHARS; oversized sections are split recursively with overlap.
Fee/SIP/load sections are kept whole when they fit; if not, they are split by
row groups with the header lines repeated. No embeddings or storage here.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass

from src.ingest.groww import fact_cards, is_groww_url
from src.ingest.load import Document
from src.schemes import SHARED_SCHEME, detect_schemes

# ~400–800 tokens, using ~4 chars/token as the proxy.
MIN_CHARS = 1600
MAX_CHARS = 3200
OVERLAP_CHARS = 380  # ~12% of MAX_CHARS (architecture: 10–15%)
MIN_TAIL_CHARS = 200

SEPARATORS = ("\n## ", "\n# ", "\n\n", "\n", ". ", " ")

AMC = "HDFC"

# Section titles whose content is usually a fee / SIP / load table.
TABLE_TITLE_RE = re.compile(
    r"expense ratio|\bTER\b|exit load|load structure|entry load|\bSIP\b|"
    r"systematic investment|minimum (application|investment|amount|purchase)|"
    r"lock[- ]in|riskometer|benchmark",
    re.IGNORECASE,
)

# Field labels that start a new section even when not in caps.
FIELD_LABEL_RE = re.compile(
    r"^(expense ratio|total expense ratio|exit load|entry load|load structure|"
    r"minimum application amount|minimum investment|minimum additional purchase|"
    r"sip|min\.?\s*sip|systematic investment plan|lock[- ]?in( period)?|riskometer|"
    r"benchmark( index)?|fund managers?|investment objective|asset allocation|"
    r"plans?\s*(/|and)\s*options?|scheme features|faqs?|"
    r"frequently asked questions|aum|nav|ter|inception date|assets under management|"
    # Groww scheme-page labels
    r"nav:\s*\d{1,2} \w{3} '\d{2}|min\.? for (sip|1st investment|2nd investment)|"
    r"fund size( \(aum\))?|expense ratio|minimum investments|exit load, stamp duty and tax|"
    r"stamp duty on investment|tax implication|fund management|about|fund benchmark|"
    r"fund house|registrar & transfer agent)\s*:?\s*$",
    re.IGNORECASE,
)

# Single-fact fields. On field-heavy pages (factsheet, scheme pages) each gets its
# own chunk instead of being merged with neighbours, so a question like "fund size"
# matches a chunk that is only about AUM (docs/eval_notes.md, AUM/NAV gold rows).
FIELD_CHUNK_RE = re.compile(
    r"^(assets under management|aum|nav|net asset value|(total )?expense ratio|ter|"
    r"exit load|entry load|benchmark|riskometer|min\.?\s*sip|minimum (application|sip|investment)|"
    r"lock[- ]?in|fund managers?|fund management|date of allotment|inception date|"
    r"min\.? for|fund size|fund benchmark|stamp duty|tax implication|registrar)\b",
    re.IGNORECASE,
)
FIELD_DOC_TYPES = ("factsheet", "faq")
# Factsheet field headings can carry a footnote marker ("FUND MANAGER ¥") whose
# text sits at the foot of the same fund page ("¥ Fund Manager for Overseas
# Investments: Mr. Dhruv Muchhal …"). It is attached to the field chunk. The €
# (AUM) footnote is left out: its PDF text is garbled and it holds a second rupee
# figure that could be mistaken for the fund size.
FOOTNOTE_MARKERS = ("¥",)
MAX_FOOTNOTE_CHARS = 300
TINY_FIELD_CHARS = 60  # a field section this short (e.g. "NAV (As On …)") joins the next
MIN_LONE_LINE_CHARS = 40  # a one-line piece shorter than this is just a heading

# A fund-name line such as "HDFC Children's Fund" or "HDFC NIFTY 50 ETF". Holdings
# lines ("HDFC Large Cap Fund - Direct Plan - Growth Option") are not names.
SCHEME_LINE_RE = re.compile(
    r"^HDFC [\w&'’.\-\s]+?\b(Fund|ETF|FOF)\b[\w()&'’\-\s]*$(?<!Option)",
)
_HOLDING_LINE_RE = re.compile(r"\b(direct|regular)\s+plan\b|\bgrowth\s+option\b|\bidcw\b", re.I)
# Each factsheet fund page starts: fund name → description → CATEGORY OF SCHEME.
_FUND_PAGE_START_RE = re.compile(r"^category of scheme$", re.I)
PARENT_SEP = " > "


def _is_scheme_line(line: str) -> bool:
    s = line.strip()
    return bool(SCHEME_LINE_RE.match(s)) and not _HOLDING_LINE_RE.search(s)

MAX_HEADING_CHARS = 80


@dataclass(frozen=True)
class Chunk:
    text: str
    chunk_id: str
    url: str
    scheme: str
    doc_type: str
    section_title: str
    fetched_at: str
    amc: str = AMC
    field: str = ""  # fact-card field for Groww pages (e.g. "expense_ratio"); "" otherwise

    def metadata(self) -> dict[str, str]:
        meta = asdict(self)
        del meta["text"]
        return meta


@dataclass
class _Section:
    title: str
    start: int  # offset of the heading line (or 0) in the document text
    end: int


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > MAX_HEADING_CHARS:
        return False
    if s.startswith("#"):
        return True
    if s.endswith((".", ",", ";")):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 3:
        return False
    if FIELD_LABEL_RE.match(s):
        return True
    if _is_scheme_line(s):
        return True
    # ALL-CAPS label, e.g. "KEY INFORMATION MEMORANDUM", "LOAD STRUCTURE".
    words = re.findall(r"[A-Za-z]+", s)
    return len(words) >= 2 and all(c.isupper() for c in letters)


def _clean_title(line: str) -> str:
    return line.strip().lstrip("#").strip().rstrip(":").strip()


def _sections(text: str) -> list[_Section]:
    """Split at heading lines. Titles carry the most recent scheme-name heading as
    a parent ("HDFC Large Cap Fund > EXPENSE RATIO"): the factsheet repeats the
    same sub-headings for every fund, so the sub-heading alone is ambiguous."""
    sections: list[_Section] = []
    title = ""
    parent = ""
    start = 0
    offset = 0
    after_name = False  # previous heading was a fund name
    prev = ""  # previous non-blank line
    for line in text.splitlines(keepends=True):
        # Holdings tables split their "% to NAV" column header over two lines; that
        # bare "NAV" is a column header, not the NAV field.
        continues_header = line.strip().upper() == "NAV" and prev.endswith(" to")
        if line.strip():
            prev = line.strip()
        if _is_heading(line) and not continues_header:
            heading = _clean_title(line)
            if _is_scheme_line(line):
                parent, after_name = heading, True
                heading_is_name = True
            else:
                if _FUND_PAGE_START_RE.match(heading) and not after_name:
                    parent = ""  # new fund page whose name we did not recognise
                after_name = False
                heading_is_name = False
            if parent and not heading_is_name:
                heading = f"{parent}{PARENT_SEP}{heading}"
            if offset > start:
                sections.append(_Section(title, start, offset))
                start = offset
            title = heading
        offset += len(line)
    sections.append(_Section(title, start, len(text)))
    return [s for s in sections if text[s.start : s.end].strip()]


def _split_span(
    text: str, start: int, end: int, seps: tuple[str, ...], limit: int
) -> list[tuple[int, int]]:
    """Recursively split text[start:end] into disjoint spans of at most `limit`."""
    if end - start <= limit:
        return [(start, end)]
    sep = next((s for s in seps if s in text[start:end]), None)
    if sep is None:
        return [(i, min(i + limit, end)) for i in range(start, end, limit)]
    rest = seps[seps.index(sep) + 1 :]

    # Newline-led separators ("\n## ") cut before the heading so it stays with its
    # body; ". " and " " cut after, so the sentence keeps its full stop.
    lead = 1 if sep.startswith("\n") else len(sep)
    pieces: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        hit = text.find(sep, pos + 1, end)
        cut = end if hit == -1 else hit + lead
        pieces.append((pos, cut))
        pos = cut

    spans: list[tuple[int, int]] = []
    cur_start = cur_end = start
    for p_start, p_end in pieces:
        if p_end - p_start > limit:
            if cur_end > cur_start:
                spans.append((cur_start, cur_end))
            spans.extend(_split_span(text, p_start, p_end, rest, limit))
            cur_start = cur_end = p_end
        elif p_end - cur_start > limit:
            spans.append((cur_start, cur_end))
            cur_start, cur_end = p_start, p_end
        else:
            cur_end = p_end
    if cur_end > cur_start:
        spans.append((cur_start, cur_end))
    return spans


def _split_with_overlap(text: str, sec: _Section) -> list[tuple[int, str]]:
    """Recursive split; each piece after the first repeats ~OVERLAP_CHARS of the
    previous one (snapped to a word). Returns (id offset, text) — the id offset is
    the un-overlapped start, so ids stay unique and stable."""
    spans = _split_span(text, sec.start, sec.end, SEPARATORS, MAX_CHARS - OVERLAP_CHARS)
    out = [(spans[0][0], text[spans[0][0] : spans[0][1]])]
    for s, e in spans[1:]:
        back = max(sec.start, s - OVERLAP_CHARS)
        space = text.find(" ", back, s)
        out.append((s, text[space + 1 if space != -1 else back : e]))
    return out


def _split_table(text: str, sec: _Section) -> list[tuple[int, str]] | None:
    """Split an oversized table section by row groups, repeating the heading and
    column-header lines on each continuation. None if it does not look tabular."""
    lines = text[sec.start : sec.end].splitlines(keepends=True)
    header = "".join(lines[:2])  # heading line + column header row
    if len(lines) < 3 or len(header) > MAX_CHARS // 4:
        return None
    if any(len(line) > MAX_CHARS // 2 for line in lines):
        return None  # prose, not rows

    groups: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    cur_start = offset = sec.start
    for line in lines:
        budget = MAX_CHARS - (len(header) if groups else 0)
        if cur and sum(map(len, cur)) + len(line) > budget:
            groups.append((cur_start, cur))
            cur, cur_start = [], offset
        cur.append(line)
        offset += len(line)
    if cur:
        groups.append((cur_start, cur))
    return [(s, (header if i else "") + "".join(g)) for i, (s, g) in enumerate(groups)]


def _chunk_id(url: str, key: int | str) -> str:
    """Stable id: hash of url + start offset (generic chunks) or field (fact cards)."""
    return hashlib.sha1(f"{url}#{key}".encode("utf-8")).hexdigest()[:16]


def _groww_chunks(doc: Document) -> list[Chunk]:
    fund = doc.scheme
    return [
        Chunk(
            text=card.text,
            chunk_id=_chunk_id(doc.url, f"{card.field}:{card.label}"),
            url=doc.url,
            scheme=doc.scheme,
            doc_type=doc.doc_type,
            section_title=f"{fund.removesuffix(' Direct Growth')}{PARENT_SEP}{card.label}",
            fetched_at=doc.fetched_at,
            field=card.field,
        )
        for card in fact_cards(doc.text, fund)
    ]


def chunk_document(doc: Document) -> list[Chunk]:
    if is_groww_url(doc.url):
        return _groww_chunks(doc)
    text = doc.text
    pieces: list[tuple[int, str, str]] = []  # (start offset, text, section_title)

    pending: list[_Section] = []

    def flush() -> None:
        if pending:
            start, end = pending[0].start, pending[-1].end
            pieces.append((start, text[start:end], pending[0].title))
            pending.clear()

    isolate_fields = doc.doc_type in FIELD_DOC_TYPES
    sections = _sections(text)
    if isolate_fields:
        sections = _join_tiny_fields(text, sections)

    for i, sec in enumerate(sections):
        if isolate_fields and _is_field(sec.title) and sec.end - sec.start <= MAX_CHARS:
            flush()  # a single-fact field is its own chunk, never merged
            body = text[sec.start : sec.end] + _footnote(text, sections, i)
            pieces.append((sec.start, body, _field_title(sec.title, doc)))
            continue
        if sec.end - sec.start > MAX_CHARS:
            if pending and sec.start - pending[0].start < MIN_CHARS:
                # A short heading run (e.g. "Benchmark") belongs with the section
                # it introduces, not in a chunk of its own.
                sec = _Section(pending[0].title or sec.title, pending[0].start, sec.end)
                pending.clear()
            flush()
            is_table = bool(TABLE_TITLE_RE.search(sec.title))
            split = (_split_table(text, sec) if is_table else None) or _split_with_overlap(
                text, sec
            )
            pieces.extend((start, body, sec.title) for start, body in split)
            continue
        if pending and sec.end - pending[0].start > MAX_CHARS:
            flush()
        pending.append(sec)
        if sec.end - pending[0].start >= MIN_CHARS:
            flush()
    flush()

    # A tiny tail (e.g. "BACK TO TOP") is appended to the previous chunk.
    if len(pieces) > 1 and len(pieces[-1][1].strip()) < MIN_TAIL_CHARS:
        start, body, title = pieces[-2]
        pieces[-2:] = [(start, body.rstrip() + "\n" + pieces[-1][1].strip(), title)]

    return [
        Chunk(
            text=_with_title(body.strip(), title),
            chunk_id=_chunk_id(doc.url, start),
            url=doc.url,
            scheme=_chunk_scheme(doc, title),
            doc_type=doc.doc_type,
            section_title=title,
            fetched_at=doc.fetched_at,
        )
        for start, body, title in pieces
        if _has_content(body)
    ]


def _has_content(body: str) -> bool:
    """False for empty pieces and lone headings (e.g. Groww's "Minimum investments"
    label when its fields became their own chunks)."""
    text = body.strip()
    return bool(text) and ("\n" in text or len(text) >= MIN_LONE_LINE_CHARS)


def _leaf(title: str) -> str:
    return title.split(PARENT_SEP)[-1].strip()


def _is_field(title: str) -> bool:
    return bool(FIELD_CHUNK_RE.match(_leaf(title)))


def _join_tiny_fields(text: str, sections: list[_Section]) -> list[_Section]:
    """A near-empty field section joins the next section when both name the same
    field, e.g. the factsheet's "NAV (As On AUGUST 31, 2026)" + "NAV PER UNIT …",
    or the scheme page's "TER" label followed by a second "TER" heading."""
    out: list[_Section] = []
    i = 0
    while i < len(sections):
        sec = sections[i]
        nxt = sections[i + 1] if i + 1 < len(sections) else None
        body = text[sec.start : sec.end].split("\n", 1)[1] if "\n" in text[sec.start : sec.end] else ""
        same_field = nxt and _leaf(nxt.title).split()[:1] == _leaf(sec.title).split()[:1]
        if _is_field(sec.title) and nxt and same_field and len(body.strip()) < TINY_FIELD_CHARS:
            out.append(_Section(sec.title, sec.start, nxt.end))
            i += 2
        else:
            out.append(sec)
            i += 1
    return out


def _footnote(text: str, sections: list[_Section], i: int) -> str:
    """The definition of the field's footnote marker, searched only within the
    same fund page (up to the next section with a different parent fund)."""
    leaf = _leaf(sections[i].title)
    marker = next((m for m in FOOTNOTE_MARKERS if leaf.endswith(m)), None)
    if not marker:
        return ""
    parent = sections[i].title.split(PARENT_SEP)[0] if PARENT_SEP in sections[i].title else None
    end = len(text)
    for later in sections[i + 1 :]:
        if parent is None or not later.title.startswith(parent):
            end = later.start
            break
    page = " ".join(text[sections[i].end : end].split())
    # Footnote text runs until the next footnote marker (or the length cap).
    found = re.search(rf"{re.escape(marker)}\s*([A-Z][^¥€]{{10,{MAX_FOOTNOTE_CHARS}}})", page)
    return f"\n{marker} {found.group(1).strip()}" if found else ""


def _field_title(title: str, doc: Document) -> str:
    """Field chunks on a single-scheme page get the scheme name as their parent,
    so "[HDFC Small Cap Fund > AUM]" embeds as being about that fund."""
    if PARENT_SEP in title or doc.scheme == SHARED_SCHEME:
        return title
    return f"{doc.scheme.removesuffix(' Direct Growth')}{PARENT_SEP}{title}"


def _with_title(body: str, title: str) -> str:
    """Prefix the section path so the embedding knows which fund a chunk is about
    (the factsheet's "EXPENSE RATIO" blocks are otherwise indistinguishable)."""
    if not title or body.startswith(title):
        return body
    return f"[{title}]\n{body}"


def _chunk_scheme(doc: Document, title: str) -> str:
    """Shared factsheet chunks under one of the five schemes' headings belong to
    that scheme, so the retrieval scheme filter keeps them and drops other funds'."""
    if doc.scheme != SHARED_SCHEME or doc.doc_type != "factsheet":
        return doc.scheme
    schemes = detect_schemes(title.split(PARENT_SEP)[0])
    return schemes[0] if len(schemes) == 1 else doc.scheme


def chunk_documents(docs: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        chunks.extend(chunk_document(doc))
    return chunks


def _cli() -> None:
    from src.ingest.load import DEFAULT_SOURCES, load_documents

    parser = argparse.ArgumentParser(description="Phase 3 chunker debug print")
    parser.add_argument("--sources", default=DEFAULT_SOURCES)
    parser.add_argument("--limit", type=int, default=None, help="Max ingest URLs")
    parser.add_argument("--show", type=int, default=0, help="Print first N chunks")
    args = parser.parse_args()

    docs = load_documents(args.sources, limit=args.limit)
    chunks = chunk_documents(docs)
    per_url = Counter(c.url for c in chunks)
    for doc in docs:
        sizes = [len(c.text) for c in chunks if c.url == doc.url]
        print(
            f"{per_url[doc.url]:4d} chunks  chars min/avg/max="
            f"{min(sizes)}/{sum(sizes) // len(sizes)}/{max(sizes)}  {doc.url}"
        )
    print(f"total chunks={len(chunks)}")
    for c in chunks[: args.show]:
        print("-" * 60)
        print(c.metadata())
        print(c.text[:400])


if __name__ == "__main__":
    _cli()
