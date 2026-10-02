"""Phase 8: grounded answer generation (architecture §7).

Generators, picked in this order unless GENERATOR forces one:
  1. Claude via the Anthropic SDK, when ANTHROPIC_API_KEY is set (paid API).
  2. Groq (free tier), when GROQ_API_KEY is set.
  3. The extractive fallback, which quotes the best-matching source sentences.

Environment (read from .env too):
  ANTHROPIC_API_KEY  Claude API key
  CLAUDE_MODEL       default claude-opus-5
  CLAUDE_EFFORT      low | medium | high, default medium
  GROQ_API_KEY       Groq API key (console.groq.com)
  GROQ_MODEL         default openai/gpt-oss-120b
  GENERATOR          claude | groq | extractive (optional)

The rules in the prompt are also enforced in code: at most three sentences, and
every number in the answer must appear in the excerpts (no invented fees). A
failed check raises GenerationError so the caller shows a safe error instead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import anthropic
import httpx
from dotenv import load_dotenv

from src.guards.performance import is_performance
from src.rag.retrieve import RetrievedChunk, intent_fields

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
MAX_SENTENCES = 3
REQUEST_TIMEOUT_S = 60.0

# Groq: OpenAI-compatible chat completions. gpt-oss models support strict JSON
# schema output on the free tier (limits as of 2026-09: 30 req/min, 1K req/day,
# 8K tokens/min, 200K tokens/day). One question with 8 excerpts is ~5-6K tokens,
# so back-to-back questions can hit the per-minute cap; 429s are retried.
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MAX_RETRIES = 3
GROQ_MAX_WAIT_S = 65.0
# Models with strict json_schema support on Groq (docs, 2026-09); others get JSON mode.
GROQ_STRICT_SCHEMA_PREFIXES = ("openai/gpt-oss-", "qwen/")
JSON_MODE_INSTRUCTION = (
    '\n\nRespond with only a JSON object of the form '
    '{"found": true or false, "answer": "<at most three sentences>", "excerpt": <number>}.'
)

SYSTEM_PROMPT = """\
You answer questions about five HDFC Mutual Fund schemes for a facts-only FAQ \
assistant. The user message contains numbered excerpts from the public Groww \
scheme pages of these funds, followed by the question.

Rules:
- Use only facts stated in the excerpts, never outside knowledge.
- Answer in at most three sentences of plain text, with no lists or markdown. \
Write complete sentences that name the fund, e.g. "The expense ratio of HDFC \
Small Cap Fund Direct Growth is 0.78%."
- Copy numbers (percentages, amounts, periods, dates) exactly as written; do not \
calculate, round, combine or compare them.
- Never give investment advice: no buy/sell/hold views, recommendations, \
suitability opinions, rankings, or return calculations or comparisons.
- Excerpts may describe other funds or general regulations. Only use an excerpt \
about the fund the question asks about. If the only figure available is a \
general regulatory limit rather than the fund's own figure, say that it is a \
regulatory limit, not the fund's actual figure.
- Figures such as NAV, AUM (fund size) and expense ratio change over time. When \
an excerpt gives an "as on" date for the figure, state that date in the answer.
- If one excerpt shows a field as "NA" but another gives its actual value, use the value.
- If the field has several values in the excerpt you use (for example several fund \
managers, or several plans' NAVs when no plan is named), list all of them with \
their roles or labels, even if the question uses the singular.
- For allocation, mix, ratio or "holdings analysis" questions, quote the totals in \
the "Holdings analysis" excerpts and say they are calculated from the holdings \
listed on Groww. Lead with the asset-class mix (equity / debt / cash / other); \
add the top sectors only if asked or if space allows. Never add up or calculate \
percentages yourself.
- Lists such as holdings are split across several excerpts, and you may see only \
part of one (e.g. the top 10 of 87 holdings). Never say an item is absent or not \
held unless it is absent from a complete list; if the item is not in the excerpts, \
set found to false.
- If the excerpts do not contain the answer, set found to false and leave answer empty.

Set excerpt to the number of the single excerpt that best supports your answer."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "excerpt": {"type": "integer"},
    },
    "required": ["found", "answer", "excerpt"],
    "additionalProperties": False,
}

EXTRACTIVE_LABEL = "[Extractive fallback: quoted from the source, no LLM configured]"


class GenerationError(Exception):
    """Generator failed or produced an answer that broke a grounding rule."""


class UngroundedNumberError(GenerationError):
    """The answer contained a figure that is not in the excerpts (e.g. a sum the
    model calculated). Not a transient failure: retrying would not help."""


@dataclass(frozen=True)
class Generation:
    found: bool
    text: str
    chunk_index: int  # 0-based index into the chunks passed in
    mode: str  # "claude" | "groq" | "extractive"


