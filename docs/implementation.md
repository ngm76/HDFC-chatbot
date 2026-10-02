# Implementation guide (phase-wise)

**Product:** Mutual Fund FAQ RAG Chatbot  
**Follow:** [architecture.md](./architecture.md) (source of truth for design)  
**Also:** [PRD.md](./PRD.md) (product rules)  
**How to use:** One phase per Cursor chat (or `/clear` between phases). Paste the **Cursor prompt** for that phase. Do not skip ahead. Do not implement later phases “while you’re at it.”

---

## Rules for every phase

- Stay inside the file list and acceptance checks for **this phase only**.  
- Ingest (`src/ingest/`) and retrieve (`src/rag/`) stay **separate packages**.  
- Public AMC / SEBI / AMFI URLs are citations; Groww URLs are scheme **seeds** only unless architecture known-limit applies.  
- No live web agent on each user query.  
- No PII stored. No returns math. No investment advice.  
- Python 3.11+, `sentence-transformers/all-MiniLM-L6-v2`, ChromaDB, tiny Streamlit or Gradio UI (choose Streamlit unless told otherwise).  
- Generator: use an env var (e.g. `OPENAI_API_KEY` or local model); document the choice in README only in **Phase 10**. Until then, a stub generator is OK where noted.

---

## Phase map

| Phase | Name | RAG stage | Depends on |
| --- | --- | --- | --- |
| 0 | Repo scaffold | — | — |
| 1 | Source registry | Ingestion prep | 0 |
| 2 | Loading | Load | 1 |
| 3 | Chunking | Chunk | 2 |
| 4 | Embed + Chroma | Embed + store | 3 |
| 5 | Ingest CLI | Wire ingestion | 4 |
| 6 | Retrieval | Retrieve | 5 |
| 7 | Guards | App safety | 0 (can parallel after 0; wire in 8) |
| 8 | Generate + assemble | Generate | 6, 7 |
| 9 | UI | Query path | 8 |
| 10 | Deliverables + eval | Milestone wrap | 9 |

Suggested Cursor sequence: **0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10**.  
Phase 7 may be implemented right after Phase 0 if you want guards done before RAG, but **do not wire them into the chat path until Phase 8**.

---

## Phase 0 — Repo scaffold

**Goal:** Empty Python app layout, dependencies, gitignore. No fetching, no Chroma, no UI logic.

**Create**

- `README.md` (title + “setup coming in Phase 10” only)  
- `requirements.txt`  
- `.gitignore` (`data/chroma/`, `data/raw/`, `.venv/`, `__pycache__/`, `.env`)  
- `.env.example` (`OPENAI_API_KEY=` or whichever generator you pick later)  
- Packages: `src/ingest/`, `src/rag/`, `src/guards/`, `src/app/` with `__init__.py`  
- `scripts/` folder  

**Do not:** ingest data, write loaders, Streamlit app, or sample Q&A content.

### Cursor prompt — Phase 0

```
Implement Phase 0 only from docs/implementation.md, following docs/architecture.md §10–§11.

Create a Python 3.11+ project scaffold for a local RAG chatbot:
- requirements.txt with placeholders we will use later: httpx, beautifulsoup4, pypdf, sentence-transformers, chromadb, streamlit, python-dotenv
- .gitignore for venv, chroma, raw cache, .env, pycache
- .env.example
- Empty packages: src/ingest, src/rag, src/guards, src/app (each with __init__.py)
- scripts/ empty except a .gitkeep if needed
- README.md: project name “Mutual Fund FAQ RAG Chatbot” and say full setup is Phase 10

Do not implement loading, chunking, embeddings, Chroma, guards, or UI.
Stop when the tree exists and pip-install would work for listed packages.
```

**Done when**

- [ ] Layout matches architecture §10  
- [ ] No ingestion or chat code yet  

---

## Phase 1 — Source registry

**Goal:** Curated URL list for the five HDFC schemes. Official pages for ingest; Groww listed as seeds.

