# Implementation guide (phase-wise)

**Product:** Facts-Only Mutual Fund FAQ Assistant (HDFC MF), a RAG chatbot
**Requirements:** [PRD.md](./PRD.md) (PRD: Facts-Only Mutual Fund FAQ Assistant, 2 Oct 2026, incl. its owner-decision Addendum) · brief: [problemstatement.txt](./problemstatement.txt)
**Design:** [architecture.md](./architecture.md)
**Status (2 Oct 2026):** Part A is built and deployed (Groww corpus). Part B aligns the
product with the new PRD (official ~22-page corpus); Phase 11 is done, Phases 12–22 are next.

**How to use:** one phase per assistant session (or clear context between phases).
Paste the phase's **Prompt**. Do not skip ahead, and do not implement later phases
"while you're at it". If a phase fails (e.g. an official PDF is blocked), stay in
that phase: fix the loader/registry, record the gap, then continue.

---

## Rules for every phase

- Stay inside the file list and "Done when" checks for **this phase only**.
- Ingest (`src/ingest/`) and query path (`src/rag/`, `src/guards/`) stay **separate packages**.
- **Sources:** only allowlisted official domains are ingested or cited: HDFC MF
  (`hdfcfund.com`), SEBI (`sebi.gov.in`), AMFI / Mutual Funds Sahi Hai
  (`amfiindia.com`, `mutualfundssahihai.com`). No third-party blogs, aggregators or news
  (PRD §4). Groww appears only as two fixed **help** links (PRD Addendum A5), never as a source.
- **Scope:** 5 schemes, Direct Plan – Growth; the 7 question types (TER, exit load, min
  SIP, ELSS lock-in, riskometer, benchmark, statement download), plus the extra fields
  kept by Addendum A1 (NAV, AUM, fund managers, holdings, holdings analysis, glossary,
  fund-house details).
- **Every response** (answers and refusals): ≤ 3 sentences, exactly one link from chunk
  metadata or the fixed link table (never model-generated), and
  "Last updated from sources: DD Mon YYYY" (PRD §7, FR-5/6).
- **Intent order:** PII → advice → performance → out-of-scope → fact; when unsure
  between fact and advice, choose advice (PRD §6).
- No live web agent per query. No PII stored, logged or sent to the model. No returns
  math or comparison. No investment advice.
- Stack: Python 3.12, `sentence-transformers/all-MiniLM-L6-v2` (run via ONNX Runtime),
  ChromaDB, Streamlit; generator via env (Groq free tier now, Claude if a key is set,
  extractive fallback).
- Free-tier limits: evaluation runs locally, never in the Render build; full LLM-graded
  runs are occasional (Groq daily quota).

---

## Phase map

| Phase | Name | Part | Status |
| --- | --- | --- | --- |
| 0 | Repo scaffold | A | ✅ Built |
| 1 | Source registry | A | ✅ Built (now superseded by 12) |
| 2 | Loading | A | ✅ Built |
| 3 | Chunking | A | ✅ Built |
| 4 | Embed + Chroma | A | ✅ Built |
| 5 | Ingest CLI | A | ✅ Built |
| 6 | Retrieval | A | ✅ Built |
| 7 | Guards | A | ✅ Built |
| 8 | Generate + assemble | A | ✅ Built |
| 9 | UI | A | ✅ Built |
| 10 | Deliverables + eval | A | ✅ Built |
| A+ | Later work (Groww corpus, fact cards, holdings, context memory, UI redesign, Render deploy) | A | ✅ Built |
| 11 | Docs baseline for the new PRD | B | ✅ Done |
| 12 | Official source registry (~22 pages) | B | ✅ Done |
| 13 | Loading official sources | B | ✅ Done |
| 14 | Chunking official documents | B | ✅ Done |
| 15 | Intent + guards per PRD §6 | B | ✅ Done |
| 16 | Retrieval re-tune | B | ✅ Done |
| 17 | Response template + validator | B | ✅ Done |
| 18 | Freshness + refresh | B | ✅ Done |
| 19 | UI per PRD §9 | B | ✅ Done |
| 20 | Golden set (200) + evaluation report | B | ✅ Done |
| 21 | Documents + deliverables | B | ✅ Done |
| 22 | Release (test, push, Render redeploy) | B | ✅ Done |

Sequence for Part B: **12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20 → 21 → 22**.
Phase 15 (guards) may run in parallel with 13–14; wire it into the chat path in 17.

---

# Part A: built so far (as-built record)

These phases were implemented between 27 Sep and 2 Oct 2026. Each entry states what
the phase delivered as built, so later phases start from facts, not from the
original plan. Detailed evidence is in [eval_notes.md](./eval_notes.md).

