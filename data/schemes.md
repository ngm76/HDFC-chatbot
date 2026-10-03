# Scheme registry

**AMC:** HDFC Mutual Fund
**Plans in scope:** Direct Plan – Growth (default for every answer, PRD FR-3)
**Corpus:** 24 official pages from HDFC MF, SEBI and AMFI / Mutual Funds Sahi Hai
(PRD §4), listed in `data/sources.csv`, plus 2 Groww help links (Addendum A5).

The loader reads **`data/sources.csv` only**. This file is human documentation:
names, aliases, what each source gives, and known gaps.

Verified on 2026-10-02: every row was fetched from Python with the loader's
settings (`User-Agent`, 30 s timeout) and returned HTTP 200 with usable text.

---

## Five schemes

| Category | Scheme (AMC name) | Internal `scheme` value | Former names and aliases (FR-2) |
| --- | --- | --- | --- |
| Large cap | HDFC Large Cap Fund | `HDFC Large Cap Fund Direct Growth` | HDFC Top 100 Fund, HDFC Top 100, HDFC Large Cap |
| Flexi cap | HDFC Flexi Cap Fund | `HDFC Flexi Cap Fund Direct Growth` | HDFC Equity Fund (renamed 29 Jan 2021), HDFC Flexicap |
| ELSS | HDFC ELSS Tax Saver | `HDFC ELSS Tax Saver Fund Direct Growth` | HDFC Taxsaver, HDFC Tax Saver, HDFC ELSS, "HDFC ELSS - Tax Saver Fund" (TER file) |
| Small cap | HDFC Small Cap Fund | `HDFC Small Cap Fund Direct Growth` | HDFC Smallcap, HDFC Small Cap |
| Hybrid | HDFC Balanced Advantage Fund | `HDFC Balanced Advantage Fund Direct Growth` | HDFC BAF, BAF, HDFC Balanced Advantage |

Chroma metadata uses the internal `scheme` value; shared documents use `ALL`.
Aliases are applied in code in Phase 15 (`src/schemes.py`).

## Sources (`role=ingest`, 24 rows)

| # | Publisher | Doc type | Covers | Answers | Freshness limit | Notes |
|---|---|---|---|---|---|---|
| 1–5 | HDFC MF | `scheme_page` | One scheme each | Expense ratio, exit load, min SIP (₹100; ELSS ₹500), riskometer, benchmark, ELSS lock-in; also NAV, AUM, fund managers (A1) | 7 days | `hdfcfund.com/explore/mutual-funds/<scheme>/direct`. 5.4–7.6k chars. Also carries performance tables, which must be dropped at load (Phase 13). These are the citation for scheme misses (FR-1) |
| 6–10 | HDFC MF | `kim` | One scheme each | Exit load (with tiers), min SIP, ELSS lock-in ("statutory lock in of 3 years"), riskometer, benchmark | 180 days | 61–65k chars each. All five are the 21 Nov 2025 editions (updated 2026-10-03 from the KIM hub page) |
| 11 | HDFC MF | `factsheet` | All five (per-fund pages) | TER snapshot, riskometer, benchmark, NAV, AUM, managers, holdings (A1) | 35 days | August 2026 edition, 744k chars. The September 2026 edition is not published yet (403 on 2026-10-02). Also the performance-refusal link (FR-9) |
| 12 | HDFC MF | `ter` | All five, Direct and Regular | Expense ratio (TER), dated | 7 days | `HDFCMF_SCHEMES_TER_30-09-2026.xls`, linked from the TER reports page. Despite the `.xls` name it is an **.xlsx** workbook (zip); readable with the standard library, no new dependency. The reports page itself is JS-rendered (101 chars) so it is not ingested |
| 13 | HDFC MF | `statement_guide` | All | Account statement, CAS, capital-gains statement options; CAS timing | 365 days | Request-statement page; the request form itself (folio entry) is never used |
| 14 | HDFC MF | `statement_guide` | All | Step-by-step capital-gains statement via CAMS / KFintech | 365 days | Learners' Corner article |
| 15 | SEBI | `riskometer` | All | The six riskometer levels and how they're assigned | 365 days | Circular SEBI/HO/IMD/DF3/CIR/P/2020/197, 5 Oct 2020. The circular's HTML page is a PDF viewer (0 chars), so the PDF is the row; page 1 has a garbled Hindi header to strip |
| 16 | SEBI | `education` | All | MF investor FAQs: expense ratio, exit load, riskometer, benchmark, statements | 365 days | `faqfiles/sep-2024` PDF, 46k chars. Advice-refusal link candidate (FR-8) |
| 17 | SEBI | `education` | All | Investor rights, grievance redressal | 365 days | `investor.sebi.gov.in` Investor Charter (65k chars, broad; chunk by heading) |
| 18 | AMFI | `education` | All | General investor education, TER basics | 365 days | Existing out-of-scope link (`educational_source()` needs an `amfiindia.com` row) |
| 19–24 | AMFI (Mutual Funds Sahi Hai) | `education` | All | ELSS basics, lock-in, SIP, loads, how the riskometer is derived, Direct vs Regular | 365 days | Short pages (0.9–3.2k chars). Educational context only; scheme facts always come from HDFC pages |