**Create**

- `data/sources.csv` columns: `url`, `scheme`, `doc_type`, `role` (`seed` | `ingest`), `fetched_at` (empty until ingest)  
- `data/schemes.md` — the five schemes + Groww seed URLs from the PRD  
- Allowed `doc_type` values: `factsheet`, `kim`, `sid`, `faq`, `charges`, `riskometer`, `statement_guide`  
- At least one **ingest** URL per scheme from official HDFC AMC / AMFI / SEBI (factsheet or KIM/SID/FAQ). Plus one statement/tax-doc **official** guide if available.  
- One stable **educational** official URL for advice refusals (AMFI investor education or similar).  

**Do not:** fetch pages or parse HTML yet.

### Cursor prompt — Phase 1

```
Implement Phase 1 only from docs/implementation.md. Read docs/architecture.md §2, §9 and docs/PRD.md §5.

Create data/schemes.md listing the five HDFC schemes and their Groww seed URLs (role=seed, not for citation).

Create data/sources.csv with columns: url, scheme, doc_type, role, fetched_at
- role=seed for the five Groww URLs
- role=ingest for official HDFC AMC / SEBI / AMFI pages only (factsheets, KIM/SID, FAQs, charges, riskometer/benchmark, statement guides)
- Include at least one ingest URL per scheme
- Include one official statement/capital-gains download guide if publicly available
- Include one official educational URL for advice-refusal (document which row)

Do not fetch or download. Do not write loaders. Look up real public official URLs; if a page cannot be confirmed, mark it in a “known gaps” note in data/schemes.md rather than inventing a URL.
```

**Done when**

- [ ] Five seeds + ingest rows with real official URLs  
- [ ] CSV is the only input the loader will read later  

---

## Phase 2 — Loading

**Goal:** Fetch and parse registry URLs (`role=ingest` only) into normalized documents.

**Create**

- `src/ingest/load.py`  
- Optional cache under `data/raw/` (gitignored)  
- Function: `load_documents(sources_csv) -> list[Document]` each with `text`, `url`, `scheme`, `doc_type`, `fetched_at`  
- HTML: extract main text, strip nav  
- PDF: extract text  
- Skip `role=seed`  
- Skip empty fetches; log failures (do not crash the whole run unless all fail)  
- Allowed domains only (hdfcfund / sebi / amfi and others you listed as official in Phase 1)

**Do not:** chunk, embed, or write Chroma.

### Cursor prompt — Phase 2

```
Implement Phase 2 only from docs/implementation.md. Follow docs/architecture.md §4.1 Loading and §3 Loader.

Write src/ingest/load.py:
- Read data/sources.csv
- Fetch only rows with role=ingest
- Parse HTML (main content) or PDF
- Return documents with text, url, scheme, doc_type, fetched_at (ISO date)
- Cache raw bytes under data/raw/ keyed by URL hash
- On fetch failure: skip that URL, collect errors; never index empty text
- Do not fetch Groww seed URLs

No chunking, embeddings, or Chroma. Add a tiny `if __name__` or pytest that loads one URL and prints char count (optional).
```

**Done when**

- [ ] At least one official HTML or PDF yields non-empty text locally  
- [ ] Seeds are never fetched  

---

## Phase 3 — Chunking

**Goal:** Split documents per architecture §5.

**Create**

- `src/ingest/chunk.py`  
- Recursive + heading-aware split  
- ~400–800 tokens (use ~1,600–3,200 characters as proxy), 10–15% overlap  
- Separators: `\n## `, `\n# `, `\n\n`, `\n`, `. `, space  
- Tables: keep fee tables in one chunk when possible; if split, repeat headers  
- Each chunk metadata: `chunk_id` (hash of url + start offset), `url`, `scheme`, `doc_type`, `section_title`, `fetched_at`, `amc=HDFC`

**Do not:** embed or store.

### Cursor prompt — Phase 3

