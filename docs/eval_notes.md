# Evaluation notes

Gold-set evaluation of retrieval and answers, per architecture §5 ("tune after
first retrieval eval") and §12. Reproduce with:

```
python scripts/eval_gold.py
```

Each gold question has an expected fact read off the official pages in the index.
The script checks three things:

- **Fact in top-k:** does any retrieved chunk contain the fact, and at what rank?
- **Answer has fact:** does the final answer text contain it?
- **Official citation:** is the answer's single link on hdfcfund.com / amfiindia.com / sebi.gov.in?
  Refusals and "not in this prototype" replies count as ❌ here.

## Round 9: official corpus and the PRD (Phases 12–20), 2026-10-03

The corpus moved from the five Groww pages to 24 official pages (HDFC MF, SEBI,
AMFI / Mutual Funds Sahi Hai; `data/sources.csv`), with fact cards per document
type, the PRD §6 guards, the §7 template and FR-4 validator, and the §9 UI. The
launch gate is now the 200-query golden set: see
[evaluation_report.md](evaluation_report.md) (`scripts/eval_golden.py`).

| Check | Before (Groww, round 8) | Now (official) |
|---|---|---|
| Fund × field matrix (top-1 right card) | 50/50 | 50/50 |
| Gold set (20): fact retrieved / answered / cited (Groq) | 17/18 retrieved; ELSS lock-in and statement steps missing | 20/20 · 20/20 · 20/20 |
| Guard suite | 58/58 | 99/99 (every §6 example and §8 edge case) |
| Golden set, free mode (200, no LLM) | — | intent 200/200; fact retrieved 120/120; refusal recall 50/50; precision 100%; format 200/200; PII leaks 0; fabricated 0 |
| Headless UI test | — | 15/15 |

What the golden set found and what was fixed:
- "Total Return Index" in benchmark names was read as a returns question (it hid
  benchmark answers offline and could have refused a benchmark question).
- "Direct Growth … 3 years" was read as a growth claim (hid the ELSS lock-in card).
- Short definitions ("What is NAV?") asked which fund; now answered.
- Advice recall: "better than", "the right choice for me", "which … better" added;
  returns comparisons still go to the performance refusal.
- "How much would 10000 invested … be worth now?" added to performance.
- Calibration: unanswerable fund questions score 0.58–0.82, so no score floor can
  separate them; the generator's found flag and the validator decide. `MIN_SCORE`
  0.35 → 0.20 keeps short term questions.
- Measured Groq usage ≈ 1.8–5K tokens per answered question, so a full golden-set run
  (120 fact answers) spans two days of the free quota; the runner is resumable.

## Round 8: holdings analysis and honest error replies, 2026-10-01

- **Trigger:** "can you give me the holdings analysis" (a follow-up) returned
  "Sorry, I couldn't generate an answer right now" with an AMFI link.
- **Cause 1, no totals in the sources:** Groww's page states each holding's
  weight but no allocation totals. Its "Holding Analysis" chart is drawn in the
  browser from separate data. The model added up weights itself, and the number
  check rightly rejected the totals.
- **Cause 2, misleading message:** that rejection surfaced as the generic
  "try again" error. A retry could never help.
- **Cause 3, irrelevant link:** miss and error replies picked their link from the
  question text only. With no fund named, they fell back to the AMFI page, even
  though the fund was known from the chat.
- **Fixes:**
  - **Analysis cards:** three `holdings_breakdown` cards per fund, computed
    exactly at ingest from the listed weights and labelled as calculated.
    - Asset class, with equity / debt / cash always shown, even at 0.00%.
    - Instrument type.
    - Sector.
  - **Routing:** analysis, allocation, ratio, mix and sector questions go to
    these cards.
  - **Prompt:** quote these totals, lead with the asset mix, and never sum
    percentages yourself.
  - **Honest message:** a figure not in the sources now gives "I can only give
    figures that are stated in the sources…" (`UngroundedNumberError`). The
    generic error is reserved for outages.
  - **Links:** miss and error replies link the fund in context (named or carried
    over), or nothing.
- **Results:**

  | Question | Answer |
  |---|---|
  | BAF holdings analysis (follow-up) | "equity 73.26%, debt 23.76%, other 1.60% and cash 1.28%, calculated from the 326 holdings listed on Groww" |
  | Small Cap equity vs debt | "equity 89.64% and debt 0.00%" |

  Gold set: 19/20 retrieved, plus 2 new analysis rows. Matrix 50/50. Guards 58/58.

## Round 7: conversation context + definite "not held" answers, 2026-09-30

- **Context window of the last 25 exchanges (`src/rag/context.py`).**
  - **Fund carry-over:** a question naming no fund inherits the most recent
    single fund from the chat. The which-fund prompt and the "Tata = other AMC"
    scope rule are skipped in that case.
  - **Topic carry-over:** a short follow-up ("What about Large Cap?") is searched
    together with the previous question and passed to the generator with it.
  - **What the generator sees:** a compact transcript, labelled "only to
    understand what the question refers to; take every fact from the excerpts".
    The number check still runs against the current excerpts only.
- **Definite absence (`src/rag/holdings.py`).** "Does <fund> hold <company>?"
  checks the company name exactly against all the fund's holdings cards. If
  it's not found, the bot answers "<company> is not among the N holdings listed
  for <fund> on its Groww page" without calling the LLM.
- **Scripted conversation (`scripts/debug_chat.py`, Groq):** 8/8 turns correct.
  - Exit load → "And its expense ratio?" → "Who manages it?" → "Does it hold
    Tata Steel?" (yes, 0.68%) → "Does it hold Infosys?" (not among the 87) →
    "What about Large Cap?" (holds Infosys Ltd, 2.76%) → "What is the minimum
    SIP?" (Large Cap, ₹100) → "Should I buy it?" (advice refusal).
  - The first run missed "What about Large Cap?": retrieval had the right card,
    but the model saw only the bare follow-up. Passing the previous question
    alongside it fixed this.
- **Regression:** matrix 50/50, gold 17/18, guards 58/58.

## Round 6: answer anything on the page (holdings etc.), 2026-09-30

- **Trigger:** "what are the holdings in HDFC Balanced Advantage Fund" got "not in
  sources". Holdings had been dropped under architecture §8 ("live holdings").
  The owner decided the bot should answer anything the page states, so only
  the content the brief rules out stays dropped: returns, rankings, star rating
  and "compare similar funds".
- **New cards (158 total):**
  - A holdings headline (count + top 10) and the rest of the list in groups of 25.
  - Glossary definitions.
  - Full fund-house details (custodian, address, incorporation, the AMC's total
    AUM labelled "not this fund's size").
  - The other schemes each manager runs, and the registrar address.
- **Retrieval, field routing:**
  - The query-synonym table now also names the card fields that answer each
    kind of question. A filtered search on those fields is placed first.
  - Definition questions route to the glossary.
  - Holdings questions also get an exact, case-insensitive match of the
    question's words against all the fund's holdings cards. Company names are a
    weak signal for dense search.
- **MIN_SCORE 0.45 → 0.35:** "Which other schemes does Chirag Setalvad manage?"
  scored 0.42 with the right card at #1. Off-topic questions still max out at 0.24.
- **Guards:**
  - Holdings removed from the live-data rule. Only today / live / right-now
    NAV, price and AUM are refused.
  - Company names (Tata, ICICI, SBI, HDFC Bank…) no longer trigger other-AMC /
    non-MF refusals when one of the five schemes is named.
  - "Tata Small Cap Fund" (a fund-house name followed by a fund name) is still
    refused.
  - Definition questions skip the which-fund prompt.
- **Prompt:** never say an item is absent from a partial list.
- **Bugs found while testing:**
  - "Does HDFC Small Cap Fund hold Tata Steel?" was first refused as other-AMC
    (Tata). After that fix, it was answered "not listed", because only the top
    10 was in context. It is actually holding #51 at 0.68%. Both are fixed; the
    answer is now "Yes … Tata Steel Ltd with a weight of 0.68%".
  - The custodian answer "HDFC Bank" for Large Cap was checked and is correct.
    Groww lists different custodians per scheme (Citibank NA for Small Cap).

| Check | Round 5 | Round 6 |
|---|---|---|
| Matrix (now incl. holdings + holdings count), top-1 | 40/40 | **50/50** |
| Gold (now 18 incl. BAF holdings + a definition), retrieved | 15/16 | **17/18**, all #1 |
| Guard tests | 49 | **58/58** |

## Round 5: chunking and retrieval rebuilt for the Groww data, 2026-09-28

**Why.** After the switch to Groww, the chunker and retriever were still the ones
built for the official-document corpus (factsheet/KIM heading logic, patched for
Groww). An audit found these problems:
- Chunks were terse fragments, and some had no fund name ("About").
- The riskometer existed only inside prose.
- The current exit load sat beside an undated history of old 2% rules.
- HDFC's total AUM sat next to AUM questions.
- There were duplicate chunks.
- A fact question naming no fund was answered about whichever fund ranked first.
  Architecture §12 says to ask which fund; this had never been built.

**Changes.**
1. **Fact-card chunking (`src/ingest/groww.py`).** The problem statement asks for a
   chunking strategy chosen from the data. Groww pages are structured
   label/value pages, so each page is parsed into fields, and each field is one
   self-contained card that names the fund:
   - NAV with date, TER, AUM, min SIP and lump sum
   - the current exit load, plus exit-load history labelled "earlier rules, not
     current"
   - stamp duty, tax, riskometer, benchmark, objective
   - the fund-managers list and each manager's profile
   - fund house and registrar
   - one overview card per fund

   That makes 93 cards. Each carries a `field` in its metadata. The generic
   chunker remains for non-Groww documents.
2. **Which-fund guard (`src/guards/clarify.py`).** A per-fund fact question with no
   fund named gets "Which fund do you mean?" and the list of five funds.
3. **Retrieval.**
   - Query synonyms were added for benchmark and statements.
   - The card labels carry everyday synonyms, e.g. "Fund size (AUM, assets under
     management)".
   - MIN_SCORE was re-calibrated: in-scope questions score 0.64–0.92, off-topic
     ones 0.00–0.24, so 0.45 stays.
   - TOP_K stays at 8. Eight short cards are about 500 tokens.
