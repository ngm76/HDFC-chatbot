# Mutual Fund FAQ RAG Chatbot

A facts-only FAQ assistant for five **HDFC Mutual Fund** schemes, built with
retrieval-augmented generation (RAG) over **official public pages only**: HDFC Mutual
Fund, SEBI and AMFI / Mutual Funds Sahi Hai. Every response is at most three
sentences with exactly one source link and a "Last updated from sources" date. It
refuses investment advice, never quotes or compares returns, and blocks messages
that contain personal details.

Product spec: [docs/PRD.md](docs/PRD.md) · Design: [docs/architecture.md](docs/architecture.md)
· Build plan: [docs/implementation.md](docs/implementation.md) · Evaluation:
[docs/evaluation_report.md](docs/evaluation_report.md) · Sample Q&A: [docs/sample_qa.md](docs/sample_qa.md)

## Scope

**AMC:** HDFC Mutual Fund. **Plan:** Direct Plan – Growth (every answer defaults to it).

| Category | Scheme | Also known as |
|---|---|---|
| Large cap | HDFC Large Cap Fund | HDFC Top 100 Fund (former name) |
| Flexi cap | HDFC Flexi Cap Fund | HDFC Equity Fund (former name) |
| ELSS | HDFC ELSS Tax Saver Fund | HDFC TaxSaver (former name) |
| Small cap | HDFC Small Cap Fund | "hdfc smallcap" |
| Hybrid | HDFC Balanced Advantage Fund | BAF |

**Source list (deliverable):** [data/sources.csv](data/sources.csv), with notes in
[data/schemes.md](data/schemes.md). 24 pages are ingested:

| Publisher | Documents | Answers |
|---|---|---|
| HDFC MF | 5 scheme pages | exit load, min SIP, riskometer, benchmark, AUM, lock-in, managers |
| HDFC MF | 5 Key Information Memorandums (21 Nov 2025) | full exit-load rules, lump-sum minimums, ELSS lock-in rule, former names |
| HDFC MF | Monthly factsheet | NAV with its date, holdings, asset mix, manager details, objective |
| HDFC MF | TER disclosure (workbook) | expense ratio, Direct and Regular, by date |
| HDFC MF | 2 statement pages | account / capital-gains statements, CAS |
| SEBI | Riskometer circular, investor FAQs, investor charter | riskometer levels, investor basics |
| AMFI / Mutual Funds Sahi Hai | 7 education pages | ELSS, lock-in, SIP, exit load, riskometer, direct vs regular |

Two Groww help-centre links are used only as links (never ingested): the PII block
message and the non-mutual-fund redirect (PRD Addendum A5).

**What it answers:** the PRD's seven question types (expense ratio, exit load, minimum
SIP, ELSS lock-in, riskometer, benchmark, how to download statements) plus, by owner
decision (Addendum A1), NAV, fund size, fund managers, holdings, holdings analysis,
definitions and scheme details.

**How each kind of message is handled** (PRD §6, fixed precedence):

| Message | Response | Link |
|---|---|---|
| Contains PAN, Aadhaar, phone, email, OTP, account/folio number | **Blocked**: safety message; nothing is sent, stored or logged | Groww help (mutual funds) |
| Advice ("should I buy", "which is better for me") | Polite refusal + an offer of facts | AMFI investor education |
| Returns / performance / rankings | Refusal, no figures | HDFC MF monthly factsheet |
| Other fund house, other HDFC scheme, Regular / IDCW, live NAV | What is covered | AMFI / HDFC MF schemes listing / scheme page / factsheet |
| Not about mutual funds | One-line redirect | Groww help |
| Ambiguous name ("HDFC cap fund"), or no fund named | "Which fund do you mean?" with chips | HDFC MF schemes listing |
| Fact question | ≤ 3 sentences from the official sources | The cited page |

## How it works

```
Loading → Chunking (fact cards) → Embedding (MiniLM) → ChromaDB      [build time]
PII check → guards → context → retrieval → generation → validator → template   [per question]
```

- **Loading** (`src/ingest/load.py`): HTML, PDF and the TER `.xlsx` workbook; HDFC
  scheme pages lose their returns, suitability and promotional blocks; a page is
  cached only once its text passes, and a failed fetch falls back to that last
  good copy.
