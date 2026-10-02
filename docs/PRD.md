# Product Requirements Document  
**Product:** Mutual Fund FAQ RAG Chatbot  
**Version:** 1.0  
**Status:** Draft  
**Owner:** Product (Neha)  
**Last updated:** 2026-09-27  

---

## 1. Summary

Build a small, facts-only FAQ assistant that answers questions about a defined set of **HDFC Mutual Fund** schemes using Retrieval-Augmented Generation (RAG) over official public pages. Every answer must cite a source. The product must not give investment advice, store PII, or invent performance numbers.

This is a working prototype of a RAG chatbot, not a general-purpose investing advisor.

---

## 2. Problem

Retail users and support/content teams repeatedly ask the same factual questions about mutual fund schemes: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and how to download statements.

Today those answers live across factsheets, KIMs/SIDs, AMC FAQs, and regulator pages. People either:

- Get an opinionated or incomplete answer from blogs and chat UIs, or  
- Hunt through PDFs and product pages themselves.

We need a **scoped, citable, facts-only** assistant so answers are short, sourced, and clearly not advice.

---

## 3. Goals and non-goals

### 3.1 Goals

| ID | Goal |
| --- | --- |
| G1 | Answer factual scheme questions from a curated public corpus only. |
| G2 | Show **one clear citation URL** on every answer. |
| G3 | Refuse advice / portfolio / buy-sell questions politely and stay facts-only. |
| G4 | Implement a full RAG pipeline: load → chunk → embed → store → retrieve → generate. |
| G5 | Ship a tiny UI plus required milestone deliverables (README, source list, sample Q&A, disclaimer). |

### 3.2 Non-goals

- Personalized recommendations, asset allocation, or “should I buy/sell?”  
- Account login, KYC, transactions, or statement **generation** (only explain how to download from official channels)  
- Comparing returns, ranking funds, or computing performance  
- Multi-AMC coverage beyond the five HDFC schemes in v1  
- Using third-party blogs, app backends, or unofficial screenshots as sources  
- Collecting or storing PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers  

---

## 4. Users and use cases

### 4.1 Primary users

- **Retail users** comparing a small set of HDFC schemes and needing official facts.  
- **Support / content teams** answering repetitive MF FAQ traffic with a consistent, sourced reply.

### 4.2 Primary use cases

1. Look up expense ratio, exit load, or minimum SIP for a named scheme.  
2. Ask ELSS lock-in (and related tax-saver facts that appear on official pages).  
3. Ask riskometer and/or benchmark.  
4. Ask how to download statements / capital-gains documents (process from official guides only).  
5. Ask something opinionated → receive a refusal plus an educational official link.

---

## 5. Scope (v1)

### 5.1 AMC and schemes

**AMC:** HDFC Mutual Fund  

| Category | Scheme (as specified) | Seed URL |
| --- | --- | --- |
| Large cap | HDFC Large Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi cap | HDFC Equity Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver Fund – Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small cap | HDFC Small Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Hybrid | HDFC Balanced Advantage Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

### 5.2 Corpus rules

- **Public sources only:** AMC / SEBI / AMFI pages (factsheets, KIM/SID, scheme FAQs, fee/charges, riskometer/benchmark notes, statement/tax-doc guides).  
- Groww scheme URLs above are **entry points for scoping schemes**, not a substitute for official AMC/SEBI/AMFI documents as the citation source of record. Prefer citing official AMC/SEBI/AMFI URLs in answers.  
- No screenshots of app backends.  
- No third-party blogs as sources.  
- Maintain a **source list** (CSV or Markdown) of the URLs actually ingested (milestone requires documenting the five seed URLs; ingest additional official pages as needed and list them).

### 5.3 Question types in scope

Examples:

- Expense ratio of [scheme]?  
- ELSS lock-in?  
- Minimum SIP?  
- Exit load?  
- Riskometer / benchmark?  
- How to download capital-gains statement?

Out of scope for answers (refuse): buy/sell, “best fund,” predicted returns, portfolio construction.

---

## 6. Product experience

### 6.1 UI (tiny)

- Welcome line.  
- **Three example questions** (clickable or copy-ready).  
- Persistent note: **“Facts-only. No investment advice.”**  
- Chat input + answer area.  
- Each answer shows: short text (≤3 sentences), **one source link**, and **“Last updated from sources: &lt;date&gt;”**.

### 6.2 Answer behavior

| Situation | Behavior |
| --- | --- |
| Factual question in corpus | ≤3 sentences, one citation, last-updated line, no advice. |
| Factual question not in corpus | Say we don’t have it in this prototype; do not invent; optional link to official AMC/AMFI/SEBI hub. |
| Performance / returns compare | Do not compute or compare; link to official factsheet. |
| Advice / portfolio | Polite facts-only refusal + relevant educational official link. |
| PII in user message | Do not store; warn user not to share PII; continue without persisting identifiers. |

### 6.3 Disclaimer (UI snippet)

Must appear in the UI (and in README). Intent:

> Facts-only answers from public scheme documents. This is not investment advice. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.

Exact legal wording can be tightened at implementation; the product requirement is a visible facts-only / no-advice disclaimer.

---

## 7. RAG architecture (required)

The chatbot is a **RAG system**. Architecture and implementation must follow **all stages** of retrieval-augmented generation, covering **data ingestion** and **data retrieval**.

### 7.1 Ingestion pipeline

