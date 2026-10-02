"""Phase 6: query-time retrieval from the hdfc_mf_faq collection (architecture §4.2, §6).

Embeds the query with the same MiniLM embedder used at ingest (after expanding
everyday terms such as "fund size" → "assets under management"), runs a dense
cosine search, and filters by scheme when the query names one of the five
schemes. Rows tagged scheme=ALL (none in the Groww-only corpus) stay in scope.
Two or more schemes named → filter to those schemes; this module never compares
or ranks funds. Fund-fact questions naming no fund never reach here (the clarify
guard asks which fund). Weak best match → empty list (caller treats as a miss).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from src.ingest.embed import embed_texts
from src.ingest.store import open_collection
from src.schemes import SHARED_SCHEME, detect_schemes

# Architecture allows 3–8. With one fact card per field, the right card is top-1
# for 40/40 fund × field questions (scripts/eval_gold.py --matrix); 8 keeps the
# fund's overview and neighbouring facts in context for broader questions, and 8
# short cards are only ~500 tokens for the generator.
TOP_K = 8

# Minimum cosine similarity (1 - cosine distance) of the best chunk. Below this the
# corpus does not cover the question and we return nothing rather than guess.
# Re-calibrated on the Groww fact-card index: in-scope questions score 0.64–0.92
# when a fund is named, but questions that name only a person (e.g. "Which other
# schemes does Chirag Setalvad manage?", 0.42) score lower; off-topic questions
# score 0.00–0.24. Questions that merely mention "HDFC" (e.g. HDFC Bank credit
# cards) are caught by the scope guard before retrieval.
MIN_SCORE = 0.35

class RetrievedChunk(TypedDict):
    text: str
    url: str
    section_title: str
    scheme: str
    fetched_at: str
    score: float
    field: str  # fact-card field (e.g. "expense_ratio"); "" for generic chunks


# Everyday phrasings → (terms the cards use, fact-card fields that answer them).
# The terms expand the text that gets embedded; the fields drive field routing
# (see retrieve). Guards and scheme detection see the original query.
QUERY_SYNONYMS: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = [
    (re.compile(r"\b(fund\s+size|size\s+of\s+the\s+fund|corpus|aum|asset\s+base|how\s+big)\b", re.I),
     "assets under management AUM", ("aum",)),
    (re.compile(r"\b(nav|net\s+asset\s+value|unit\s+price|price\s+per\s+unit)\b", re.I),
     "NAV per unit net asset value", ("nav",)),
    (re.compile(r"\b(expense\s+ratio|ter|fees?|charges)\b", re.I),
     "total expense ratio TER", ("expense_ratio",)),
    (re.compile(r"\b(risk\s+level|how\s+risky|risk\s+grade|riskometer)\b", re.I),
     "riskometer", ("riskometer",)),
    (re.compile(r"\b(fund\s+managers?|who\s+manages|managed\s+by)\b", re.I),
     "fund managers, the people who manage this fund", ("fund_managers",)),
    (re.compile(r"\bbenchmark", re.I), "benchmark index the fund is measured against", ("benchmark",)),
    (re.compile(r"\b(analysis|analy[sz]e|allocation|breakdown|break\s+up|split|ratio|"
                r"mix|composition|sectors?|asset\s+class(es)?|equity\s+(vs|versus|and|to)\s+debt|"
                r"how\s+much\s+(equity|debt|cash))\b", re.I),
     "holdings analysis: allocation by asset class, instrument type and sector",
     ("holdings_breakdown",)),
    (re.compile(r"\b(holdings?|portfolio|stocks?|invests?\s+in|holds?)\b", re.I),
     "holdings portfolio: stocks and bonds the fund holds, top 10 by % of assets", ("holdings",)),
    (re.compile(r"\b(statements?|cas|download)\b", re.I),
     "registrar and transfer agent RTA for account and capital gains statements", ("registrar",)),
    (re.compile(r"\bexit\s+load\b", re.I), "exit load (current)", ("exit_load",)),
    (re.compile(r"\b(other\s+(schemes?|funds?)|also\s+manag\w*|which\s+(schemes?|funds?)\s+does)\b", re.I),
     "other schemes also managed by the fund manager",
     ("fund_manager_other_schemes", "fund_manager_profile")),
    (re.compile(r"\b(custodian|address|phone|contact|incorporat\w*|launch\s+date|website|"
                r"fund\s+house|amc|asset\s+management\s+company)\b", re.I),
     "fund house (AMC) details", ("fund_house",)),
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


def intent_fields(query: str) -> tuple[str, ...]:
    """Fact-card fields the question asks for ("definition" for glossary questions)."""
    if _DEFINITION_RE.search(query):
        return ("definition",)
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
                    field=meta.get("field", ""),
                ))
        if hits:
            break  # longest matching phrase wins
    return hits[:2]


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
    return chunks