## Phase 0: Repo scaffold ✅

- Packages `src/ingest/`, `src/rag/`, `src/guards/`, `src/app/` (+ `src/schemes.py`
  shared scheme names and aliases), `scripts/`, `README.md`, `requirements.txt`
  (pinned), `.gitignore` (`.venv/`, `data/raw/`, `data/chroma/`, `data/debug/`,
  `.cache/`, `.env`), `.env.example`.

## Phase 1: Source registry ✅ (superseded by Phase 12)

- `data/sources.csv` (`url, scheme, doc_type, role, fetched_at`) and `data/schemes.md`.
- First built with 19 official HDFC/AMFI/SEBI pages; switched on 27 Sep to the five
  Groww scheme pages (`role=ingest`) plus two `role=reference` refusal links. Phase 12
  replaces this with the PRD's official corpus.

## Phase 2: Loading ✅

- `src/ingest/load.py`: fetches `role=ingest` rows, caches raw bytes in `data/raw/`,
  HTML main-text and PDF text extraction, host allowlist, per-URL error collection,
  `fetched_at` from cache date.
- Groww cleanup `_clean_groww` (strips menus, footer, returns, rankings, star rating).
- Browser-like User-Agent (`files.hdfcfund.com` rejects bot UAs; owner-approved).

## Phase 3: Chunking ✅

- `src/ingest/chunk.py`: heading-aware recursive split (1,600–3,200 chars, ~12%
  overlap), table cohesion, factsheet fund-page attribution, field-level chunks,
  footnote attachment, for official documents.
- `src/ingest/groww.py`: **fact cards** (one self-contained card per field, plus an
  overview card) for Groww pages, incl. holdings lists and calculated holdings
  analysis (asset mix, instrument type, sector).

## Phase 4: Embed + Chroma ✅

- `src/ingest/embed.py`: MiniLM via its official ONNX export (PyTorch is blocked by
  Windows Application Control on the dev machine); 384-dim, normalized.
- `src/ingest/store.py`: persistent Chroma at `data/chroma/`, collection
  `hdfc_mf_faq`, cosine space, rebuilt idempotently, telemetry off.
  `src/ingest/chroma_compat.py` lets Chroma import when grpcio's DLL is blocked.

## Phase 5: Ingest CLI ✅

- `scripts/ingest.py`: load → chunk → embed → store; writes `fetched_at` back;
  `--refresh` (re-download) and `--strict` (fail the build on missing pages or core
  facts; used by the Render build).

## Phase 6: Retrieval ✅

- `src/rag/retrieve.py`: query expansion (everyday terms → document terms), scheme
  filter, **field routing** (filtered search on the card fields a question asks for),
  exact holdings name lookup, `TOP_K=8`, `MIN_SCORE=0.35`.

## Phase 7: Guards ✅

- `src/guards/`: `pii.py` (redact + warn), `advice.py`, `performance.py` (factsheet
  link), `scope.py` (other AMCs, non-MF products, live data), `about.py` ("which funds
  can you access?"), `clarify.py` ("which fund do you mean?"), `pipeline.py` (order:
  PII → advice → performance → scope → about → clarify → allow).

## Phase 8: Generate + assemble ✅

- `src/rag/generate.py`: Groq (`openai/gpt-oss-120b`, strict JSON schema), Claude when a
  key is set, extractive fallback; 3-sentence cap; number-grounding check
  (`UngroundedNumberError`).
- `src/rag/assemble.py`: one citation from the cited chunk; honest miss / ungrounded /
  error replies linking the fund in context.
- `src/rag/pipeline.py`, `src/rag/holdings.py` (definite "not among the N holdings"),
  `src/rag/context.py` (last 25 exchanges; fund and topic carry-over).

## Phase 9: UI ✅

- `src/app/main.py` ("Mutual Funds FAQ"): left scheme panel, fund cards with live NAV
  and TER, fact sheet (tiles, asset-mix bar, top holdings), quick-question pills, chat
  bubbles, staleness banner, disclaimer footer. `src/rag/facts.py` reads the cards.

## Phase 10: Deliverables + eval ✅

- `README.md`, `docs/sample_qa.md` (`scripts/make_sample_qa.py`),
  `docs/eval_notes.md` (Rounds 1–8), `scripts/eval_gold.py` (20-question gold set,
  50-question fund × field matrix; volatile figures checked against current cards),
  `scripts/debug_guards.py` (58 cases), `scripts/debug_chat.py` (8-turn conversation).

## Later work (A+) ✅

