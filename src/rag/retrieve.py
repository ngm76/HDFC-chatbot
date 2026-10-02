"""Query-time retrieval from the hdfc_mf_faq collection (Phases 6 and 16,
architecture §4.2, §6).

Embeds the query with the same MiniLM embedder used at ingest (after expanding
everyday terms such as "fund size" → "assets under management"), runs a dense
cosine search, and filters by scheme when the query names one of the five
schemes. Shared rows (scheme=ALL: statement guides, SEBI / AMFI pages, the
glossary) stay in scope. Cards for the same scheme and fact are ordered newest
document first (PRD §8 "conflicting sources"); a disagreement is logged.
Two or more schemes named → filter to those schemes; this module never compares
or ranks funds. Fund-fact questions naming no fund never reach here (the clarify
guard asks which fund). Weak best match → empty list (caller treats as a miss).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import TypedDict

from src.ingest.embed import embed_texts
from src.ingest.store import open_collection
from src.schemes import SHARED_SCHEME, detect_schemes

logger = logging.getLogger(__name__)

# Architecture allows 3–8. With one fact card per field, the right card is top-1
# for 40/40 fund × field questions (scripts/eval_gold.py --matrix); 8 keeps the
# fund's overview and neighbouring facts in context for broader questions, and 8
# short cards are only ~500 tokens for the generator.
TOP_K = 8

# Minimum cosine similarity (1 - cosine distance) of the best chunk. Below this the
# corpus does not cover the question and we return nothing rather than guess.
# Re-calibrated on the official index (Phase 16, 79 answerable questions): median
# 0.87, p5 0.53, but short term questions score low ("What is a folio number?",
# 0.22). Unanswerable mutual-fund questions about a named fund ("standard deviation
# of ...", "CEO of HDFC AMC") score 0.58–0.82, so no floor can separate them: the
# generator's found flag and the validator decide those (FR-1). Off-topic questions
# never get here (non-MF guard), so the floor only drops clearly unrelated text.
MIN_SCORE = 0.20

class RetrievedChunk(TypedDict):
    text: str
    url: str
    section_title: str
    scheme: str
    fetched_at: str
    score: float
    field: str  # fact-card field (e.g. "expense_ratio"), or the prose doc type's field
    doc_type: str  # scheme_page, kim, factsheet, ter, statement_guide, education, ...
    doc_date: str  # ISO date the document states for the fact ("" if none)
    publisher: str


# Everyday phrasings → (terms the cards use, fact-card fields that answer them).
# The terms expand the text that gets embedded; the fields drive field routing
# (see retrieve). Guards and scheme detection see the original query.
QUERY_SYNONYMS: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = [
    (re.compile(r"\b(fund\s+size|size\s+of\s+the\s+fund|corpus|aum|asset\s+base|how\s+big)\b", re.I),
     "assets under management AUM", ("aum",)),
    (re.compile(r"\b(nav|net\s+asset\s+value|unit\s+price|price\s+per\s+unit)\b", re.I),
     "NAV per unit net asset value", ("nav",)),
    (re.compile(r"\b(expense\s+ratios?|ter|fees?|charges)\b", re.I),
     "total expense ratio TER", ("expense_ratio",)),
    (re.compile(r"\b(risk\s+level|how\s+risky|risk\s+grade|riskometer)\b", re.I),
     "riskometer", ("riskometer",)),
    (re.compile(r"\b(fund\s+managers?|who\s+manages|managed\s+by)\b", re.I),
     "fund managers, the people who manage this fund", ("fund_managers",)),
    (re.compile(r"\b(experience|managing\s+since|since\s+when)\b", re.I),
     "fund manager details: managing since, total experience", ("fund_manager_profile",)),
    (re.compile(r"\bbenchmark", re.I), "benchmark index the fund is measured against", ("benchmark",)),
    (re.compile(r"\b(analysis|analy[sz]e|allocation|breakdown|break\s+up|split|ratio|"
                r"mix|composition|sectors?|asset\s+class(es)?|equity\s+(vs|versus|and|to)\s+debt|"
                r"how\s+much\s+(equity|debt|cash))\b", re.I),
     "holdings analysis: allocation by asset class, instrument type and sector",
     ("holdings_breakdown",)),
    (re.compile(r"\b(holdings?|portfolio|stocks?|invests?\s+in|holds?)\b", re.I),
     "holdings portfolio: stocks and bonds the fund holds, top 10 by % of assets", ("holdings",)),
    (re.compile(r"\b(statements?|cas|download|registrar|rta|cams|kfin\w*)\b", re.I),
     "how to get an account statement, capital gains statement or consolidated account "
     "statement (CAS)", ("statement_steps",)),
    (re.compile(r"\bexit\s+loads?\b", re.I), "exit load (current)", ("exit_load",)),
    (re.compile(r"\block[\s-]?in\b", re.I), "lock-in period", ("lock_in",)),
    (re.compile(r"\b(min(imum)?\s+(investment|lump\s*sum|application|purchase)|lump\s*sum)\b", re.I),
     "minimum application amount (lump sum)", ("min_lumpsum",)),
    (re.compile(r"\b(formerly|former\s+name|renamed|old\s+name|previous\s+name|"
                r"earlier\s+called|called\s+(earlier|before|previously))\b", re.I),
     "former name of the scheme", ("former_name",)),
    (re.compile(r"\b(inception|launch(ed)?(\s+date)?|allotment\s+date|date\s+of\s+allotment|"
                r"how\s+old|since\s+when\s+(has|is)\s+the\s+fund)\b", re.I),
     "date of allotment / inception date", ("inception_date", "plan_inception_date")),
    (re.compile(r"\b(objective|aim|goal\s+of\s+the\s+(fund|scheme))\b", re.I),
     "investment objective", ("objective",)),
    (re.compile(r"\bentry\s+load\b", re.I), "entry load", ("entry_load",)),
    (re.compile(r"\b(type\s+of\s+(scheme|fund)|category|what\s+kind\s+of\s+fund)\b", re.I),
     "type of scheme (category)", ("scheme_type",)),
    (re.compile(r"\b(how\s+(to|do\s+i|can\s+i)\s+(invest|start|buy\s+units|redeem|withdraw)|"
                r"redeem|redemption)\b", re.I),
     "how to invest or redeem: steps", ("how_to_invest", "scheme_faq")),
    (re.compile(r"\b(min(imum)?\s+sip|sip\s+amount)\b", re.I), "minimum SIP amount", ("min_sip",)),
]

# "What is an expense ratio?" asks for a definition, not the fund's value.
_DEFINITION_RE = re.compile(
    r"\bwhat\s+(is|are)\s+(an?|meant\s+by)\b|\bwhat\s+does\b.*\bmean\b|\bmeaning\s+of\b|"
    r"\bdefin(e|ition)\b|\bexplain\b",
    re.I,
)
ROUTED_K = 2  # routed cards placed ahead of the plain dense results


def expand_query(query: str) -> str:
    extra = [terms for pattern, terms, _ in QUERY_SYNONYMS if pattern.search(query)]
    return f"{query} ({'; '.join(extra)})" if extra else query


# "What is ELSS?" / "What is a SIP?": a short question about a term, no fund named.
_SHORT_WHAT_IS_RE = re.compile(r"^\s*what\s+(is|are)\s+(an?\s+)?[\w\s-]{2,30}\??\s*$", re.I)
_RISK_MEANING_RE = re.compile(r"\b(riskometer|risk[\s-]?o[\s-]?meter|risk\s+level)", re.I)
_PLAN_EXPLAINER_RE = re.compile(
    r"\bdirect\s+(vs\.?|versus|and|or)\s+regular\b|\bregular\s+(vs\.?|versus|and|or)\s+direct\b|"
    r"\bdifference\s+between\s+(a\s+)?(direct|regular)\b",
    re.I,
)


def intent_fields(query: str) -> tuple[str, ...]:
    """Fact-card fields the question asks for. Definitions go to the glossary cards
    and the SEBI / AMFI education pages; riskometer meaning to the SEBI circular."""
    if _PLAN_EXPLAINER_RE.search(query):
        return ("education",)
    short_term = _SHORT_WHAT_IS_RE.match(query) and "hdfc" not in query.lower()
    if _DEFINITION_RE.search(query) or short_term:
        if _RISK_MEANING_RE.search(query):
            return ("riskometer_levels", "education")
        return ("definition", "education")
    fields: list[str] = []
    for pattern, _, targets in QUERY_SYNONYMS:
        if pattern.search(query):
            fields.extend(t for t in targets if t not in fields)
    return tuple(fields)


def _scheme_filter(schemes: list[str]) -> dict:
    """Named schemes' chunks plus shared rows. Shared *factsheet* chunks are left
    out: the chunker tags the five schemes' factsheet pages with their scheme, so
    the factsheet chunks still tagged ALL describe other funds (eval: they pushed
    the right chunks out of the top k)."""
    return {
        "$or": [
            {"scheme": {"$in": schemes}},
            {"$and": [{"scheme": SHARED_SCHEME}, {"doc_type": {"$ne": "factsheet"}}]},
        ]
    }


@lru_cache(maxsize=1)
def _collection():
    return open_collection()


def _search(embedding: list[list[float]], k: int, where: dict | None) -> list[RetrievedChunk]:
    result = _collection().query(
        query_embeddings=embedding,
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return [
        RetrievedChunk(
            text=doc,
            url=meta["url"],
            section_title=meta.get("section_title", ""),
            scheme=meta["scheme"],
            fetched_at=meta["fetched_at"],
            score=round(1.0 - dist, 4),
            field=meta.get("field", ""),
            doc_type=meta.get("doc_type", ""),
            doc_date=meta.get("doc_date", ""),
            publisher=meta.get("publisher", ""),
        )
        for doc, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]


HOLDINGS_FIELDS = ("holdings", "holdings_more")
# Words that are not part of a company name in a holdings question.
_NAME_STOPWORDS = set(
    "a an and any are as at be by can do does for from has have hdfc how i in is it its "
    "me much my of on or the to what which who why will with fund funds scheme direct "
    "growth plan hold holds held holding holdings invest invests invested investment "
    "exposure stake portfolio stock stocks share shares own owns large small flexi cap "
    "elss tax saver balanced advantage baf equity mid percentage percent weight there "
    "include includes included contain contains list tell".split()
)


def _holding_mentions(query: str, scheme_where: dict | None) -> list[RetrievedChunk]:
    """Holdings cards that literally mention a company named in the question.

    Company names are a weak signal for dense search across long lists of names,
    so this checks every holdings card of the named fund(s) for the question's
    remaining words (longest phrase first), case-insensitively.
    """
    words = [w for w in re.findall(r"[a-z0-9&.'-]+", query.lower()) if w not in _NAME_STOPWORDS]
    phrases = [
        " ".join(words[i : i + n])
        for n in (3, 2, 1)
        for i in range(len(words) - n + 1)
        if n > 1 or len(words[i]) >= 4
    ]
    if not phrases:
        return []
    field_where: dict = {"field": {"$in": list(HOLDINGS_FIELDS)}}
    where = {"$and": [scheme_where, field_where]} if scheme_where else field_where
    cards = _collection().get(where=where, include=["documents", "metadatas"])
    hits: list[RetrievedChunk] = []
    for phrase in phrases:
        pattern = re.compile(rf"(?<![\w]){re.escape(phrase)}(?![\w])", re.I)
        for doc, meta in zip(cards["documents"], cards["metadatas"]):
            if pattern.search(doc) and all(h["text"] != doc for h in hits):
                hits.append(RetrievedChunk(
                    text=doc, url=meta["url"], section_title=meta.get("section_title", ""),
                    scheme=meta["scheme"], fetched_at=meta["fetched_at"], score=1.0,
                    field=meta.get("field", ""), doc_type=meta.get("doc_type", ""),
                    doc_date=meta.get("doc_date", ""), publisher=meta.get("publisher", ""),
                ))
        if hits:
            break  # longest matching phrase wins
    return hits[:2]


def one_page_covers(schemes: list[str], fields: tuple[str, ...]) -> bool:
    """PRD §8 factual comparison: True if a single official page has a card for the
    asked field for every one of `schemes` (e.g. the TER file for expense ratios)."""
    if not fields:
        return False
    cards = _collection().get(
        where={"$and": [{"scheme": {"$in": schemes}}, {"field": {"$in": list(fields)}}]},
        include=["metadatas"],
    )
    by_url: dict[str, set[str]] = {}
    for meta in cards["metadatas"]:
        by_url.setdefault(meta["url"], set()).add(meta["scheme"])
    return any(set(schemes) <= covered for covered in by_url.values())


def effective_date(chunk: RetrievedChunk) -> str:
    """The date a fact is "as of": the document's own date, else its ingest date."""
    return chunk.get("doc_date") or chunk["fetched_at"]


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def prefer_newest(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """PRD §8 conflicting sources: among cards for the same scheme and fact (from
    different documents), the newest goes first, in the slot the group's best card
    held. A disagreement in their figures is logged (scheme and field only)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for i, c in enumerate(chunks):
        if c["field"] and c["scheme"] != SHARED_SCHEME:
            groups.setdefault((c["scheme"], c["field"]), []).append(i)
    out = list(chunks)
    for (scheme, field), slots in groups.items():
        members = [chunks[i] for i in slots]
        if len({m["url"] for m in members}) < 2:
            continue
        ordered = sorted(members, key=effective_date, reverse=True)
        for slot, chunk in zip(slots, ordered):
            out[slot] = chunk
        figures = {frozenset(_NUMBER_RE.findall(m["text"].split(": ", 2)[-1])) for m in members}
        if len(figures) > 1:
            logger.info("source conflict for %s / %s: newest (%s) preferred",
                        scheme, field, effective_date(ordered[0]))
    return out


def retrieve(
    query: str,
    k: int = TOP_K,
    min_score: float = MIN_SCORE,
    schemes: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks for the query, best first; [] if the best score is below min_score.

    `schemes` overrides the schemes detected in the query text (used for
    follow-ups whose fund comes from earlier in the conversation).

    Field routing: when the question clearly asks for a known fact ("holdings",
    "fund size", "benchmark", a definition…), the best cards of that field (within
    the scheme filter) go first, then the plain dense results. Several cards with
    similar wording (e.g. the holdings list continued over several cards) otherwise
    compete for the top slot.
    """
    query = query.strip()
    if not query:
        return []
    if schemes is None:
        schemes = detect_schemes(query)
    scheme_where = _scheme_filter(schemes) if schemes else None
    embedding = embed_texts([expand_query(query)]).tolist()

    chunks = _search(embedding, k, scheme_where)
    fields = intent_fields(query)
    if fields:
        field_where: dict = {"field": {"$in": list(fields)}}
        where = {"$and": [scheme_where, field_where]} if scheme_where else field_where
        routed = _search(embedding, ROUTED_K * len(fields), where)
        if "holdings" in fields:
            # Exact company-name matches first ("Does it hold Tata Steel?").
            routed = _holding_mentions(query, scheme_where) + routed
        seen: set[str] = set()
        merged = []
        for c in routed + chunks:
            if c["text"] not in seen:
                seen.add(c["text"])
                merged.append(c)
        chunks = merged[:k]

    if not chunks or max(c["score"] for c in chunks) < min_score:
        return []
    return prefer_newest(chunks)