```
Implement Phase 3 only from docs/implementation.md. Follow docs/architecture.md §5 exactly.

Write src/ingest/chunk.py that takes loaded documents and returns chunks with text + metadata:
chunk_id, url, scheme, doc_type, section_title, fetched_at, amc=HDFC

Use heading-aware recursive character split, 1600–3200 chars, 10–15% overlap, separators as in architecture §5.
Preserve table cohesion for expense ratio / SIP / exit load sections.

No embeddings or Chroma. Include a small debug print: chunk count per URL.
```

**Done when**

- [ ] Chunks have all metadata fields  
- [ ] Typical factsheet is not a single giant chunk and not sentence-shredded  

---

## Phase 4 — Embedding + Chroma store

**Goal:** MiniLM embeddings persisted in Chroma.

**Create**

- `src/ingest/embed.py` — `sentence-transformers/all-MiniLM-L6-v2`, 384-dim; reuse one model instance  
- `src/ingest/store.py` — persistent Chroma at `data/chroma/`, collection `hdfc_mf_faq`  
- Idempotent rebuild: delete collection or upsert by `chunk_id`  
- Store documents, embeddings, metadatas, ids=`chunk_id`

**Do not:** query-path retriever or LLM.

### Cursor prompt — Phase 4

```
Implement Phase 4 only from docs/implementation.md. Follow docs/architecture.md §4.1 Embedding and Store, §11.

Write src/ingest/embed.py using sentence-transformers/all-MiniLM-L6-v2.
Write src/ingest/store.py: Chroma persistent client, path data/chroma/, collection hdfc_mf_faq.
Rebuild must be idempotent (wipe or upsert by chunk_id).
Do not implement the user-query retriever yet (that is Phase 6).
Do not call an LLM.
```

**Done when**

- [ ] Can write a few dummy chunks and reopen Chroma from disk  
- [ ] Collection name and path match architecture  

---

## Phase 5 — Ingest CLI (wire ingestion)

**Goal:** One command runs Loading → Chunking → Embedding → Store and updates `fetched_at` in the source list.

**Create**

- `scripts/ingest.py`  
- Orchestrate `load → chunk → embed → store`  
- Update `data/sources.csv` `fetched_at` for successful URLs  
- Print summary: URLs ok/fail, chunk count  
- README one-liner: `python scripts/ingest.py` (full README still Phase 10)

**Do not:** chat UI or generation.

### Cursor prompt — Phase 5

```
Implement Phase 5 only from docs/implementation.md. Follow docs/architecture.md §4.1 full pipeline.

Write scripts/ingest.py that runs load → chunk → embed → store from existing src/ingest modules.
Rebuild Chroma idempotently.
Update fetched_at in data/sources.csv for successful ingest URLs.
Print a summary. Do not add Streamlit or RAG query code.
After implementing, run ingest once if network allows; if fetch fails, document failed URLs in the summary output.
```

**Done when**

- [ ] `python scripts/ingest.py` produces a non-empty `hdfc_mf_faq` collection  
- [ ] Both RAG **ingestion** stages exist as code, not comments  

---

## Phase 6 — Retrieval

**Goal:** Query embedding + top-k from Chroma (+ optional scheme filter).

**Create**

- `src/rag/retrieve.py`  
- Same MiniLM model as ingest  
- `k=5` (config constant; comment that 3–8 is allowed)  
- Similarity floor: if top distance/score is too weak, return empty (tune constant; document it)  
- If query names one of the five schemes, Chroma `where` filter on `scheme`  
- If two schemes named: no filter (or two searches); never compare returns here  
- Return list of `{text, url, section_title, scheme, fetched_at, score}`

**Do not:** LLM generate or UI.

### Cursor prompt — Phase 6