def generator_mode() -> str:
    """claude if its key is set, else groq if its key is set, else the extractive
    fallback. GENERATOR forces one."""
    forced = os.getenv("GENERATOR", "").strip().lower()
    if forced in ("claude", "groq", "extractive"):
        return forced
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    return "groq" if os.getenv("GROQ_API_KEY") else "extractive"


def generator_label() -> str:
    """Human-readable generator name for the UI and generated docs."""
    return {
        "claude": f"Claude ({os.getenv('CLAUDE_MODEL', DEFAULT_MODEL)})",
        "groq": f"Groq ({os.getenv('GROQ_MODEL', DEFAULT_GROQ_MODEL)})",
        "extractive": "extractive fallback (no LLM configured)",
    }[generator_mode()]


def generate(
    query: str,
    chunks: list[RetrievedChunk],
    conversation: str = "",
    about_fund: str | None = None,
) -> Generation:
    """`conversation`: recent exchanges (src/rag/context.py) to interpret follow-ups.
    `about_fund`: the fund a follow-up refers to when the question names none."""
    if not chunks:
        raise ValueError("generate() needs at least one chunk")
    user = _user_message(query, chunks, conversation, about_fund)
    mode = generator_mode()
    if mode == "claude":
        return _generate_claude(user, chunks)
    if mode == "groq":
        return _generate_groq(user, chunks)
    return _generate_extractive(query, chunks)


# --- Claude -------------------------------------------------------------------


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=REQUEST_TIMEOUT_S, max_retries=2)


# Repeated next to the question: the system-prompt rule alone was followed
# inconsistently (fund-manager answers listed one of two names).
COMPLETENESS_REMINDER = (
    "Answer completely: if the excerpt you use lists several values for what is "
    "asked (for example several fund managers), name all of them with their roles."
)


def _user_message(
    query: str, chunks: list[RetrievedChunk], conversation: str = "", about_fund: str | None = None
) -> str:
    parts = []
    if conversation:
        parts.append(
            "Conversation so far (only to understand what the question refers to; "
            "take every fact from the excerpts, not from earlier answers):\n" + conversation
        )
    parts.append(f"Excerpts:\n\n{_context(chunks)}")
    question = f"Question: {query}"
    if about_fund:
        question += f"\n(This follow-up question is about {about_fund}.)"
    parts.append(question)
    parts.append(COMPLETENESS_REMINDER)
    return "\n\n".join(parts)


def _context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{i}] Source: {c['url']}\nSection: {c['section_title'] or '(none)'}\n{c['text']}"
        for i, c in enumerate(chunks, 1)
    )


