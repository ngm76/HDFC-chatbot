# Mutual Fund FAQ RAG Chatbot

A small, facts-only FAQ assistant for five **HDFC Mutual Fund** schemes. It answers
from the five public **Groww** scheme pages named in the problem statement, using
retrieval-augmented generation (RAG). Each answer is at most three sentences, with
exactly one source link and a "last updated from sources" date. It refuses
investment advice, never computes or compares returns, and never stores personal
data.

Product spec: [docs/PRD.md](docs/PRD.md) · Design: [docs/architecture.md](docs/architecture.md)
· Build plan: [docs/implementation.md](docs/implementation.md)

## Scope

**AMC:** HDFC Mutual Fund. **Plans:** Direct Growth.

| Category | Scheme | Source page (ingested and cited) |
|---|---|---|
| Large cap | HDFC Large Cap Fund | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi cap | HDFC Flexi Cap Fund (formerly HDFC Equity Fund) | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small cap | HDFC Small Cap Fund | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Hybrid | HDFC Balanced Advantage Fund | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

**Source list:** [data/sources.csv](data/sources.csv).
- **`role=ingest`:** the five Groww pages above. These are the **only** documents in
  the vector database.
- **`role=reference`:** two official links that are never searched. The HDFC MF
  factsheet is the link on returns refusals, as the brief requires. AMFI's
  investor-education page is the link on out-of-scope refusals. Advice refusals
  carry no link (owner decision); they reply "I can only share facts from Groww
  scheme pages, so I can't recommend whether to buy, sell or choose a fund."

This follows [docs/problemstatement.txt](docs/problemstatement.txt), which names the
five Groww URLs as the pages to use. It supersedes PRD §5.2, which had treated them
as scoping seeds only.