## Help links (`role=help`, never ingested or searched)

| Use | URL | Verified |
| --- | --- | --- |
| PII block message (FR-11) | https://groww.in/help/mutual-funds | 200, "Help & Support \| Groww" |
| Non-MF redirect (FR-15) | https://groww.in/help | 200, "Help & Support \| Groww" |

## Coverage of the 7 question types

| Question type | Scheme-specific source | Shared / educational source |
| --- | --- | --- |
| Expense ratio | TER file (#12), scheme pages, factsheet | SEBI FAQ, Sahi Hai Direct vs Regular |
| Exit load | Scheme pages, KIMs | SEBI FAQ, Sahi Hai loads |
| Minimum SIP | Scheme pages, KIMs | Sahi Hai SIP |
| ELSS lock-in | ELSS KIM (#8), ELSS scheme page | Sahi Hai ELSS, lock-in |
| Riskometer | Scheme pages, KIMs, factsheet | SEBI circular, Sahi Hai riskometer |
| Benchmark | Scheme pages, KIMs, factsheet | SEBI FAQ |
| Statement download | n/a (AMC-wide) | HDFC statement pages (#13, #14), SEBI FAQ |

Every type is covered for every scheme where it applies (lock-in applies to ELSS only).

## Known gaps and notes

- **Which document answers what (Phase 14):** expense ratio from the TER file; exit
  load, min SIP, riskometer, benchmark, AUM, lock-in and managers from the scheme
  pages; NAV, holdings and holdings analysis from the factsheet; full exit-load
  rules, lump-sum minimums and the ELSS lock-in rule from the KIMs.
- **ELSS NAV:** the factsheet's PDF text lists two Direct Plan NAVs (₹94.510 and
  ₹1,512.010) without the Growth / IDCW labels, so the card states both and does not
  guess; the scheme page shows NAV only via JavaScript.
- **Factsheet expense ratio not used:** it is the base expense ratio excluding
  brokerage and transaction costs (e.g. Large Cap Direct 0.98%), a different basis
  from the TER file's total TER (1.04%).
- **Managers differ by date:** the scheme page lists today's managers; the factsheet
  lists managers as on its date (e.g. new names effective September 2026). Both are
  indexed with their source and date.

- **Allowlist:** `mutualfundssahihai.com` and `investor.sebi.gov.in` (covered by the
  `sebi.gov.in` suffix) must be on the loader allowlist. `mutualfundssahihai.com` is
  not there yet, so it is added in Phase 13.
- **Loader support (Phase 13):** the TER workbook needs an `.xlsx` reader. Scheme
  pages need their performance sections dropped.
- **Dated URLs:** KIM, factsheet and TER file names change with each edition, and the
  hub pages (`/mutual-funds/factsheets`, `/fund-documents/kim`) are JS-rendered, so
  new editions are updated here by hand (Phase 18 adds the check).
- **Not ingested:** SIDs (KIMs carry the same facts in 1/10 the size), the TER reports
  HTML page (JS only), fund presentations and leaflets (marketing material).
- **Regular plan and IDCW:** TER for Regular is present in the TER file and used only
  for the "Regular Plan values differ" note (FR-3); other Regular/IDCW questions are
  out of scope (FR-14).
- **History:** Groww scheme pages were the corpus from 2026-09-27 to 2026-10-02 (MVP).
  They were removed in Phase 12 per the PRD; Groww appears only as the two help links.