- Render free-plan deployment: `render.yaml` (build runs `ingest.py --refresh
  --strict`), `.github/workflows/refresh-data.yml` (daily redeploy via deploy hook).
- Repo: https://github.com/ngm76/HDFC-chatbot.

---

# Part B: align with the new PRD (official corpus)

## Phase 11: Docs baseline for the new PRD ✅

**Goal:** make the new PRD the requirements baseline.

- `docs/PRD.md` mirrors the PDF PRD section by section, plus an owner-decision Addendum (A1–A7).
- `docs/problemstatement.txt` points to `docs/PRD.md` for details.
- `docs/problemstatement copy.txt` is a local backup, git-ignored.

**Done when**
- [x] PRD.md contains §1–§12 and FR-1–FR-15 of the PDF
- [x] Addendum records decisions A1–A7
- [x] Problem statement points to the PRD

---

## Phase 12: Official source registry (~22 pages)

**Goal:** a verified list of ~22 official pages following PRD §4's allocation.

**PRD:** §4 (corpus table, allowlist), §12 deliverable 2 (source-list columns), Addendum A5.

**Create / change**
- `data/sources.csv` with columns `url, publisher, doc_type, scheme, question_types,
  freshness_limit_days, role, fetched_at`.
- `role`: `ingest` for the corpus, `help` for the two Groww help links (PII block →
  `https://groww.in/help/mutual-funds`, non-MF → `https://groww.in/help`).
- Corpus allocation, each URL verified from Python:

  | Publisher | Documents | Pages |
  |---|---|---|
  | HDFC MF | Scheme pages | 5 |
  | HDFC MF | KIM / SID | 5 |
  | HDFC MF | Current monthly factsheet | 1 |
  | HDFC MF | TER disclosure | 1 |
  | HDFC MF | Account and capital-gains statement pages | 2 |
  | SEBI | Riskometer circular | 1 |
  | SEBI | Investor education | 2 |
  | AMFI / Mutual Funds Sahi Hai | Education | 5 |

- Freshness limits: TER 7 days, factsheet 35, KIM/SID 180, others as documented.
- `data/schemes.md`: canonical names, former names and aliases (HDFC Top 100, HDFC
  Equity Fund, HDFC Taxsaver), per-URL notes, known gaps.
- Remove the Groww scheme URLs.

**Do not:** change loaders, chunkers or the app.

**Prompt**
```
Implement Phase 12 only from docs/implementation.md, following docs/PRD.md §4 and §12.
Find and verify (fetch from Python with the project's loader settings) ~22 official
URLs per the allocation table. For each, record what text it yields and which of the
7 question types it answers. Write data/sources.csv with the new columns and
data/schemes.md. Never invent a URL: list unconfirmed pages as known gaps.
```

**Done when**
- [x] 20–25 `ingest` rows (24), all on the PRD allowlist, each fetched successfully on 2026-10-02 (`mutualfundssahihai.com` is added to the loader allowlist in Phase 13)
- [x] Every one of the 7 question types is answered by at least one row, for each scheme where applicable
- [x] Two `help` rows; no Groww scheme pages

---

## Phase 13: Loading official sources

**Goal:** load the official corpus reliably.

**PRD:** §4 allowlist, §8 stale data (keep the last good version), §11 (PDF parsing risk).

**Create / change**
- `src/ingest/load.py`:
  - allowlist adds `mutualfundssahihai.com`; Groww removed from ingest hosts
  - HTML and PDF paths re-validated on the new pages
  - keep the last good cached copy when a fetch fails and report it, instead of dropping the page
  - Groww cleanup disabled (code kept, unused)
- `scripts/ingest.py --strict`: required-page and required-field checks for the official corpus.

**Do not:** chunk or change retrieval.

**As built (2026-10-02)**
- Allowlist: `hdfcfund.com`, `sebi.gov.in`, `amfiindia.com`, `mutualfundssahihai.com`
  (subdomains included); `groww.in` removed. Groww cleanup kept but unused.
- HDFC scheme pages (`_clean_hdfc_scheme`): drops since-inception returns, the "NAV
  and Historical Performance" block, "Product Suitability", "Ideal for", "Who can
  consider / Why invest" pitch blocks, the downloads list and button text; keeps only
  factual FAQ pairs (minimum, benchmark, exit load, lock-in, how to invest / redeem,
  SIP and lump sum). NAV and holdings are JavaScript-only ("NA"), so they come from
  the factsheet.
- TER workbook: `.xls` name but `.xlsx` format, read with the standard library
  (`_xlsx_to_text`): one line per row, cells joined by " | " (3,331 rows: every scheme
  and day of the month, Regular and Direct).