4. **Generation.** Answers are complete sentences that name the fund.

**Results.**

| Check | Before (Round 4) | After |
|---|---|---|
| Fund × field matrix: top-1 is the right card (`--matrix`, 40 questions) | not measured | **40/40** |
| Gold set: fact retrieved | 14/16 (ranks 1–3) | **15/16**, all at rank 1 |
| Gold set: answer has fact (Groq) | not measured | **15/16** |
| Guard tests | 43 | **49/49** |
| Full LLM eval runtime | ~12 min (rate-limited) | **~90 s** |

The one remaining miss is the ELSS lock-in, which is not on Groww's page. The
statement question now finds the registrar card (CAMS, camsonline.com) at #1.

## Round 4: Groww-only corpus, 2026-09-27

- **Change:** the corpus is now the five Groww scheme pages named in
  `docs/problemstatement.txt`. The official HDFC documents are no longer ingested.
  AMFI and the HDFC factsheet remain only as refusal links (`role=reference`).
- **Gold set:** the expected facts were re-read from the Groww pages. They differ
  from HDFC's documents, e.g. Large Cap TER is 1.03% (Groww) vs 0.98% (factsheet),
  and NAV is dated 25 Sep '26.
- **Index:** 5 pages → 70 chunks. Ingest takes about 10 seconds.