```
Implement Phase 6 only from docs/implementation.md. Follow docs/architecture.md §4.2 and §6.

Write src/rag/retrieve.py:
- Embed the query with the same MiniLM model as ingest
- Query Chroma collection hdfc_mf_faq, k=5
- Apply scheme metadata filter when the query names one of the five HDFC schemes
- If similarity is below a documented floor, return no chunks
- Return chunk text + url + section_title + scheme + fetched_at + score

Add a small scripts/debug_retrieve.py that prints top chunks for:
“What is the expense ratio of HDFC Large Cap Fund Direct Growth?”

No LLM and no Streamlit.
```

**Done when**

- [ ] Debug retrieve prints real chunks with official `url`s after ingest  
- [ ] Empty result path exists for weak scores  

---

## Phase 7 — Guards

**Goal:** Deterministic advice / performance / PII / out-of-scope checks.

**Create**

- `src/guards/advice.py`  
- `src/guards/performance.py`  
- `src/guards/pii.py`  
- `src/guards/scope.py` (other AMC / holdings)  
- `src/guards/pipeline.py` — ordered: PII warn+redact → advice → performance → scope → `allow`  
- Return the same answer payload shape as architecture §7 (`text`, `source_url`, `last_updated_from_sources`, `refusal`, `refusal_reason`)  
- Advice: polite facts-only + educational official URL from sources.csv  
- Performance: no compute; factsheet URL for named scheme or AMC hub  
- PII: regex for PAN, Aadhaar, account-like numbers, OTP, email, phone; **never log raw**; redact before any debug print  

**Do not:** call retriever or LLM.

### Cursor prompt — Phase 7

```
Implement Phase 7 only from docs/implementation.md. Follow docs/architecture.md §8 and §7 payload.

Create src/guards/advice.py, performance.py, pii.py, scope.py, and pipeline.py.
Order: PII (warn, redact, do not store) → advice refusal → performance (no returns math, factsheet link) → out of corpus → allow.

Use the educational URL and factsheet URLs from data/sources.csv.
Return dict: text, source_url, last_updated_from_sources, refusal, refusal_reason.

Add tests or a small scripts/debug_guards.py covering:
- “Should I buy HDFC Small Cap?”
- “Which fund had better returns?”
- A message containing a fake PAN-like string (ensure it is not printed in full)

Do not call Chroma or an LLM.
```

**Done when**

- [ ] Advice never yields a recommendation  
- [ ] PII is not printed or written to disk  

---

## Phase 8 — Generate + assemble

**Goal:** Grounded generation and the public answer contract.

**Create**

- `src/rag/generate.py` — system prompt from architecture §7; context = retrieved chunks with url/section prefixes; max 3 sentences; no advice; no numbers not in context  
- `src/rag/assemble.py` — one `source_url` (best supporting chunk); `last_updated_from_sources` = max `fetched_at` of chunks sent to the generator  
- `src/rag/pipeline.py` — guards first; if allow → retrieve → if empty/weak miss message + optional hub URL → else generate → assemble  
- Weak retrieval: “not in this prototype,” no invented fees  
- Generator errors: generic safe error, no partial fake fee  
- Config: model name via env; if no API key, a **dev fallback** that extracts a short quote from top chunk **clearly labeled as extractive fallback** (still 3 sentences max, still one citation)

### Cursor prompt — Phase 8

```
Implement Phase 8 only from docs/implementation.md. Follow docs/architecture.md §4.2, §7, §12.

Write src/rag/generate.py (grounded LLM, context-only, ≤3 sentences).
Write src/rag/assemble.py (exactly one citation URL; last_updated_from_sources from chunk fetched_at).
Write src/rag/pipeline.py: guards → retrieve → generate → assemble.
Miss/low similarity: do not guess. LLM failure: safe error.

Use env for the generator; document the env var in a comment. If no key, extractive fallback from top chunk (still one URL).

Do not build Streamlit yet. Provide scripts/debug_ask.py that prints the JSON payload for 2 factual questions and 1 advice question.
```

**Done when**