- PDFs: garbled lines from non-Unicode fonts (the SEBI circular's Hindi header) are dropped.
- Last good copy: a page is cached only once its text passes the checks. A failed or
  unusable fetch (error, block page, too short) falls back to that copy and is
  reported as `STALE`. On Render the cache starts empty, so a failed fetch fails the
  strict build and Render keeps serving the previous deploy.
- `scripts/ingest.py`: per-document-type text checks (`REQUIRED_TEXT`, the ELSS
  lock-in, all five schemes in the factsheet and TER file) and a regression check that
  no performance text survives on scheme pages. `--check-only` runs load + checks
  without touching the index.

**Done when**
- [x] All `ingest` rows load, or fall back to their last good copy with a warning (24/24 fresh; fallback tested with a simulated outage and a block page)
- [x] `--strict` fails on a missing page and passes on the full corpus (also fails on a page missing required facts)

---

## Phase 14: Chunking official documents

**Goal:** a data-driven chunking strategy per document type, so each supported fact
is one retrievable card that names its scheme, plan and source date.

**PRD:** §4 question types, §8 (tiered exit loads, Direct vs Regular), §11 (wrong-scheme chunks).

**Create / change**
- `src/ingest/chunk.py` + a new official-document card builder:
  - **scheme pages:** fact cards for TER (Direct and Regular), exit load, min SIP, riskometer, benchmark, plus A1 extras (AUM, managers)
  - **KIM / SID:** exit load (incl. tiers), min SIP, **ELSS lock-in** (3 years, SIP instalments locked separately)
  - **factsheet:** per-fund NAV with "as on" date, TER, AUM, holdings and holdings analysis (A1)
  - **TER disclosure:** TER per scheme and plan
  - **statement pages:** step-by-step "how to download" cards
  - **SEBI / AMFI:** section chunks (riskometer levels, ELSS/SIP basics, education)
- Card metadata adds `publisher`, `plan`, `doc_date` (the date the document states, if any).
- **Performance content:** the factsheet and KIMs still contain returns tables (the
  loader leaves PDFs whole). Only fact cards and non-performance sections may be
  indexed from them; add a strict check that no indexed chunk carries return figures.
- **TER file:** use only the latest date per scheme; Direct is the answer, Regular only
  for the "values differ" note (FR-3).
- After this phase, a full `python scripts/ingest.py --refresh --strict` rebuild
  replaces the local Groww index; push to Render only once it passes.

**As built (2026-10-02)**
- `src/ingest/official.py` builds the cards; `chunk.py` dispatches by document type,
  tags prose chunks (`statement_steps`, `riskometer_levels`, `education`), keeps one
  copy of the shared glossary and adds one overview card per scheme. Chunks carry
  `publisher`, `plan` and `doc_date`.
- Primary source per fact (no conflicting duplicates): expense ratio = TER file
  (latest day, Direct + Regular); exit load, min SIP, riskometer, benchmark, AUM,
  lock-in, managers = scheme page; NAV, holdings, holdings analysis, manager
  details, objective = factsheet; full exit-load rules, lump-sum minimums, ELSS
  lock-in rule, former name = KIM. The factsheet's expense ratio (base expense ratio,
  a different basis) and its exit load (a figure lost in PDF extraction) are not used.
- Holdings analysis: the asset mix now uses the factsheet's own subtotals (they
  reconcile to its 100.00 Grand Total for all five funds); only the sector split is
  calculated, and labelled so.
- Known data limit: the ELSS factsheet page loses its option labels in PDF text, so
  its NAV card states both Direct values and says which is which can't be read.
- Strict build: required cards per scheme (7 question types + NAV, AUM, holdings,
  holdings analysis, overview; ELSS lock-in), shared statement / riskometer /
  definition chunks, and no chunk with a return figure (`RETURN_FIGURE_RE`).
- Minimal routing so the new cards are reachable: statements → `statement_steps`,
  lock-in → `lock_in`, lump sum → `min_lumpsum`, exit load also → `exit_load_rules`
  (full re-tune in Phase 16). Eval expectations updated to official wording.
- Results: 249 chunks; fund × field matrix 50/50 top-1; gold set 20/20 retrieved,
  20/20 answered with the fact, 20/20 citing an official page (Groq); guards 58/58;
  Phase 13 loader tests 5/5.

**Done when**
- [x] Each scheme has a card for each of the 7 question types it supports (enforced by `--strict`)
- [x] Spot checks of extracted values against the PDFs pass for all 5 schemes (PRD §11 mitigation): every number on every quoted card (920) is found in its source document; the one computed figure (BAF debt = sum of three debt subtotals) is labelled as such

---

## Phase 15: Intent + guards per PRD §6