| Gold (retrieval rank) | Groww-only |
|---|---|
| 1–2 TER (Large / Small Cap) | 1, 1 |
| 3 ELSS lock-in | ❌ not on Groww's page |
| 4–5 Min SIP | 1, 1 |
| 6–7 Exit load | 1, 2 |
| 8 Riskometer | 1 |
| 9–10 Benchmark | 1, 1 |
| 11 Statement download | ❌ Groww only names the registrar (CAMS) |
| 12–13 AUM | 1, 1 |
| 14–15 NAV | 1, 2 |
| 16 Fund managers | 3 |
| **Retrieved** | **14/16** |

**LLM spot checks (Groq):**

| Question | Answer |
|---|---|
| Fund size, Small Cap | "₹41,890.86 Cr" |
| Fund managers, Small Cap | "Dhruv Muchhal and Chirag Setalvad" |
| ELSS lock-in | "doesn't have that information", linking Groww's ELSS page |

All three cite Groww. A full 16-question LLM run is pending the Groq daily quota.

**Groww-specific cleanup (`src/ingest/load.py`, `_clean_groww`).**
- **Dropped:** menus, footer, returns, rankings, star rating, holdings and
  "compare similar funds".
- **Wrong template sentence:** also dropped is the auto-generated "About"
  sentence that states the AMC's total AUM (₹9,86,237 Cr) as the fund's AUM.