- **Chunking** (`src/ingest/official.py`): each fact becomes one card that names its
  scheme, e.g. *"HDFC Small Cap Fund Direct Growth: Expense ratio (TER, total expense
  ratio): Direct Plan: 0.79% as on 30 Sep 2026 …"*. Returns tables are never
  indexed. Prose pages use a heading-aware splitter. 249 chunks in all.
- **Embedding / store:** `sentence-transformers/all-MiniLM-L6-v2` (ONNX Runtime) into
  the persistent Chroma collection `hdfc_mf_faq` (cosine).
- **Retrieval** (`src/rag/retrieve.py`): scheme filter, routing by question type,
  newest document first when sources disagree, and comparisons only when one page
  covers both schemes.
- **Generation** (`src/rag/generate.py`): Groq `openai/gpt-oss-120b` (or Claude) with
  strict JSON output; numbers must appear in the sources; the FR-4 validator
  (`src/rag/validate.py`) rejects return figures, judgement words, opinions, more
  than three sentences or unknown links, regenerates once, then says "I couldn't
  find this in the official sources".
- **Conversation:** the last 25 exchanges (redacted) help with follow-ups like "And
  its exit load?"; they live in the browser session only.

## Setup

Requires **Python 3.11+** (developed on 3.12, Windows 11).

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then set GROQ_API_KEY (free) or ANTHROPIC_API_KEY
```

### Build the index

```powershell
python scripts/ingest.py --refresh --strict   # fetch, chunk, embed, store (~1 min)
python scripts/ingest.py --check-only         # fetch + chunk + checks, index untouched
```

`--strict` refuses to publish incomplete data: every page must load, every scheme
must have its required cards (the seven question types, NAV, AUM, holdings, overview;
ELSS lock-in), and no chunk may contain a return figure. The first run also
downloads the embedding model (~90 MB).

### Run the app

```powershell
streamlit run src/app/main.py
```

The UI follows PRD §9: welcome line (with the five schemes covered listed under it), three example questions, a pinned "Facts-only.
No investment advice." note, the input hint, answers with a source label and
freshness line, the PII block state, 👍 / 👎 feedback (session only), and chips for
ambiguous fund names. It is a single chat screen: the most asked questions are shown
as tappable chips (prominent on an empty chat, then in a collapsible section).

## Keeping the data current

- **Daily:** a GitHub Actions workflow redeploys on Render, whose build re-fetches
  everything (`--refresh --strict`), and checks every source link.
- **Monthly checklist** (dated files change URL with each edition):
  1. Run `python scripts/check_links.py`. It reports broken links and any newer
     factsheet, TER file or KIM listed on HDFC MF's hub pages.
  2. Put each newer URL into `data/sources.csv` (same row; clear `fetched_at`), and
     update the factsheet `label` month.
  3. Run `python scripts/ingest.py --refresh --strict` and the tests below.
- The build log shows `STALE EDITION:` when the factsheet (35 days) or TER file
  (7 days) is past its freshness limit, and answers citing it add "Please check the
  linked page for the latest value."

## How to add a scheme alias

Aliases and former names live in `src/schemes.py`:
1. Add the spelling to the scheme's pattern in `SCHEME_PATTERNS` (exact match), e.g.
   `r"\bhdfc\s+top[\s-]?100\b"`.
2. For a former name, also add it to `FORMER_NAMES` so answers say "X was formerly
   called Y".
3. For misspellings, add the words to `_ALIASES` (fuzzy matched, ratio ≥ 0.85).
4. Add a case to `scripts/debug_guards.py` and run it.

## Tests and evaluation

| Command | What it checks | LLM tokens |
|---|---|---|
| `python scripts/debug_guards.py` | 99 cases: every PRD §6 example and §8 edge case, PII never reaching retrieval or the model, one link on every non-answer | none |
| `python scripts/eval_gold.py --matrix` | Every fund × field (50): the right card ranks first | none |
| `python scripts/eval_gold.py --retrieval-only` | 20-question gold set, retrieval only | none |
| `python scripts/eval_gold.py` | Same 20 questions, generated answers | ~50K |
| `python scripts/test_ui.py` | Headless UI test (Streamlit AppTest) | none |
| `python scripts/debug_chat.py --no-llm` | Multi-turn follow-ups | none |
| `python scripts/check_links.py` | Link health and newer editions | none |

### How to run the golden-set evaluation (PRD §10)

[data/golden_set.csv](data/golden_set.csv) holds 200 labelled queries (120 fact, 30
advice, 20 performance, 15 out-of-scope, 15 PII).

```powershell
python scripts/eval_golden.py --mode free --report   # all 200, offline generator, ~3 min
python scripts/eval_golden.py --mode full --report   # Groq answers; resumable
```

- **Free mode** grades intent routing, retrieval, citations, format and PII without
  any LLM.
- **Full mode** also grades the generated answers. It saves each result in
  `data/eval/` and skips finished queries on the next run, because the 120 fact
  answers need about 300K tokens, more than Groq's free 200K per day.
- `--report` writes [docs/evaluation_report.md](docs/evaluation_report.md) with every
  §10 metric against its target and the rows to review.

## Deploy on Render (free plan)

The repo includes a Render Blueprint ([render.yaml](render.yaml)) for one free web
service. Render's disk is temporary, so the index is rebuilt on every deploy:

1. **Build:** `pip install -r requirements.txt && python scripts/ingest.py --refresh --strict`.
   If a page fails or a required fact is missing, the build fails and Render keeps
   serving the previous deploy.
2. **Daily refresh:** [.github/workflows/refresh-data.yml](.github/workflows/refresh-data.yml)
   calls Render's deploy hook at 21:00 IST and runs the link check.
3. **Staleness banner:** the app warns if the data is more than 3 days old.

**One-time setup:** Render → New → Blueprint → this repo; enter `GROQ_API_KEY`
(secret). Then copy the service's Deploy Hook URL into a GitHub Actions secret
named `RENDER_DEPLOY_HOOK_URL`.

**Free-plan notes:** peak memory ~305 MB of 512 MB; the service sleeps after ~15
minutes idle (first visit then takes ~30–60 s); GitHub pauses scheduled workflows
after 60 days without repo activity.

## Generator

Picked automatically: **Claude** if `ANTHROPIC_API_KEY` is set, else **Groq** if
`GROQ_API_KEY` is set, else a clearly labelled **extractive fallback** that quotes
the source. `GENERATOR=groq|claude|extractive` forces one.

| Setting | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | unset | Free key from console.groq.com |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Free tier: 8K tokens/min, 200K tokens/day; one question ≈ 1.8–5K tokens |
| `ANTHROPIC_API_KEY` | unset | Claude (paid API) |
| `CLAUDE_MODEL` / `CLAUDE_EFFORT` | `claude-opus-5` / `medium` | |

Only the redacted question and the public excerpts are sent to the generator.

## Disclaimer (shown in the UI)

> Facts-only answers from official HDFC Mutual Fund, SEBI and AMFI pages. This is not investment advice. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.

The header also shows a pinned **"Facts-only. No investment advice."** note.

## Privacy

- **PII is blocked.** A message with a PAN, Aadhaar (Verhoeff-checked), phone number,
  email, OTP or account/folio number is stopped before anything else reads it; the
  user sees a safety message and the Groww help link. Nothing is sent to the
  generator, stored in the chat or logged.
- **Chat history and feedback stay in the browser session**, never on disk.
- **No telemetry** (Streamlit usage statistics and Chroma telemetry are off).

## Known limits

- **ELSS NAV:** the factsheet's PDF text lists two Direct Plan NAVs without the
  Growth / IDCW labels, so the answer states both and says which is which can't be
  read.
- **Flexi Cap's former name** (HDFC Equity Fund) is recognised as an alias, but no
  ingested official document states it, so "what was it called earlier?" is answered
  only for Large Cap (from its KIM).
- **Monthly figures:** NAV, holdings and the asset mix are "as on" the factsheet date;
  the expense ratio is "as on" the TER file date. Live NAV is out of scope.
- **Dated files need a monthly URL update** (checklist above); the daily link check
  reports newer editions.
- **Guards are pattern-based.** They are tuned on the golden set and lean towards
  refusing when a message might be advice; unusual phrasings can still slip through.
- **Offline fallback** (no API key) quotes source text; it is weaker than the LLM on
  multi-part questions.
- **Free Groq quota:** about 60–80 answered questions a day; a full golden-set run
  takes two days.
- **No PyTorch / grpcio on the dev machine** (Windows Application Control):
  embeddings run through ONNX Runtime, and `src/ingest/chroma_compat.py` stands in
  for Chroma's unused gRPC tracing module. Both are no-ops on Linux.