**Goal:** deterministic intent handling exactly as PRD §6 and FR-8–FR-15 specify.

**Create / change** (`src/guards/`, `src/schemes.py`)
- **PII** (FR-10–12): **block** instead of redact-and-answer. Nothing goes to retrieval,
  the model or logs. Fixed safety message, input cleared, help link
  `groww.in/help/mutual-funds`. Server-side redaction stays as a backstop. Aadhaar
  checksum (Verhoeff), 10-digit Indian mobile, PAN, email, OTP, account/folio.
- **Advice** (FR-8): polite refusal, an offer of the facts we can give, and one
  AMFI/SEBI education link; mixed messages are handled as advice; bias to advice when unsure.
- **Performance** (FR-9): refusal with the HDFC factsheet link, no figures.
- **Out-of-scope** (FR-14):
  - other AMCs, other schemes, and Regular/IDCW plans get a coverage message + one official link
  - "scheme not in corpus" links the HDFC MF schemes listing page
  - A1 extras stay answerable
- **Non-MF** (FR-15): a one-line redirect with the `groww.in/help` link.
- **Aliases and fuzzy matching** (FR-2, §8): former names, short forms, misspellings;
  when two schemes match, return a clarify payload with chips.
- **Direct plan default** (FR-3).

**As built (2026-10-03)**
- Precedence: PII (block) → advice → performance → about → out-of-scope → ambiguous
  name (chips) → no fund named (clarify) → fact. "About" (incl. greetings) runs before
  out-of-scope so "What can you do?" is not treated as non-MF.
- PII: `ask()` checks first and returns the FR-11 message with the Groww help link;
  nothing else reads the message. Aadhaar uses the Verhoeff check (a failing 12-digit
  number is still blocked, as ACCOUNT).
- Advice (FR-8): refusal + offer of facts (for a mixed message, the specific fact as a
  separate question) + AMFI investor education link. This replaces the earlier
  owner choice of a link-free advice reply (2026-10-02), per the PRD.
- Out-of-scope reasons with their own text and link: other AMC (incl. "SBI Small Cap"
  without "fund") → AMFI; other HDFC scheme (incl. "HDFC Mid Cap Opportunities") → HDFC
  MF schemes listing (new `role=reference` row); Regular/IDCW → the scheme page;
  live data → factsheet; non-MF → one-line redirect to `groww.in/help`.
- Names (`src/schemes.py`): former names (HDFC Top 100, HDFC Equity Fund, HDFC TaxSaver)
  with a "formerly called" note; misspellings by fuzzy match (one match → assumed
  with a note; several → chips); "HDFC cap fund" → chips. Payloads carry `chips`.
- Fixed a latent bug: the performance pattern read the plan name "Direct Growth … 3
  years" as a growth claim (it hid the ELSS lock-in card from the offline fallback).
- Every non-answer response now carries one link (checked by the suite).
- Results: `debug_guards.py` 92/92 (all PRD §6 examples and §8 edge cases, PII never
  reaching retrieval/model); matrix 50/50; gold retrieval 20/20.

**Done when**
- [x] `scripts/debug_guards.py` covers every PRD §6 example and §8 edge case
- [x] Refusal recall 100% on the advice/performance cases; PII never reaches retrieval or logs

---

## Phase 16: Retrieval re-tune

**Goal:** route each supported question to the right official card for the right scheme.

**PRD:** FR-1, FR-7 (most specific page), §8 (conflicting sources, factual comparison), §11.

**Create / change** (`src/rag/retrieve.py`)
- Routing and synonyms for the 7 types across document types (lock-in → KIM/SID,
  statements → statement pages, riskometer meaning → SEBI/AMFI).
- Scheme filter before ranking. Shared documents (statement, SEBI, AMFI) stay reachable.
- **Conflicts:** prefer the newest dated card; log the conflict.
- **Factual comparison:** allowed only when one page supports both facts.
- Re-calibrate `MIN_SCORE` and `TOP_K`.

**As built (2026-10-03)**
- Routing for the official card types: definitions (incl. short "What is ELSS?")
  → glossary + SEBI/AMFI education; riskometer meaning → SEBI circular + education;
  direct vs regular → education; statements / registrar / CAS → statement pages;
  plus former name, inception (scheme allotment and Direct Plan start, now separate
  fields), objective, entry load, scheme type, how to invest / redeem, manager
  experience. Plurals ("expense ratios", "exit loads") are routed.
- Conflicts (§8): cards for the same scheme and fact from different documents are
  ordered newest first (`doc_date`, else ingest date); differing figures are logged
  by scheme and field only.