- **Initials:** manager avatar initials ("DM", "CS") are removed. The model had
  reported them as the managers' roles.

The rounds below describe the earlier official-document corpus. Their tuning
(query synonyms, field-level chunks, completeness rule) still applies.

## Round 3: single-field facts (AUM, NAV, fund manager), 2026-09-27 (official-document corpus)

- **Trigger:** a user asked "What is the fund size of HDFC Small Cap Fund?". The
  bot replied "not in this prototype", yet the figure (₹41,890.86 Cr as on 31 Aug
  2026) is in both the factsheet and the scheme page.
- **Diagnosis:** two causes.
  - "Fund size" is not the documents' wording; they say "Assets Under Management".
  - The figure was one number inside a chunk full of other fields, titled
    "Riskometer" or "DATE OF ALLOTMENT". Neither chunk made the top 8.
- **Gold set extended to 16:** added AUM ×2, Direct Growth NAV ×2 and fund manager.
  These were measured with `--retrieval-only` (no API calls) while tuning.

| Gold (retrieval rank) | Baseline | + query synonyms | + field chunks |
|---|---|---|---|
| 1 Large Cap TER | 2 | 1 | 1 |
| 2 Small Cap TER | 8 | 3 | 1 |
| 7 ELSS exit load | 4 | 4 | 1 |
| 8 Large Cap riskometer | 8 | 8 | 1 |
| 12 Small Cap AUM ("fund size") | – | – | 1 |
| 13 Large Cap AUM | – | 4 | 1 |
| 14 Flexi Cap NAV | 3 | 3 | 2 |
| 15 Small Cap NAV | – | – | 2 |
| 16 Small Cap fund manager | – | – | 1 |
| **Retrieved** | **12/16** | **13/16** | **16/16** |

The other rows were already rank 1–2 and are unchanged.

**Changes:**
1. **Query synonyms (`src/rag/retrieve.py`, `expand_query`).** Everyday terms are
   expanded before embedding: fund size / corpus / AUM → "assets under
   management", NAV, fees → "total expense ratio", risk level → riskometer, and
   who manages → fund manager. Guards and scheme detection still see the
   original question.
2. **Field-level chunks (`src/ingest/chunk.py`).** On factsheet and scheme pages
   (`doc_type` factsheet / faq), each single-fact field gets its own chunk:
   AUM, NAV, TER / expense ratio, exit/entry load, benchmark, riskometer, min
   SIP, lock-in, fund manager, allotment/inception date. Each chunk is titled
   with its fund, e.g. `[HDFC Small Cap Fund > AUM]`.
   - Scheme-page labels (`AUM`, `NAV`, `TER`, `Min SIP`, `Lock in`) are now
     recognised as headings.
   - A near-empty field section joins the next section when both name the same
     field. This keeps "NAV (As On AUGUST 31, 2026)" together with its values.
   - A bug was found and fixed during this round. The holdings tables' `% to` /
     `NAV` column header was being treated as the NAV field, which produced
     chunks like "NAV Lumax Industries 0.90" that a model could misread as the
     fund's NAV. After the fix, all 59 NAV-titled chunks are genuine.
   - KIM chunking is unchanged.
3. **Prompt (`src/rag/generate.py`).** Answers state the "as on" date for NAV,
   AUM and expense ratio. If one excerpt says "NA" and another has the value,
   the value is used.

**Cost:** the index grew from 576 to 1,673 chunks, mostly small factsheet field
chunks (median ~270 chars). Ingest takes about 3 minutes.