def _generate_claude(user: str, chunks: list[RetrievedChunk]) -> Generation:
    try:
        response = _client().beta.messages.create(
            model=os.getenv("CLAUDE_MODEL", DEFAULT_MODEL),
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": os.getenv("CLAUDE_EFFORT", "medium"),
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise GenerationError("Anthropic API key was rejected") from exc
    except anthropic.RateLimitError as exc:
        raise GenerationError("rate limited by the Anthropic API") from exc
    except anthropic.APIStatusError as exc:
        raise GenerationError(f"Anthropic API error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:  # includes timeouts
        raise GenerationError("could not reach the Anthropic API") from exc

    if response.stop_reason == "refusal":
        raise GenerationError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise GenerationError("model output was truncated")
    raw = next((b.text for b in response.content if b.type == "text"), "")
    return _finish(raw, chunks, "claude")


def _finish(raw: str, chunks: list[RetrievedChunk], mode: str) -> Generation:
    """Parse the model's JSON and apply the code-enforced grounding rules."""
    try:
        data = json.loads(raw)
        found, answer, excerpt = bool(data["found"]), str(data["answer"]), int(data["excerpt"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GenerationError("model returned malformed JSON") from exc

    if not found or not answer.strip():
        return Generation(False, "", 0, mode)
    index = excerpt - 1
    if not 0 <= index < len(chunks):
        index = 0
    text = _cap_sentences(answer.strip())
    _check_numbers(text, chunks)
    return Generation(True, text, index, mode)


# --- Groq (free tier) ---------------------------------------------------------


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("retry-after", "10"))
    except ValueError:
        return 10.0


def _groq_body(model: str, user: str) -> dict:
    """Strict JSON schema + low reasoning on gpt-oss models; plain JSON mode (with
    the shape spelled out in the prompt) on others, e.g. llama-3.1-8b-instant."""
    body: dict = {"model": model, "max_completion_tokens": 4096}
    if model.startswith(GROQ_STRICT_SCHEMA_PREFIXES):
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "grounded_answer", "strict": True, "schema": OUTPUT_SCHEMA},
        }
        # Short reasoning keeps each question well inside the free tier's token caps.
        body["reasoning_effort"] = "low"
        body["include_reasoning"] = False
        system = SYSTEM_PROMPT
    else:
        body["response_format"] = {"type": "json_object"}
        body["temperature"] = 0
        system = SYSTEM_PROMPT + JSON_MODE_INSTRUCTION
    body["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return body


def _generate_groq(user: str, chunks: list[RetrievedChunk]) -> Generation:
    body = _groq_body(os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL), user)
    headers = {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"}

    for attempt in range(GROQ_MAX_RETRIES + 1):
        try:
            response = httpx.post(GROQ_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT_S)
        except httpx.TimeoutException as exc:
            raise GenerationError("Groq request timed out") from exc
        except httpx.HTTPError as exc:
            raise GenerationError("could not reach Groq") from exc
        if response.status_code == 429 and attempt < GROQ_MAX_RETRIES:
            wait = min(_retry_after(response), GROQ_MAX_WAIT_S)
            logger.warning("Groq rate limit; retrying in %.0fs", wait)
            time.sleep(wait)
            continue
        break

    if response.status_code == 401:
        raise GenerationError("Groq API key was rejected")
    if response.status_code == 429:
        raise GenerationError("Groq free-tier rate limit reached; try again shortly")
    if response.status_code >= 400:
        raise GenerationError(f"Groq API error {response.status_code}")
    try:
        choice = response.json()["choices"][0]
        raw = choice["message"]["content"] or ""
    except (ValueError, KeyError, IndexError) as exc:
        raise GenerationError("unexpected Groq response") from exc
    if choice.get("finish_reason") == "length":
        raise GenerationError("model output was truncated")
    return _finish(raw, chunks, "groq")


# --- Extractive fallback ------------------------------------------------------

# Scheme-name words identify the fund rather than the fact asked for, and every
# chunk of that fund carries them (title prefix), so they do not score.
_STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it its me my of on or "
    "the to what when where which who why will with fund funds hdfc direct growth "
    "plan scheme schemes large small flexi cap elss tax saver balanced advantage".split()
)
_TITLE_PREFIX_RE = re.compile(r"^\[[^\]\n]*\]\n")


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


EXTRACTIVE_CANDIDATES = 3


def _best_sentences(query: str, text: str) -> tuple[int, list[str]]:
    """(overlap score, up to three best-overlapping sentences in document order)."""
    body = _TITLE_PREFIX_RE.sub("", text)
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n\s*\n|\s*[•●]\s*", body)
        if len(s.strip()) > 20
        and not s.strip().endswith("?")  # FAQ questions aren't answers
        and not is_performance(s)  # never quote returns / CAGR tables (PRD: no performance)
    ]
    wanted = _terms(query)
    scored = [(len(wanted & _terms(s)), i, s) for i, s in enumerate(sentences)]
    best = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))[:MAX_SENTENCES]
    return sum(x[0] for x in best), [s for _, _, s in sorted(best, key=lambda x: x[1])]


def _generate_extractive(query: str, chunks: list[RetrievedChunk]) -> Generation:
    """Quote up to three sentences from whichever of the top chunks overlaps the
    query best (ties go to the higher-ranked chunk). Cites that chunk. When the top
    chunk is a fact card routed for the field asked ("launched" -> inception date),
    it is the answer even if the wording differs, so its card text is quoted."""
    fields = intent_fields(query)
    top = chunks[0]
    if fields and top["field"] in fields and not is_performance(top["text"]):
        quote = " ".join(_TITLE_PREFIX_RE.sub("", top["text"]).split())[:400]
        return Generation(True, f"{EXTRACTIVE_LABEL} {quote}", 0, "extractive")
    candidates = [
        (i, *_best_sentences(query, c["text"])) for i, c in enumerate(chunks[:EXTRACTIVE_CANDIDATES])
    ]
    index, score, sentences = max(candidates, key=lambda c: (c[1], -c[0]))
    if not score:
        return Generation(False, "", 0, "extractive")
    quote = " ".join(" ".join(s.split())[:300] for s in sentences)
    return Generation(True, f"{EXTRACTIVE_LABEL} {quote}", index, "extractive")


# --- Grounding checks ---------------------------------------------------------

_ABBREVIATIONS = re.compile(r"\b(Rs|No|Nos|e\.g|i\.e|p\.a|viz|approx|Ltd|Co|vs)\.", re.I)


def _cap_sentences(text: str) -> str:
    protected = _ABBREVIATIONS.sub(lambda m: m.group(0)[:-1] + "\x00", text)
    sentences = re.split(r"(?<=[.!?])\s+", protected)
    return " ".join(sentences[:MAX_SENTENCES]).replace("\x00", ".")


def _normalize_number(raw: str) -> str:
    n = raw.replace(",", "")
    return n.rstrip("0").rstrip(".") if "." in n else n  # "1.00" matches "1"


def _numbers(text: str) -> set[str]:
    return {_normalize_number(n) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _check_numbers(answer: str, chunks: list[RetrievedChunk]) -> None:
    context = _numbers(" ".join(c["text"] for c in chunks))
    invented = _numbers(answer) - context
    if invented:
        raise UngroundedNumberError(f"answer contains numbers not in the sources: {sorted(invented)}")