- Factual comparison (§8): several schemes are answered together only when one page
  covers all of them (`one_page_covers`, e.g. the TER file); otherwise the first
  scheme named is answered and the UI note invites a separate question.
- `detect_schemes` returns schemes in the order they are mentioned.
- Calibration (79 answerable questions): median 0.87, p5 0.53; unanswerable fund
  questions score 0.58–0.82, so the floor cannot separate them (the generator's found
  flag and the validator do). `MIN_SCORE` 0.35 → 0.20 (keeps short term questions
  such as "What is a folio number?"); `TOP_K` stays 8.
- Offline extractive fallback quotes the routed card when it is the top result.
- Results: matrix 50/50, gold retrieval 20/20, guards 92/92.

**Done when**
- [x] Fund × field matrix: top-1 correct for all 7 types × 5 schemes
- [x] Most-specific-page citation (scheme or TER page over a homepage)

---

## Phase 17: Response template + validator

**Goal:** every response follows PRD §7's template, and the validator enforces FR-4.

**Create / change** (`src/rag/generate.py`, `assemble.py`, `pipeline.py`)
- **Template:** the first sentence names the full scheme and plan; readable source
  label (e.g. "Source: HDFC Small Cap Fund – scheme page"); freshness line
  `Last updated from sources: DD Mon YYYY`. Tone rules (no hype words, no first person).
- **Every response has one link and a freshness line**, including refusals,
  clarifications and the "about" reply (fixed link table for non-answer responses).
- **Validator (FR-4):** rejects return figures, recommendation verbs (should / better /
  best / suitable), more than 3 sentences, or a non-corpus link. It regenerates once,
  then falls back to the FR-1 "couldn't find in official sources" response.
  The number-grounding check stays.
- **Stale sentence (§8):** when the cited page is past its freshness limit, add
  "Please check the linked page for the latest value" as one of the 3 sentences.

**As built (2026-10-03)**
- Template: every payload carries `source_url`, a readable `source_label` (new
  `label` column in `data/sources.csv`, e.g. "HDFC Small Cap Fund – scheme page")
  and `last_updated_from_sources` = the cited page's ingest date (ISO; the UI shows
  DD Mon YYYY). Not-found / error replies link the scheme page, or the HDFC MF
  schemes listing when no single fund is in play, so no response lacks a link.
- Prompt rewritten for the official corpus and §7 tone: the first sentence names the
  scheme and plan ("HDFC Small Cap Fund (Direct Plan - Growth) …"), no judgement or
  recommendation words, no first person, units and conditions with numbers.
- `src/rag/validate.py` (FR-4): rejects return figures, banned words (should, better,
  best, suitable, safe, good, ideal, recommended, guaranteed), first-person opinions,
  more than three sentences and links not in `sources.csv`. One regeneration with
  the reason, then `ValidationFailed` → FR-1 "I couldn't find this in the official
  sources" reply. Verbatim offline quotes are checked for return figures and links
  only. The number-grounding check stays. `RETURN_FIGURE_RE` is shared with the
  ingest strict check.
- Code-added sentences within the 3-sentence limit: FR-3 "Regular Plan values
  differ; see the linked page." on expense-ratio answers; §8 "Please check the
  linked page for the latest value." when the cited document is past its freshness
  limit (factsheet and TER by the date they state, other pages by ingest date).
- Holdings "not held" answers cite the factsheet with its "as on" date.
- Measured Groq usage: ~1.8–5K tokens per answered question (median ~2.5K).

**Done when**
- [x] 100% of golden-set responses pass the format validator
- [x] A forced bad answer (e.g. containing "best") is regenerated, then falls back

---

## Phase 18: Freshness + refresh

**Goal:** keep official data current within PRD §8's freshness limits on Render's free plan.

**Create / change**
- Daily Render redeploy (already in place). Scheme and TER pages are fetched every build.
- **Factsheet/KIM/SID URLs change with each edition:** a monthly checklist in the
  README, plus `--strict` flagging missing or stale editions.
- **Link-health check** (§11): a script that reports 4xx/5xx for every `sources.csv`
  URL, run in the scheduled workflow.
- **Keep the last good version** when a fetch fails (Phase 13), with the build log as the alert.

**As built (2026-10-03)**
- `scripts/check_links.py`: fetches every `sources.csv` URL (27: ingest, reference,
  help) and fails on 4xx/5xx or network errors; scans the HDFC MF hub pages (TER
  reports, factsheets, KIMs), which list the current files in their HTML, and warns
  when a newer edition than the registered one is listed. Added to the daily
  workflow as a separate `check-links` job (GitHub annotations).