**LLM check on the 5 new questions (Groq):** all correct, each with a date and an
official source. For example, "The fund's assets under management are
₹41,890.86 Cr as of 31/08/2026." and "The Direct Plan – Growth Option NAV is
160.949 as on August 31, 2026." A full 16-question LLM re-run is pending,
because the free tier's daily token budget was spent on today's runs:
`python scripts/eval_gold.py`.

**Follow-up: incomplete fund-manager answers.** A user reported that the bot
named one Small Cap manager while the website shows two. Two causes:

1. **The model dropped names.** Retrieval returned the full list, but the model
   named only the first manager for a singular question. Fixes:
   - The gold check now requires both names.
   - The prompt says to list every value.
   - The rule is also repeated next to the question (`COMPLETENESS_REMINDER`).
     The system-prompt rule alone was followed only about two times in three.
2. **The factsheet's overseas manager sits in a ¥ page footnote.** The chunker
   now attaches the ¥ footnote from the same fund page to the `FUND MANAGER ¥`
   chunk. It is scoped per page and checked for all five schemes. The €
   footnote is left out, because it is garbled and holds a second rupee figure
   near the AUM.

After both fixes, two runs listed all four names the August factsheet gives,
with roles and dates:
- Chirag Setalvad
- Bhagyesh Kagalkar (gold/silver, from 26 Aug 2026)
- Dhruv Muchhal (overseas, from 22 Jun 2023)
- Gopal Agrawal (from 1 Sep 2026)

The website currently shows only Setalvad and Muchhal. The factsheet is newer
on this point.

**Design choice to revisit:** "current AUM" / "NAV today" are refused as live
data. A plain "AUM" / "NAV" question is answered with the dated snapshot.

## Results with the LLM generator (2026-09-27, 11-question set, before round 3; k=8, Groq `openai/gpt-oss-120b`)

| # | Category | Question | Expected | Fact in top-k (rank) | Answer has fact | Official citation | Cited page |
|---|---|---|---|---|---|---|---|
| 1 | Expense ratio | What is the expense ratio of HDFC Large Cap Fund Direct Growth? | Direct TER 0.98% (Aug 2026 factsheet) | ✅ #2 | ✅ | ✅ | HDFC MF Factsheet - August 2026.pdf |
| 2 | Expense ratio | What is the expense ratio of HDFC Small Cap Fund Direct Growth? | Direct TER 0.72% (Aug 2026 factsheet) | ✅ #8 | ✅ | ✅ | KIM - HDFC Small Cap Fund dated November 21, 2024.pdf |
| 3 | Lock-in | What is the lock-in for HDFC ELSS Tax Saver? | 3 years | ✅ #1 | ✅ | ✅ | ELSS scheme page |
| 4 | Minimum SIP | What is the minimum SIP amount for HDFC ELSS Tax Saver? | ₹500 | ✅ #1 | ✅ | ✅ | ELSS scheme page |
| 5 | Minimum SIP | What is the minimum SIP amount for HDFC Balanced Advantage Fund? | ₹100 | ✅ #1 | ✅ | ✅ | BAF scheme page |
| 6 | Exit load | What is the exit load on HDFC Small Cap Fund Direct Growth? | 1% if redeemed within 1 year | ✅ #1 | ✅ | ✅ | KIM - HDFC Small Cap Fund dated November 21, 2024.pdf |
| 7 | Exit load | What is the exit load of HDFC ELSS Tax Saver? | Nil | ✅ #4 | ✅ | ✅ | HDFC MF Factsheet - August 2026.pdf |
| 8 | Riskometer | What is the riskometer level of HDFC Large Cap Fund? | Very High | ✅ #8 | ✅ | ✅ | Large Cap scheme page |
| 9 | Benchmark | What is the benchmark of HDFC Small Cap Fund? | BSE 250 SmallCap Index (TRI) | ✅ #1 | ✅ | ✅ | Small Cap scheme page |
| 10 | Benchmark | What is the benchmark of HDFC Flexi Cap Fund? | NIFTY 500 Index (TRI) | ✅ #1 | ✅ | ✅ | KIM - HDFC Flexi Cap Fund dated November 21, 2025.pdf |
| 11 | Statement | How do I download my capital gains statement? | via CAMS / KFintech / CAS | ✅ #1 | ✅ | ✅ | HDFC capital-gain statement guide |