```
Loading → Chunking → Embedding → Store vector data
```

| Stage | Requirement |
| --- | --- |
| **Loading** | Fetch and parse the scoped public pages / PDFs into text. Track source URL and fetch date per document. |
| **Chunking** | Split documents so retrieval stays precise for FAQ-style fields (fees, lock-in, SIP, riskometer) without losing section context. **Strategy is to be chosen from the actual source formats** (HTML vs PDF, table-heavy factsheets vs narrative KIM). Default recommendation until data is inspected: heading-aware / recursive character split, ~400–800 tokens, ~10–15% overlap, preserve metadata (`url`, `scheme`, `doc_type`, `section_title`). Tune after first retrieval eval. |
| **Embedding** | `sentence-transformers/all-MiniLM-L6-v2` |
| **Vector store** | **ChromaDB** — persist embeddings + metadata for local prototype use. |

### 7.2 Retrieval and generation

```
User query → Embed query → Retrieve top-k chunks from ChromaDB → Grounded generation → Answer + citation
```

- Retrieve enough chunks to cover the fact (typical k = 3–8; tune).  
- Generator may use only retrieved context; if context is weak, refuse to guess.  
- Citation = the URL of the **best supporting chunk** (one link per answer).  
- “Last updated from sources” = latest fetch/ingest date of documents used for that answer (or corpus ingest date if per-doc dates are uniform in v1).

### 7.3 What “good RAG” means here

- Grounded: no facts that are not in retrieved text.  
- Attributable: one real public URL.  
- Scoped: only the five schemes + official process pages.  
- Safe: advice and PII paths are blocked in the application layer, not left to the model alone.

---

## 8. Functional requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| FR1 | User can ask a free-text question in the UI. | P0 |
| FR2 | System retrieves from ChromaDB using MiniLM embeddings. | P0 |
| FR3 | Answers are ≤3 sentences. | P0 |
| FR4 | Every answer includes exactly one source URL. | P0 |
| FR5 | Every answer includes “Last updated from sources: …” | P0 |
| FR6 | Advice / buy-sell / ranking questions are refused with a polite facts-only message + educational official link. | P0 |
| FR7 | Returns questions do not compute or compare; user is pointed to official factsheet. | P0 |
| FR8 | UI shows welcome, 3 example questions, and facts-only note. | P0 |
| FR9 | Ingestion pipeline can (re)load corpus into ChromaDB. | P0 |
| FR10 | App does not persist PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers. | P0 |
| FR11 | Sample Q&A file exists (5–10 queries with answers + links). | P0 |
| FR12 | README documents setup, AMC + scheme scope, and known limits. | P0 |
| FR13 | Source list (CSV or MD) of ingested/used URLs. | P0 |

---

## 9. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR1 | Prototype can run locally with documented setup (Python stack expected given embedding + Chroma). |
| NFR2 | Latency: interactive demo quality (target: answer in a few seconds on a laptop after index is built). |
| NFR3 | Corpus is rebuildable from listed URLs (no hidden private files). |
| NFR4 | Answers remain readable to a non-technical retail user. |
| NFR5 | Failure modes: retrieval miss and model error show a safe fallback, not a hallucinated fee. |

---

## 10. Success metrics (prototype)

These are **eval-style** checks for a milestone, not production analytics.

- **Citation coverage:** 100% of in-scope factual answers have a working public URL.  
- **Grounding:** On a gold set of 5–10 questions, extracted facts (expense ratio, SIP, lock-in, etc.) match the cited page.  
- **Refusal quality:** Advice prompts never produce a recommendation.  
- **Length:** Answers stay within 3 sentences (excluding citation and last-updated line).  
- **PII:** No identifier fields written to logs, Chroma, or local history.  
- **Demo:** Working app **or** ≤3-minute demo video if hosting is not possible.

---

## 11. Deliverables (milestone)

1. Working prototype (hosted link or local app) **or** ≤3-min demo video.  
2. Source list (CSV/MD) including the five scheme URLs used.  
3. README: setup, scope (AMC + schemes), known limits.  
4. Sample Q&A file (5–10 queries, assistant answers, links).  
5. Disclaimer snippet used in the UI.  
6. This PRD as the product spec for the RAG chatbot.

**End output:** RAG chatbot covering ingestion + retrieval as specified in §7.

---

## 12. Risks and open decisions

| Topic | Note |
| --- | --- |
| Groww vs official AMC pages | Seed URLs are Groww. Citations should prefer official HDFC AMC / SEBI / AMFI documents. Confirm which pages are ingested vs merely used to identify schemes. |
| Chunking | Final splitter settings depend on factsheet/KIM layout; validate with the gold Q&A set. |
| Stale data | Factsheets change; ingest date must be visible. No live NAV/returns computation. |
| Model choice for generation | Not specified in the brief; any generator must be strictly grounded. Document the choice in README. |
| Legal | Disclaimer is product UX, not legal sign-off. |

---

## 13. Out of scope for later versions (not v1)

- More AMCs and schemes  
- Streaming quotes, portfolio linking, authenticated holdings  
- Multilingual UI  
- Agent tools that browse the live web on every query (v1 is indexed RAG)  

---

## 14. Appendix — example questions for the UI

1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?  
2. What is the lock-in for HDFC ELSS Tax Saver?  
3. What is the exit load on HDFC Small Cap Fund Direct Growth?  

(Replace with the three that retrieve most reliably after the first eval pass.)