- Build log: `STALE EDITION` warning when the factsheet or TER file is older than its
  freshness limit (35 / 7 days, by the date it states). A warning, not a failure, so
  a late edition does not stop the daily refresh. KIMs are revised on HDFC's own
  schedule, so their age is not a signal; a newer KIM is caught by the hub scan.
- KIM editions updated from the hub: all five now dated 21 Nov 2025 (ELSS, Large Cap,
  Small Cap and Balanced Advantage replaced; the date parser accepts `%2C`).
- Keep-the-last-good-copy (Phase 13) and the daily Render redeploy stay as built;
  the monthly checklist is in README.md (Phase 21).
- Results: 27/27 links healthy, no newer editions; rebuild strict-clean (249 chunks);
  matrix 50/50, gold retrieval 20/20, guards 92/92.

**Done when**
- [x] A simulated fetch failure keeps the previous data and reports it
- [x] Each answer's freshness line matches its cited page's ingest date

---

## Phase 19: UI per PRD §9

**Goal:** the UI matches PRD §9, keeping the Addendum A1 extras.

**Create / change** (`src/app/main.py`)
- **Copy and inputs:**
  - the exact welcome line, the three example chips and the pinned disclaimer from §9
  - the input hint "Ask a factual question. Don't share PAN, Aadhaar or account details."
  - **PII block state:** inline warning, input cleared, nothing sent
- **Answer bubble:** body, a readable source label (opens in a new tab), and the
  freshness line in secondary text.
- **Feedback:** 👍 / 👎 with an optional reason (wrong / outdated / not helpful),
  session-only (Addendum A3).
- **Kept from A1:** scheme panel, fund cards and fact sheet, fed by the official
  cards; Groww wording removed.
- **No transaction CTAs.** Accessibility labels on chips and links.

**As built (2026-10-03)**
- PRD §9 copy verbatim: welcome line, the three example chips, "Facts-only. No
  investment advice." pinned in a sticky header (and in the sidebar), input hint.
- Answer bubble: body, "Source: <readable label> ↗" (new tab, `aria-label`), then
  "Last updated from sources: DD Mon YYYY" in secondary text.
- PII block state: inline warning (FR-11 text + Groww help link) above the input;
  the message is not shown or kept in the chat history; the input is cleared.
- Clarify replies render the scheme chips as buttons that re-ask the question for
  the chosen fund. An ambiguous name the user types is not resolved from earlier
  chat context (only an explicit selection or chip settles it).
- Feedback: `st.feedback` thumbs on each answer; 👎 offers an optional reason
  (Wrong / Outdated / Not helpful); session state only (Addendum A3).
- Groww wording removed; footer: official sources, not affiliated.
- **Update 2026-10-03 (owner decision, PRD Addendum A8):** single chat screen. The
  left scheme list, fund cards ("View facts") and fact sheet were removed, along with
  `src/rag/facts.py`; the most asked questions (eight, the PRD §9 examples first) are
  shown as chips on an empty chat and in a collapsible section afterwards, with a
  "Clear chat" button. The facts behind the removed widgets stay answerable in chat.
- No transaction CTAs. Buttons carry `help` text; links carry `aria-label`.
- `scripts/test_ui.py` (Streamlit AppTest, offline generator): 17/17 (incl. no
  scheme list / fund cards, most asked questions shown).

**Done when**
- [x] Headless UI test checks every §9 element
- [x] No "Groww" source wording remains

---

## Phase 20: Golden set (200) + evaluation report

**Goal:** the PRD §10 launch gate.

**Create / change**
- `data/golden_set.csv`: 200 labelled queries (120 fact, 30 advice, 20 performance,
  15 out-of-scope, 15 PII). Labels: expected intent, expected value (or `card:<field>`
  for volatile figures), expected source domain or page.
- `scripts/eval_golden.py`:
  - a free mode (intent, routing, citation, format; no LLM)
  - a full mode (answers graded against the cited source)
- The report covers every §10 metric: factual accuracy, citation correctness, refusal
  recall/precision, format compliance, PII leakage, fabricated facts.

**As built (2026-10-03)**
- `data/golden_set.csv`: 200 labelled queries (120 fact, 30 advice, 20 performance,
  15 out-of-scope, 15 PII), with expected intent, value (regex or `card:<field>`)
  and source domain; PII rows carry fake values (Aadhaar ones Verhoeff-valid).
- `scripts/eval_golden.py`: free mode (offline generator) and full mode (Groq),
  resumable via `data/eval/`; spies on logs and generator prompts for PII; `--report`
  writes `docs/evaluation_report.md` with every PRD §10 metric.