**Totals:** fact retrieved **11/11** · answer contains fact **11/11** · official citation **11/11**.

The LLM reads all 8 excerpts, so it recovers the facts that the extractive
fallback missed:
- **#1:** it picked the fund's own TER from the factsheet over the KIM's
  regulatory maximum.
- **#2 and #8:** it used facts that ranked last, at #8.
- **#7:** it answered "Nil" where the fallback gave up.

The run hit Groq's free-tier per-minute token cap repeatedly. Automatic retries
absorbed it, at the cost of a slower run (about 12 minutes for 11 questions).

**Claude has not been evaluated** because no paid Anthropic key was available. It
uses the same prompt, schema and code checks.

## Extractive fallback results (2026-09-27, k=8, no LLM)

| # | Category | Question | Expected | Fact in top-k (rank) | Answer has fact | Official citation | Cited page |
|---|---|---|---|---|---|---|---|
| 1 | Expense ratio | What is the expense ratio of HDFC Large Cap Fund Direct Growth? | Direct TER 0.98% (Aug 2026 factsheet) | ✅ #2 | ❌ | ✅ | KIM - HDFC Large Cap Fund dated May 30, 2025.pdf |
| 2 | Expense ratio | What is the expense ratio of HDFC Small Cap Fund Direct Growth? | Direct TER 0.72% (Aug 2026 factsheet) | ✅ #8 | ❌ | ✅ | KIM - HDFC Small Cap Fund dated November 21, 2024.pdf |
| 3 | Lock-in | What is the lock-in for HDFC ELSS Tax Saver? | 3 years | ✅ #1 | ✅ | ✅ | ELSS scheme page |
| 4 | Minimum SIP | What is the minimum SIP amount for HDFC ELSS Tax Saver? | ₹500 | ✅ #1 | ✅ | ✅ | ELSS scheme page |
| 5 | Minimum SIP | What is the minimum SIP amount for HDFC Balanced Advantage Fund? | ₹100 | ✅ #1 | ✅ | ✅ | BAF scheme page |
| 6 | Exit load | What is the exit load on HDFC Small Cap Fund Direct Growth? | 1% if redeemed within 1 year | ✅ #1 | ✅ | ✅ | KIM - HDFC Small Cap Fund dated November 21, 2024.pdf |
| 7 | Exit load | What is the exit load of HDFC ELSS Tax Saver? | Nil | ✅ #4 | ❌ | ❌ (honest miss) | ELSS scheme page |
| 8 | Riskometer | What is the riskometer level of HDFC Large Cap Fund? | Very High | ✅ #8 | ❌ | ✅ | KIM - HDFC Large Cap Fund dated May 30, 2025.pdf |
| 9 | Benchmark | What is the benchmark of HDFC Small Cap Fund? | BSE 250 SmallCap Index (TRI) | ✅ #1 | ✅ | ✅ | KIM - HDFC Small Cap Fund dated November 21, 2024.pdf |
| 10 | Benchmark | What is the benchmark of HDFC Flexi Cap Fund? | NIFTY 500 Index (TRI) | ✅ #1 | ✅ | ✅ | KIM - HDFC Flexi Cap Fund dated November 21, 2025.pdf |
| 11 | Statement | How do I download my capital gains statement? | via CAMS / KFintech / CAS | ✅ #1 | ✅ | ✅ | HDFC capital-gain statement guide |

**Totals:** fact retrieved **11/11** · answer contains fact **7/11** · official citation **10/11**.

### How to read this

- **Retrieval (11/11) is what the RAG pipeline controls.** Every fact reaches the
  generator's context. Two (#2, #8) sit at rank 8, the last slot, so they are
  fragile.
