# PRD: Facts-Only Mutual Fund FAQ Assistant (Groww × HDFC MF)

**Date:** Oct 2, 2026 · **Owner:** @Neha
**Original:** [PRD Facts-Only Mutual Fund FAQ Assistant (Groww × HDFC MF).pdf](PRD%20Facts-Only%20Mutual%20Fund%20FAQ%20Assistant%20(Groww%20×%20HDFC%20MF).pdf)
(this Markdown version mirrors the PDF section by section; owner decisions made
after it are recorded separately in the [Addendum](#addendum-owner-decisions-2-oct-2026) and
do not change the PDF's text)

---

## Summary

We will ship an in-app assistant that answers factual questions about five HDFC
Mutual Fund schemes (Direct Plan – Growth) in three sentences or fewer, with exactly
one official source link and a freshness date. It refuses advice, performance and
personal-data requests by design, so it reduces support load without creating SEBI
advice risk.

Assumptions made where the brief was open:

- "Every answer" includes refusals; they follow the same template (≤ 3 sentences, one
  link, freshness line).
- The source link line and the "Last updated" line do not count toward the
  3-sentence limit.
- "Last updated from sources" is the date the cited page was last ingested and
  verified, not today's date.
- v1 is English only, text only, and logged-out answers are allowed (no account
  context is ever used).
- Questions about NAV, AUM, fund managers or holdings are out of scope for v1, even
  though they are factual.

## 1. Problem statement and why it matters

Investors comparing schemes ask the same handful of factual questions, and the
answers are scattered across scheme pages, KIMs, factsheets and TER reports. A simple
question like "What is the exit load on HDFC Small Cap?" often means opening a 40-page
PDF or raising a support ticket.

Support and content teams answer these repetitive questions by hand. Answers drift
from the source, go stale when TERs or exit loads change, and rarely cite where the
fact came from.

A generic chatbot would make this worse. If it says "this fund is a good fit for you"
or compares returns, Groww risks outputs being treated as investment advice under the
SEBI (Investment Advisers) Regulations, 2013, and breaching SEBI's rules on how mutual
fund performance may be presented. Collecting PAN, Aadhaar or account numbers in a
chat also creates exposure under the Digital Personal Data Protection Act, 2023.

**Why now:** a narrow, cited, facts-only assistant lets us remove repetitive support
load and build user trust while keeping regulatory risk close to zero.

## 2. Goals and non-goals

The goal is correct, cited, short factual answers; anything that looks like advice is
a non-goal by design.

**Goals**

- Answer the 7 supported question types for the 5 in-scope schemes accurately, citing
  one official source.
- Refuse advice, performance and comparison-of-merit questions politely, every time,
  with one educational link.
- Never accept, store or echo personal identifiers.
- Give support and content teams a reusable, cited answer for repetitive MF questions.

**Non-goals (v1)**

- Recommending, ranking or suitability-matching schemes.
- Computing, quoting or comparing returns, CAGR, XIRR or NAV history.
- Account-specific help (holdings, transactions, SIP status, redemptions).
- Other AMCs, Regular plans, IDCW options, or schemes outside the five listed.
- Tax advice beyond stating the ELSS lock-in rule.
- Transacting (buy, SIP set-up, redeem) from within the assistant.

## 3. Target users and key use cases

Two groups use the same assistant: retail investors in the app, and internal support
and content teams.

| User | Need | Key use cases |
|---|---|---|
| Retail investor comparing schemes | Quick, trustworthy facts before deciding on their own | "What is the expense ratio of HDFC Flexi Cap Direct?" · "What is the exit load on HDFC Small Cap?" · "What's the riskometer level of HDFC Balanced Advantage?" |
| First-time ELSS investor | Understand lock-in and minimums | "How long is the lock-in on HDFC ELSS Tax Saver?" · "What is the minimum SIP amount?" |
| Existing investor | Find statements for tax filing | "How do I download my capital gains statement?" · "Where do I get my account statement?" |
| Support agent | Paste a correct, cited answer into a ticket | Same factual questions, copied with the source link |
| Content team | Verify facts for in-app content | Check a benchmark or exit load against the official source |

Assumption: support and content teams use the same in-app experience in v1; a
separate internal console is a later phase.

## 4. Scope

v1 covers one AMC, five schemes, one plan variant, seven question types and about 22
official pages.

**AMC:** HDFC Mutual Fund. **Plan variant:** Direct Plan – Growth option only.

**Schemes**

1. HDFC Large Cap Fund (formerly HDFC Top 100 Fund)
2. HDFC Flexi Cap Fund (formerly HDFC Equity Fund)
3. HDFC ELSS Tax Saver (formerly HDFC Taxsaver)
4. HDFC Small Cap Fund
5. HDFC Balanced Advantage Fund

**Supported question types:** expense ratio (TER), exit load, minimum SIP amount, ELSS
lock-in, riskometer level, benchmark index, and how to download account or
capital-gains statements.

**Corpus (~22 pages).** The split below is an assumed allocation; the final list ships
as the source-list deliverable.

| Publisher | Document type | Pages | Answers |
|---|---|---|---|
| HDFC MF | Scheme pages (one per scheme) | 5 | Benchmark, riskometer, min SIP, exit load |
| HDFC MF | Key Information Memorandum / SID extracts | 5 | Exit load, min SIP, ELSS lock-in |
| HDFC MF | Monthly factsheet | 1 | Benchmark, riskometer, TER snapshot |
| HDFC MF | TER disclosure page | 1 | Expense ratio |
| HDFC MF | Account statement and capital-gains statement pages | 2 | Statement download steps |
| SEBI | Riskometer circular | 1 | What riskometer levels mean |
| SEBI | Investor education pages | 2 | Refusal links, investor rights |
| AMFI | Mutual Funds Sahi Hai education pages | 5 | Refusal links, ELSS and SIP basics |

Only domains on an allowlist (HDFC MF, SEBI, AMFI / Mutual Funds Sahi Hai) can be
ingested or cited. No third-party blogs, aggregators or news.

## 5. Functional requirements

Every message passes a PII check first, then intent classification, and only factual
in-scope questions reach retrieval and generation. Each requirement below is written
to be testable.

**Answering**

- **FR-1:** Answer only from retrieved corpus passages; if no passage supports the
  answer above the confidence threshold, say it couldn't find this in official sources
  and link the scheme page, never a guess.
- **FR-2:** Resolve the scheme name, including former names and common short forms
  ("HDFC Top 100", "HDFC Taxsaver"), to one of the five canonical schemes.
- **FR-3:** Default every answer to Direct Plan – Growth and say so when the value
  differs by plan (see edge cases).
- **FR-4:** A post-generation validator rejects any answer that contains a return
  figure, a recommendation verb ("should", "better", "best", "suitable"), more than 3
  sentences, or a link not in the corpus. Rejected answers regenerate once, then fall
  back to the FR-1 "couldn't find" response.

**Citing**

- **FR-5:** Every response carries exactly one link, taken from the metadata of the
  chunk that supports the answer, never generated by the model.
- **FR-6:** Every response ends with "Last updated from sources: DD Mon YYYY", the
  ingest date of the cited page.
- **FR-7:** Citations link to the most specific page available (the scheme page or TER
  page, not the HDFC MF homepage).

**Refusing**

- **FR-8:** Advice, suitability and "which is better" questions get a polite refusal,
  an offer of the facts we can give, and one AMFI or SEBI educational link.
- **FR-9:** Performance and returns questions get a refusal that links the official
  HDFC MF factsheet; no figures are quoted.

**PII handling**

- **FR-10:** Detect PAN, Aadhaar, phone numbers, emails, OTPs and bank or folio account
  numbers on the client before the message is sent, using pattern checks (e.g., PAN
  format, 12-digit Aadhaar with checksum, 10-digit Indian mobile).
- **FR-11:** On detection, block the send, clear the input, and show: "For your safety,
  please don't share personal details like PAN, Aadhaar, account numbers or OTPs. I
  don't need them to answer." Offer a link to Groww's help centre for account-specific
  issues.
- **FR-12:** A server-side redaction pass is the backstop; any PII that reaches the
  server is masked before logging, never sent to the model, and never stored in
  analytics.
- **FR-13:** The assistant never asks for personal details and never uses account
  context, even for logged-in users.

**Out of scope**

- **FR-14:** Questions about other AMCs, other schemes, Regular or IDCW plans, or
  unsupported fields (NAV, AUM, fund manager) get a short message stating what is
  covered, plus one link to the relevant official HDFC MF or AMFI page.
- **FR-15:** Non-MF questions (stocks, loans, general chat) get a one-line redirect to
  Groww help, with no link to a third party.

## 6. Intent classification rules

Intents are checked in a fixed precedence order: PII, then advice, then performance,
then out-of-scope, then fact. A message is answered as a fact only if no earlier rule
fires; when unsure between fact and advice, the classifier must choose advice.

| Precedence | Intent | Rule | Example queries | Response |
|---|---|---|---|---|
| 1 | PII | Message contains a PAN, Aadhaar, phone, email, OTP or account/folio number pattern | "My PAN is ABCDE1234F, show my ELSS lock-in date" · "OTP is 482913, why isn't my statement coming?" | Block send, safety message, help-centre link (FR-10 to FR-13) |
| 2 | Advice | Asks what to buy, sell, hold, switch, or which is better/suitable, or mentions own portfolio or goals | "Should I buy HDFC Small Cap now?" · "Which is better for me, Flexi Cap or Large Cap?" | Polite refusal + one AMFI or SEBI education link |
| 3 | Performance | Asks about returns, CAGR, NAV growth, rankings, or past/future performance | "What were HDFC Flexi Cap's 5-year returns?" · "Has Balanced Advantage beaten its benchmark?" | Refusal + link to the official HDFC MF factsheet |
| 4 | Out-of-scope | Other AMC, scheme, plan or option; unsupported field; non-MF topic | "What's the exit load on SBI Small Cap?" · "Who manages HDFC Large Cap Fund?" | State what is covered + one official link |
| 5 | Fact | One of the 7 supported question types for an in-scope scheme | "What is the expense ratio of HDFC ELSS Tax Saver Direct Growth?" · "How do I download my capital gains statement from HDFC MF?" | ≤ 3-sentence answer + one source link + freshness line |

Mixed messages follow the highest-precedence intent. For example, "What's the exit
load and should I exit now?" is handled as advice, and the refusal offers to share the
exit load as a separate question, so each response keeps a single link.

## 7. Answer format and tone guidelines

Every response, answer or refusal, uses one fixed template: up to 3 sentences, one
source line, one freshness line.

**Template**

1. **Body:** 1–3 sentences. The first sentence states the fact with the full scheme
   name and plan.
2. **Source:** one link with a readable label, e.g. "Source: HDFC Small Cap Fund –
   scheme page".
3. **Freshness:** "Last updated from sources: DD Mon YYYY".

**Tone**

- Neutral, plain English, written for a first-time investor; define a term in a few
  words if needed ("exit load, a fee for redeeming early").
- Numbers with units and conditions: "1% if redeemed within 1 year", "0.xx% per year".
- No hype or judgement words: best, safe, good, ideal, recommended, guaranteed.
- No first-person opinions ("I think", "I'd suggest"); no emoji; no urgency.
- Refusals are warm and brief, never lecture, and always offer what we can answer.

**Sample answer** (illustrative; link and date are placeholders)

> **Q:** How long is the lock-in for HDFC ELSS Tax Saver?
>
> HDFC ELSS Tax Saver (Direct Plan – Growth) has a 3-year lock-in from the date units
> are allotted. For SIPs, each instalment is locked in for 3 years from its own
> allotment date, so units unlock in stages. These units cannot be redeemed or
> switched out before their lock-in ends.
>
> Source: HDFC ELSS Tax Saver – scheme page (hdfcfund.com)
> Last updated from sources: 28 Sep 2026

**Sample refusal** (illustrative)

> **Q:** Which is better for me, HDFC Flexi Cap or HDFC Large Cap?
>
> I can share facts about these schemes, but I can't recommend which one suits you. I
> can tell you either fund's expense ratio, exit load, riskometer level or benchmark if
> that helps. To learn how to choose a fund for your goals, see AMFI's investor
> education page.
>
> Source: Mutual Funds Sahi Hai – investor education (mutualfundssahihai.com)
> Last updated from sources: 28 Sep 2026

## 8. Edge cases

Each edge case has a defined behaviour so engineering and QA can test it directly.

| Edge case | Example | Expected behaviour |
|---|---|---|
| Scheme renames | "Exit load on HDFC Top 100?" | Map the former name to HDFC Large Cap Fund via an alias table; answer under the current name and mention the former name once ("HDFC Large Cap Fund, formerly HDFC Top 100 Fund…"). Same for HDFC Equity Fund and HDFC Taxsaver. |
| Direct vs Regular ambiguity | "What's the expense ratio of HDFC Flexi Cap?" | Answer for Direct Plan – Growth and label it. For fields that differ by plan (TER), add: "Regular Plan values differ; see the linked page." Questions explicitly about Regular or IDCW are out of scope. |
| Stale data | TER changed after last ingest | Re-ingest TER and scheme pages weekly and factsheets on publication. If the cited page is older than its freshness limit (TER 7 days, factsheet 35 days, KIM 180 days), add "Please check the linked page for the latest value" as one of the 3 sentences. If a page fails to fetch, keep the last good version and alert the owner. |
| Factual comparison | "Exit loads of Small Cap vs Flexi Cap?" | Allowed only if one official page supports both facts (e.g., the factsheet or TER page); otherwise answer for the first scheme and invite a second question. Never say which is lower is "better". |
| Merit comparison | "Which has lower risk, so should I pick it?" | Treated as advice: refusal + education link. |
| Scheme not in corpus | "HDFC Mid Cap Opportunities exit load?" | State the five covered schemes and link the HDFC MF schemes listing page; never answer from model memory. |
| Partial or misspelled names | "hdfc smallcap", "BAF" | Fuzzy-match to the canonical scheme if confidence is high; if two schemes match, ask the user to pick from chips. |
| Conflicting sources | Scheme page and factsheet disagree | Prefer the most recent document by date; log the conflict for content review. |
| Statement download | "How do I get my CAS?" | Give the steps from the HDFC MF statement page, linking it; never offer to fetch or email the statement. |

## 9. UI requirements

The assistant opens as a bottom sheet from each in-scope scheme page and from Help,
with a persistent disclaimer and three tappable example questions.

- **Entry points:** an "Ask about this fund" button on the five scheme pages
  (pre-fills the scheme) and a link in the Help centre.
- **Welcome line:** "Hi! Ask me facts about 5 HDFC Mutual Fund schemes – expense
  ratio, exit load, SIP minimums, lock-in, riskometer, benchmark or statements."
- **Example questions (3 chips):** "What is the exit load on HDFC Small Cap Fund?" ·
  "How long is the HDFC ELSS Tax Saver lock-in?" · "How do I download my capital gains
  statement?"
- **Disclaimer:** "Facts-only. No investment advice." shown pinned under the header,
  always visible, never dismissible.
- **Input hint:** "Ask a factual question. Don't share PAN, Aadhaar or account details."
- **Answer bubble:** body text, then the source as a tappable label that opens in the
  in-app browser, then the freshness line in secondary text.
- **PII block state:** inline warning above the input, the input cleared, nothing sent.
- **Feedback:** thumbs up/down on each answer, with an optional reason ("wrong",
  "outdated", "not helpful").
- No transaction CTAs (Invest, Start SIP) inside the assistant, so answers are never
  framed as a nudge to act.
- **Accessibility:** screen-reader labels on chips and links; text scales with system
  font size.

## 10. Success metrics

Launch is gated on a golden set of 200 labelled queries (about 120 fact, 30 advice, 20
performance, 15 out-of-scope, 15 PII), re-run on every corpus or prompt change.

| Metric | Definition | Launch target | How measured |
|---|---|---|---|
| Factual accuracy | Fact answers whose value matches the cited source exactly | ≥ 95% | Golden set, human-graded |
| Citation correctness | Answers whose single link is allowlisted and contains the stated fact | ≥ 98% | Golden set + automated link check |
| Refusal recall | Advice/performance queries correctly refused | ≥ 99% | Golden set + weekly red-team set |
| Refusal precision | Refusals that were truly advice/performance (not over-refusing facts) | ≥ 90% | Golden set |
| Length and format compliance | Responses with ≤ 3 sentences, exactly 1 link, freshness line | 100% | Automated validator on all production traffic |
| PII leakage | PII values found in logs, prompts or analytics | 0 | Daily log scan |
| Fabricated facts | Answers with no supporting passage | 0 in golden set | Groundedness check |
| Helpfulness | Thumbs-up rate on answers | ≥ 80% | In-app feedback |
| Support deflection | Drop in tickets on the 7 question types for these schemes | 20% in 90 days | Support ticket tagging |

Refusal recall is set higher than precision on purpose: a missed advice question is a
regulatory risk, while an over-refusal only costs convenience.

## 11. Known limitations and risks

The biggest risks are an advice-like answer slipping through and a stale number being
shown as current; both have layered controls.

| Risk or limitation | Impact | Mitigation |
|---|---|---|
| Advice-like phrasing slips past the classifier | Regulatory exposure | Classifier biased to advice when unsure; post-generation banned-phrase validator; compliance review of samples before launch and monthly |
| Stale TER or exit load shown | Wrong fact, user trust | Freshness limits and re-ingest schedule (section 8); freshness date on every answer |
| Retrieval picks the wrong scheme's chunk | Wrong fact with a real citation | Chunk metadata filtered by resolved scheme before ranking; accuracy tests per scheme |
| PDF parsing errors on KIM and factsheet tables | Wrong numbers | Manual verification of extracted values for all 5 schemes at each ingest |
| PII patterns miss unusual formats | Personal data reaches server | Server-side redaction backstop; no raw message storage |
| 3-sentence limit cuts nuance (e.g., tiered exit loads) | Incomplete answer | Link always points to the full condition; templates for common multi-tier loads |
| Narrow scope frustrates users | Low engagement | Clear welcome copy on coverage; out-of-scope answers name what is covered; scope expansion in a later phase |
| Official URLs change | Broken links | Weekly link-health check; alert on 4xx/5xx |

Out of v1: Hindi and other languages, voice, Regular and IDCW plans, other AMCs, and
account-specific answers.

## 12. Deliverables checklist

The release is complete when all six items below are reviewed by Product,
Engineering and Compliance.

1. **Working prototype:** RAG pipeline with PII pre-check, intent classifier, retrieval
   over the ~22-page corpus, generation, and the format validator, embedded in a Groww
   app build.
2. **Source list:** every corpus URL with publisher, document type, scheme, question
   types it answers, freshness limit and last ingest date.
3. **README:** architecture, setup, how to re-ingest sources, how to add a scheme alias,
   how to run the golden-set evaluation, and known limitations.
4. **Sample Q&A:** at least 2 examples per intent (section 6), plus every edge case in
   section 8, with expected responses.
5. **Disclaimer:** "Facts-only. No investment advice." pinned in the UI, with copy
   signed off by Compliance.
6. **Evaluation report:** golden-set results against every launch target in section 10.

---

## Addendum: owner decisions (2 Oct 2026)

Decisions taken by the owner after the PRD above, for this prototype. Where they
differ from the PRD, the decision governs and the difference is a documented
deviation.

| # | Topic | Decision | Relation to the PRD |
|---|---|---|---|
| A1 | Extra features already built (NAV with date, fund size/AUM, fund managers and their other schemes, holdings and "does it hold X", holdings analysis, glossary definitions, fund-house details; fund cards and fact sheet in the UI) | **Kept as is**, documented as additions beyond v1 | Deviation from the Summary assumption, non-goals and FR-14 (NAV, AUM, fund manager, holdings listed as out of scope) |
| A2 | Conversation memory (last 25 exchanges; follow-ups such as "And its exit load?") | **Kept** | Not covered by the PRD; no conflict |
| A3 | Thumbs up/down feedback (§9) | Shown in the UI; **not saved** anywhere (session only), since no user details are collected | Narrows §10 "Helpfulness" measurement for the prototype |
| A4 | Golden set (§10, 200 queries) | Built in full. A free retrieval-and-intent mode runs all 200 without LLM calls; the full answer-graded run is occasional (it uses most of a day's Groq free-tier quota) and runs locally, never on Render | Implements §10 within free-tier limits |
| A5 | Groww help-centre links (FR-11, FR-15) | PII block → https://groww.in/help/mutual-funds; non-MF redirect → https://groww.in/help (both verified as "Help & Support \| Groww"). Fixed links shown by the app, never fetched, indexed or cited as sources; listed in the source list with role `help` | Implements FR-11 / FR-15 |
| A6 | Problem statement deliverable "Source list … of the 5 URLs you used" | Superseded by this PRD's ~22-page official corpus; `docs/problemstatement.txt` points here for details | Reconciles the brief with §4 |
| A7 | Prototype form factor | Standalone Streamlit web app (deployed on Render's free plan), not embedded in a Groww app build; entry points from scheme pages / Help centre (§9) are not applicable | Adapts §9 and deliverable 1 to a prototype |