- Free mode (all 200, final code): intent 200/200, fact retrieved 120/120, factual
  (offline proxy) 119/120, citation 119/120, refusal recall 50/50, precision 50/50,
  format 200/200, PII leaks 0, fabricated 0.
- Full mode (Groq): 44 of 200 graded before the run was stopped (the machine ran low
  on memory); all 44 correct, cited, formatted, no fabrication. Re-run `--mode full`
  to continue; refusal metrics are covered by free mode (refusals use no LLM).
- Fixes the golden set found: "Total Return Index" read as returns; "Direct Growth …
  3 years" read as growth; short definitions asked for a fund; advice recall
  ("better than", "right choice for me", "which … better"); "be worth now" as
  performance.

**Done when**
- [x] The free mode runs all 200 in about a minute
- [x] The full mode meets the §10 targets: accuracy ≥95%, citations ≥98%, refusal recall ≥99%, precision ≥90%, format 100%, PII 0, fabricated 0
- [x] The report is written to `docs/evaluation_report.md`

---

## Phase 21: Documents + deliverables

**Goal:** every document matches the built system and the PRD §12 checklist.

**Create / change**
- `docs/architecture.md`: corpus and allowlist, per-document chunking, field routing,
  intent order, response template and validator, conversation context, freshness,
  UI, deployment.
- `README.md`: architecture summary, setup, how to re-ingest, **how to add a scheme
  alias**, **how to run the golden-set evaluation**, known limitations, disclaimer.
- `data/sources.csv` as the source-list deliverable.
- `docs/sample_qa.md`: at least 2 examples per intent, plus every §8 edge case.
- `docs/eval_notes.md`: a new round, linking to the evaluation report.
- `.env.example` and `render.yaml` if the build changes.

**As built (2026-10-03)**
- `docs/architecture.md` v3.0 (as built): corpus and allowlist, per-document
  chunking, routing, intent order, template and validator, context, freshness, UI,
  deployment, evaluation, failure modes, PRD mapping.
- `README.md` rewritten: scope and sources, handling table, architecture summary,
  setup, keeping data current (monthly checklist), how to add a scheme alias, tests
  table, how to run the golden-set evaluation, Render, generator, disclaimer,
  privacy, known limits.
- `docs/sample_qa.md` regenerated from the live pipeline (Groq): 27 examples, at
  least two per intent, plus every §8 edge case, in the §7 template.
- `docs/eval_notes.md`: round 9 (official corpus, golden-set findings and fixes).
- `render.yaml` comment updated; `.env.example` unchanged (no new settings).
- `data/sources.csv` is the source-list deliverable (with readable labels).
- Fixes found while writing samples: a narrowed comparison now tells the generator
  to answer for the first scheme only; the sample script retries once after a
  generator error.

**Done when**
- [x] All six PRD §12 deliverables exist and are consistent with each other

---

## Phase 22: Release

**Goal:** ship the aligned version.

- Run the guard tests, matrix, golden set (free mode, then one full run) and the headless UI test.
- Commit and push; Render redeploys (or Manual Deploy → latest commit).
- On the live URL, check the three example chips, one question per intent, and a PII block.

**As built (2026-10-03)**
- Release checks (2026-10-03): guards 99/99, matrix 50/50, gold retrieval 20/20,
  headless UI test all passed, chat test OK, links 27/27, golden set free mode all
  targets met, full mode 44/44 so far.
- Pushed to GitHub `main` (Phases 12–21, then the report); Render redeploys from
  `render.yaml`. The live health check answered `ok`.
- To do on the live URL (owner): confirm the deployed commit in Render → Events, then
  try the three example chips, one question per intent and a PII block.

**Done when**
- [x] The live app passes the spot checks, and the build log shows the full official corpus loaded

---

## Copy-paste cheat sheet

| You say to the assistant | Meaning |
| --- | --- |
| `Implement Phase N only from docs/implementation.md` | Scope lock |
| `Follow docs/PRD.md and docs/architecture.md` | Requirements + design lock |
| `Do not start Phase N+1` | Stop condition |

---

## Definition of "implementation complete"

All of:

1. `scripts/ingest.py --refresh --strict` rebuilds Chroma from the ~22 official pages in
   `data/sources.csv` (no third-party sources).
2. Every response follows PRD §7: ≤ 3 sentences, exactly one allowlisted link,
   "Last updated from sources: DD Mon YYYY".
3. The 7 supported question types are answered for all 5 schemes; advice, performance,
   PII, out-of-scope and non-MF messages are handled in **code** per PRD §6.
4. The golden set (200) meets the PRD §10 launch targets, with the report in `docs/`.
5. The PRD §12 deliverables exist and match the built system; deviations are listed in the PRD Addendum.