- [ ] Factual ask returns `text` + one official URL + last-updated  
- [ ] Advice ask is a refusal without retrieval-based recommendation  
- [ ] Payload matches architecture §7  

---

## Phase 9 — Tiny UI

**Goal:** Streamlit chat matching PRD UX.

**Create**

- `src/app/main.py`  
- Welcome line  
- Three example questions (clickable) from PRD appendix  
- Persistent note: **Facts-only. No investment advice.**  
- Disclaimer snippet visible (PRD §6.3 intent)  
- Input → `src/rag/pipeline.py`  
- Show answer body, source link, last-updated  
- Session-only chat; no PII persistence  
- `streamlit run src/app/main.py`

**Do not:** extra pages, auth, or analytics.

### Cursor prompt — Phase 9

```
Implement Phase 9 only from docs/implementation.md. Follow docs/architecture.md §3 UI and docs/PRD.md §6.

Create src/app/main.py Streamlit app:
- Welcome line
- Three example questions (PRD appendix) that fill/submit the question
- Always-visible: “Facts-only. No investment advice.”
- Disclaimer: facts-only, not investment advice, MF subject to market risks, read scheme documents
- Chat that calls src/rag/pipeline.py
- Render text, one source URL, “Last updated from sources: …”
- Session memory only; do not write chats to disk

No new RAG features. No extra multi-page app.
```

**Done when**

- [ ] UI matches FR8  
- [ ] Example question produces a cited answer after ingest  

---

## Phase 10 — Deliverables, README, eval

**Goal:** Milestone wrap + first retrieval eval; tune chunking only with evidence.

**Create / update**

- `README.md` — setup, Python version, `python scripts/ingest.py`, `streamlit run …`, AMC + five schemes, generator model name, known limits (failed URLs, Groww vs official, stale factsheets)  
- `data/sources.csv` final (the “source list”)  
- `docs/sample_qa.md` — 5–10 queries with assistant answers + links (run the pipeline; do not invent)  
- Disclaimer text used in UI copied into README  
- Gold eval notes: expense ratio, SIP, lock-in, exit load, riskometer/benchmark, statement download — pass/fail vs cited page  
- If tables retrieve badly: **only then** adjust chunker per architecture §5; record what changed  

**Do not:** new AMCs, hybrid search, reranker, or live browse unless gold set fails and architecture allows reranker as last resort.

### Cursor prompt — Phase 10

```
Implement Phase 10 only from docs/implementation.md. Follow docs/PRD.md §11 and docs/architecture.md §12–§14.

1. Rewrite README.md: setup steps, HDFC + five schemes, how to ingest and run UI, generator choice, known limits.
2. Run the pipeline (or use last known outputs) to write docs/sample_qa.md with 5–10 real Q&As including source links. Include at least one advice refusal.
3. Confirm disclaimer in UI matches README.
4. Add docs/eval_notes.md: gold questions vs retrieved fact; note chunking changes only if needed.

Do not add features beyond eval/docs. Do not expand corpus to other AMCs.
```

**Done when**

- [ ] README, source list, sample Q&A, disclaimer, known limits exist  
- [ ] Gold set reviewed; chunking changed only if retrieval failed  

---

## Copy-paste cheat sheet

| You say to Cursor | Meaning |
| --- | --- |
| `Implement Phase N only from docs/implementation.md` | Scope lock |
| `Follow docs/architecture.md` | Design lock |
| `Do not start Phase N+1` | Stop condition |

If a phase fails (e.g. official PDF blocked), stay in that phase: fix loader/registry, list the gap, then continue. Do not skip to UI with an empty index.

---

## Definition of “implementation complete”

All of:

1. Ingest CLI rebuilds Chroma from `data/sources.csv`.  
2. Chat UI answers in-scope facts with ≤3 sentences, one official link, last-updated.  
3. Advice and returns questions are refused in **code** (guards), not only in the prompt.  
4. README + sample Q&A + source list + disclaimer match the PRD deliverables.