**Answers:** anything the Groww page states, except performance content. That covers:
- expense ratio, exit load (current and history), minimum SIP / lump sum
- riskometer, benchmark, objective, fund size (AUM), NAV (with Groww's date)
- **holdings**: count, top 10, and the full list, e.g. "Does it hold Tata Steel?"
- **holdings analysis**: the asset-class mix (equity / debt / cash / other), the
  breakdown by instrument type, and sector allocation. Groww's page states no
  totals, only each holding's weight, so these are **sums of the listed weights,
  calculated at ingest** and labelled as such in the answer. This is portfolio
  arithmetic, not returns.
- fund managers, their profiles, and the other schemes they manage
- stamp duty and tax on redemption
- glossary definitions, e.g. "What is an expense ratio?"
- fund house details (custodian, address, incorporation, website, the AMC's total AUM)
- the registrar (CAMS)

**Left out on purpose:** Groww's returns, return calculator, rankings, "compare
similar funds" and star rating. The brief says "No performance claims" and to
refuse opinionated questions, so returns questions get the official-factsheet link.

**About the assistant:** questions like "Which funds can you access?" or "What
can you do?" get a fixed reply listing the five schemes and the facts covered
(`src/guards/about.py`). They don't go to retrieval, because no single page answers
them, so the reply has no single citation.

**Which fund?** A fact question that names no fund (e.g. "What is the expense
ratio?") gets a reply asking which of the five funds you mean (`src/guards/clarify.py`),
unless an earlier question in the chat already named one (see below).

**Conversation context (last 25 exchanges, `src/rag/context.py`).** Follow-ups work:
- "And its expense ratio?", "Who manages it?" and "Does it hold Tata Steel?"
  carry the fund over from earlier. The answer shows a "↪ Follow-up: assumed
  you mean …" note.
- "What about Large Cap?" reuses the previous question for the new fund.
- The model sees the recent exchanges only to understand the question. Facts
  still come from the cards retrieved for it, and the number check still applies.
- History holds redacted questions only, lives in the browser session, and is
  reset by "Clear chat".

**Companies a fund doesn't hold.** "Does HDFC Small Cap Fund hold Infosys?" gets a
definite answer ("Infosys is not among the 87 holdings listed for …") after an
exact check against the fund's full holdings list (`src/rag/holdings.py`).

**Refused:** buy/sell or "best fund" advice, returns or performance, other AMCs,
other HDFC schemes and products, and live data such as today's NAV or holdings.
**Not available** in the Groww pages, so the bot says so: ELSS lock-in, and how to
download statements (see Known limits).

## Setup

Requires **Python 3.11+** (developed on 3.12, Windows 11).

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then set ANTHROPIC_API_KEY (optional, see below)
```

### 1. Build the index

```powershell
python scripts/ingest.py            # load → chunk → embed → store; about 10 seconds
python scripts/ingest.py --refresh  # re-download the pages (Groww updates NAV daily)
```

This fetches every `role=ingest` URL (the five Groww pages) and caches raw files in
`data/raw/`.
- **Cleanup:** the loader strips Groww's site menus and footer, plus its returns,
  rankings, star rating and "compare similar funds" sections, which the brief
  rules out. Everything else on the page is kept.
- **Chunking:** each page is parsed into **fact cards**, one per field
  (`src/ingest/groww.py`), plus one "key facts" overview card per fund. Every
  card names its fund and records its field. For example: *"HDFC Small Cap Fund
  Direct Growth: Expense ratio (TER, total expense ratio): 0.78%."* The fields are:
  - NAV (with date), expense ratio, fund size (AUM), min SIP / lump sum
  - current exit load, exit-load history (labelled as earlier rules), stamp duty, tax
  - riskometer, benchmark, objective, fund managers and a profile for each
  - fund house and registrar (CAMS)
- **Storage:** it rebuilds the Chroma collection `hdfc_mf_faq` in `data/chroma/`
  (158 cards, including holdings, glossary and fund-house cards) and writes
  `fetched_at` back to `sources.csv`.
- **Retrieval** routes questions to the matching card type: fund size → AUM card,
  holdings → holdings cards, custodian → fund-house card, and so on. It also
  matches company names in holdings questions exactly against the fund's full
  holdings list. It rebuilds the Chroma collection `hdfc_mf_faq` in
`data/chroma/` and writes `fetched_at` back to `sources.csv`. The first run also
downloads the embedding model (about 90 MB).

### 2. Run the chat UI

```powershell
streamlit run src/app/main.py
```

The UI ("Mutual Funds FAQ") is styled like a modern investing app, under its own name and
colours (not affiliated with Groww):
- **Left panel:** pick a scheme. Questions that name no fund are then answered
  for it.
- **Fund cards:** live NAV (with date) and expense ratio for all five funds.
- **Fact sheet** for the selected fund: NAV, TER, AUM, min SIP, exit load,
  benchmark, managers, riskometer, asset mix bar and top holdings, with a source
  link.
- **Quick-question pills**, and chat bubbles with a source pill and the
  last-updated date.

Every figure comes from the same Chroma fact cards the chatbot answers from
(`src/rag/facts.py`), so cards, fact sheet and answers always agree and update
with each data refresh.

## Deploy on Render (free plan)

The repo includes a Render Blueprint ([render.yaml](render.yaml)) for one free web
service.

**How the data stays current.** Render's disk is temporary and free services have
no persistent disk or cron jobs, so the index is rebuilt on every deploy:

1. **Build:** `pip install -r requirements.txt && python scripts/ingest.py --refresh --strict`.
   This fetches the five Groww pages, downloads the embedding model into
   `.cache/` (inside the project, so it carries over to runtime) and builds Chroma.
2. **Safe refresh:** `--strict` fails the build if any page fails to load or lacks
   a core fact (NAV, TER, AUM, SIP, exit load, riskometer, benchmark, managers,
   holdings). Render then keeps serving the previous working deploy.
3. **Daily refresh:** [.github/workflows/refresh-data.yml](.github/workflows/refresh-data.yml)
   calls Render's deploy hook at 21:00 IST every day (free on GitHub Actions).
   That redeploys with fresh data, and it works while the free service is asleep.
4. **Staleness banner:** if the data is more than 3 days old, the app shows a warning.

**One-time setup**
1. Render: **New → Blueprint**, then pick this GitHub repo. Render reads `render.yaml`.
2. Enter **`GROQ_API_KEY`** when prompted. It's a secret and is never committed.
3. Render: the service → **Settings → Deploy Hook**. Copy the URL.
4. GitHub: repo → **Settings → Secrets and variables → Actions → New repository
   secret** named `RENDER_DEPLOY_HOOK_URL`, holding that URL.
5. Optional: GitHub → **Actions → Refresh fund data → Run workflow** to test it.

**Free-plan notes**
- **Memory:** peak about 305 MB (measured with the model, Chroma and Streamlit
  loaded) against the 512 MB limit.
- **Sleep:** the service sleeps after ~15 minutes idle. The first visit afterwards
  takes ~30–60 s while it wakes and loads the model.
- **Inactive repos:** GitHub pauses scheduled workflows in repos with no activity
  for 60 days. Re-enable it from the Actions tab.
- **Blocking:** if Groww blocks Render's servers, the strict build fails with a
  clear `STRICT:` message in the build log.
### Generator

The generator is picked automatically: **Claude** if `ANTHROPIC_API_KEY` is set,
otherwise **Groq** if `GROQ_API_KEY` is set, otherwise the **extractive fallback**.
The current setup uses **Groq's free tier with `openai/gpt-oss-120b`**.

| Setting | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | unset | Free key from console.groq.com (no card needed). |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Free-tier chat models: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. The Llama models are Enterprise-only (404 on a free key). |
| `ANTHROPIC_API_KEY` | unset | Claude (paid API; a Claude Pro plan does not include API credits). |
| `CLAUDE_MODEL` / `CLAUDE_EFFORT` | `claude-opus-5` / `medium` | |
| `GENERATOR` | auto | Force `groq`, `claude` or `extractive`. |

All generators follow the same contract:
- They answer only from the retrieved excerpts, in at most three sentences.
- They return which excerpt they used, and that excerpt becomes the one citation.

On Groq the request uses **strict JSON-schema output** and **low reasoning
effort**. On Claude, server-side refusal fallback (`fallbacks: "default"`) is
enabled. The code also enforces the three-sentence cap and rejects any answer
containing a number not present in the sources, showing a safe error instead.
With no key, a clearly labelled **extractive fallback** quotes up to three
sentences from the best-matching chunk. It is weaker (see
[docs/eval_notes.md](docs/eval_notes.md)).

**Groq free-tier limits** (as of Sept 2026; check the console for current values):
- 8,000 tokens per minute, and one question uses about 5–6k tokens, so asking
  twice within a minute can add a short wait. The app retries automatically.
- 200,000 tokens per day, which is about 35 questions.
- Questions (already PII-redacted) and the public excerpts are sent to Groq.

Embeddings use `sentence-transformers/all-MiniLM-L6-v2` (384-dim), run through its
official ONNX export with `onnxruntime` (see Known limits).

### Debug and evaluation scripts

| Command | What it shows |
|---|---|
| `python scripts/debug_retrieve.py -i` | Top chunks and scores for your questions |
| `python scripts/debug_guards.py` | 58 guard test cases (advice, performance, scope, PII, about-the-assistant, which-fund, holdings) |
| `python scripts/debug_ask.py "question"` | The JSON answer payload |
| `python scripts/debug_chat.py` | A scripted 8-turn conversation testing follow-ups (add `--no-llm` to skip Groq) |
| `python scripts/eval_gold.py` | 16-question gold evaluation against the Groww pages (add `--retrieval-only` to skip LLM calls) |
| `python scripts/eval_gold.py --matrix` | Every fund × field (50 questions): is the top result the right fund's right card? No LLM calls |
| `python scripts/make_sample_qa.py` | Regenerates [docs/sample_qa.md](docs/sample_qa.md) |
| `python scripts/dump_chunks.py` / `dump_embeddings.py` | Every chunk / vector as text in `data/debug/` |

## Disclaimer (shown in the UI)

> Facts-only answers from public scheme pages. This is not investment advice. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.

The UI also shows a persistent **"Facts-only. No investment advice."** note.

## Privacy

- **PII is redacted first.** PAN, Aadhaar, account/folio numbers, OTPs, emails and
  phone numbers are replaced (e.g. `[PAN]`) before anything else runs. The user is
  warned.
- **Nothing keeps the raw input.** Only the redacted question reaches retrieval,
  the generator, logs, or chat history.
- **Chat history stays in memory.** It lives in the browser session and is never
  written to disk. The last 25 exchanges (redacted questions and answers) are
  sent to the generator as context for follow-ups.
- **No telemetry.** Streamlit usage statistics are disabled in `.streamlit/config.toml`.

## Known limits

- **Claude generation not yet evaluated.** The evaluation and
  [docs/sample_qa.md](docs/sample_qa.md) use Groq (`openai/gpt-oss-120b`), since no
  paid Anthropic key was available. With a key, re-run `scripts/eval_gold.py` and
  `scripts/make_sample_qa.py` to compare.
- **Free-tier rate limits** (Groq): quick successive questions may pause while
  the app waits out the per-minute token cap. There is also a daily token budget.
- **Corpus gaps (Groww-only):**
  - Groww's pages don't state the **ELSS lock-in**, so the bot says it's not
    available.
  - For **statements**, the pages only name the registrar (CAMS, camsonline.com).
    The bot points there but can't give step-by-step download instructions.
  - Adding the official HDFC ELSS page and statement guide would close both gaps.
- **Evaluation** (see [docs/eval_notes.md](docs/eval_notes.md)):
  - Fund × field matrix: 50/50 top-1.
  - Gold set: 17/18 retrieved. The one miss is the ELSS lock-in gap above.
  - When a question is missed, the bot says so rather than guessing.
- **Holdings** are as listed on Groww at the last ingest. They change monthly, so
  re-run `ingest.py --refresh` to update them.
  - "Not among the N holdings listed" means not in Groww's list at the last ingest.
- **Custodians differ by scheme** on Groww (e.g. HDFC Bank for Large Cap, Citibank
  NA for Small Cap). Each answer uses the named fund's own page.
- **Groww data differs from HDFC's documents by date and basis.**
  - Example: Large Cap expense ratio is **1.03%** on Groww vs 0.98% (Direct) in
    HDFC's August factsheet.
  - Answers reflect Groww as of the last ingest.
  - The NAV carries Groww's date (e.g. "NAV: 25 Sep '26"). AUM has no date on the page.
- **One Groww sentence is dropped as wrong.** Groww's auto-generated "About"
  sentence states the AMC's total AUM (₹9.86 lakh Cr) as the fund's AUM and
  names only one manager. The loader drops that sentence and keeps the page's
  correct fields.
- **Live data is refused.** "NAV today" or "current AUM" gets a scope refusal.
  Plain "NAV" / "AUM" questions are answered from the last ingested snapshot.
- **Third-party source.** Groww re-publishes AMC data. The brief names these pages;
  `robots.txt` allows them. Downloads are five pages, cached in `data/raw/`.
- The problem statement's "HDFC Equity Fund" is today's HDFC Flexi Cap Fund
  (Groww's URL still uses the old name).
- **Guards are keyword/regex based.** They catch common phrasings but can miss
  unusual wording. The Claude prompt repeats the rules as a second layer. Some
  legitimate questions are refused, e.g. anything mentioning "insurance" or
  "returns".
- **No PyTorch.** Windows Application Control blocks PyTorch's DLLs on the
  development machine. Embeddings therefore run through ONNX Runtime with the same
  model and pooling, so no torch install is needed.
- **grpcio is blocked too (since 2026-09-30).** ChromaDB imports an OpenTelemetry
  gRPC exporter at startup, and that fails with *"DLL load failed while importing
  cygrpc"*.
  - The exporter is only used when ChromaDB tracing is enabled. It is off here.
  - `src/ingest/chroma_compat.py` registers a stand-in for that one module when the
    real one can't load. It is a no-op where grpcio works.
  - If tracing is ever enabled, the stand-in raises a clear error instead.