- **This answer column measures the extractive fallback.** It quotes up to three
  sentences from the top three chunks by keyword overlap. That's why it misses
  facts that rank lower (#1, #2, #8) or sit in table-like text (#7). The LLM
  results above (11/11) show those facts were retrievable all along.
- **#7 is the correct failure mode.** The fallback found no sentence to quote, so
  it replied "not in this prototype" with the ELSS page link rather than guessing.
- **Expense-ratio caveat.** The top chunk for expense-ratio questions is the KIM's
  *regulatory maximum* TER (2.25% on the first ₹500 cr). The fallback quotes it
  (sample Q&A #6), labelled as a quote. The Claude prompt instructs it to call such
  a figure a regulatory limit, not the fund's TER. That is why the expense-ratio
  question was dropped from the UI examples.

## What changed, and the evidence for each change

The architecture says to change chunking and retrieval only with gold-set evidence.
Each change below is backed by a measurement.

### 1. Chunking: factsheet chunks know which fund they belong to

- **Evidence:** in Phase 6, the Large Cap expense-ratio question never retrieved the
  fund's own TER. The August 2026 factsheet repeats the same sub-headings
  (`FUND MANAGER`, `EXPENSE RATIO`, `EXIT LOAD`) for about 70 funds. Every
  factsheet chunk was tagged `scheme=ALL` and titled only by its sub-heading. The
  right chunk ranked **#16**.
- **Change (`src/ingest/chunk.py`):**
  - Section titles carry the last fund-name heading as a parent, e.g.
    `HDFC Large Cap Fund > NAV PER`.
  - Chunk text is prefixed with that title so the embedding sees the fund.
  - Factsheet chunks under one of the five schemes are tagged with that scheme.
  - The fund-name pattern was broadened (apostrophes, digits, ETF/FOF). A
    `CATEGORY OF SCHEME` heading with no fund name before it resets the parent.
    This keeps the next unknown fund from being attributed to the previous one.
    It was found when HDFC Children's Fund (0.98% Direct) was being tagged as ELSS.
- **Result:** each of the five schemes owns exactly one factsheet chunk with its
  own TER:

  | Scheme | Regular | Direct |
  |---|---|---|
  | Large Cap | 1.52% | 0.98% |
  | Small Cap | 1.51% | 0.72% |
  | Flexi Cap | 1.27% | 0.67% |
  | BAF | 1.28% | 0.75% |
  | ELSS | 1.68% | 1.12% |

  The Large Cap TER chunk moved from #16 to #3.

### 2. Retrieval: k 5 → 8, and other funds' factsheet chunks excluded

- **Evidence:** the first gold run (k=5) retrieved 9/11. Results for filter and k
  variants:

  | Gold # | k=5 | k=8 | k=5 + exclude | k=8 + exclude |
  |---|---|---|---|---|
  | 1 Large Cap TER | 3 | 3 | 2 | 2 |
  | 2 Small Cap TER | – | – | – | 8 |
  | 8 Large Cap riskometer | – | – | – | 8 |
  | all others | unchanged | unchanged | unchanged | unchanged |

- **Change (`src/rag/retrieve.py`):**
  - `TOP_K = 8`, the top of the 3–8 range the architecture allows.
  - When a query names a scheme, the filter keeps that scheme's chunks plus
    shared rows except factsheet chunks still tagged `ALL`. After change 1,
    those belong to other funds.
- **Result:** 11/11 retrieved. No other question's rank got worse.

### 3. Extractive fallback fixes (generator quality, not retrieval)

- It picks the best of the top 3 chunks instead of always quoting #1, and cites
  the chunk it quoted.
- Scheme-name words, the title prefix and FAQ *questions* no longer count
  toward the overlap score. Before, the new title prefix made every sentence
  match "ELSS Tax Saver", and it quoted FAQ questions.
- **It never quotes sentences the performance guard flags.** Sample Q&A exposed the
  fallback quoting a CAGR/returns table in answer to a benchmark question. That
  breaks the PRD's no-performance rule even though nothing was computed.

Answers with the fact went from 3/11 to 7/11.

## Not changed (and why)

- **Chunk size and overlap** (1,600–3,200 chars, about 12%): no gold failure
  pointed at size. Every failure was attribution or rank.
- **No reranker or hybrid search:** the architecture reserves these for a gold-set
  failure, and retrieval reached 11/11 without them.
- **k=8 is the ceiling.** If #2 or #8 drop out after a corpus refresh, the next
  lever is a per-scheme factsheet PDF ("Fund Facts") added to `sources.csv`.
  A reranker comes after that.
