# Scheme registry

**AMC:** HDFC Mutual Fund  
**Plans in scope:** Direct Growth  
**Corpus:** the five public Groww scheme pages named in `docs/problemstatement.txt`.
They are the only documents in the vector database, and answers cite them.

The loader reads **`data/sources.csv` only**. This file is human documentation.

---

## Five schemes

| Category | Scheme (AMC name) | Internal `scheme` value | Source page (`role=ingest`) |
| --- | --- | --- | --- |
| Large cap | HDFC Large Cap Fund | `HDFC Large Cap Fund Direct Growth` | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi cap | HDFC Flexi Cap Fund (formerly **HDFC Equity Fund**, renamed 29 Jan 2021) | `HDFC Flexi Cap Fund Direct Growth` | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver | `HDFC ELSS Tax Saver Fund Direct Growth` | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small cap | HDFC Small Cap Fund | `HDFC Small Cap Fund Direct Growth` | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Hybrid | HDFC Balanced Advantage Fund | `HDFC Balanced Advantage Fund Direct Growth` | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

Chroma metadata uses the internal `scheme` value, so retrieval scheme filters match.

## Reference links (`role=reference`: never fetched or searched)

These appear only in refusal messages, as the problem statement requires:

| Use | URL |
| --- | --- |
| Educational link for advice / out-of-scope refusals | https://www.amfiindia.com/investor |
| "Link to the official factsheet" for returns / performance questions | https://files.hdfcfund.com/s3fs-public/2026-09/HDFC%20MF%20Factsheet%20-%20August%202026.pdf |

## What the loader keeps from each Groww page

**Kept:** everything the page states except what the brief rules out.
- NAV (with Groww's date), min SIP / first / second investment, fund size (AUM), expense ratio
- exit load (current and history), stamp duty, tax on redemption
- holdings: count and the full list (name, sector, instrument, % of assets)
- fund managers (name, since, education, experience, other schemes they manage)
- riskometer ("rated … risk"), investment objective, benchmark
- glossary definitions (expense ratio, exit load, stamp duty, tax)
- fund house details (custodian, address, incorporation, AMC total AUM) and registrar (CAMS)

**Dropped** (see `_clean_groww` in `src/ingest/load.py`):
- Site menus and the footer link farm.
- Returns, return calculator, rankings and Groww's star rating. This is
  performance or opinion content, which the brief forbids.
- "Compare similar funds" (other AMCs' returns).
- Groww's auto-generated "About" sentence. It gives the AMC's total AUM as the
  fund's AUM and names a single manager.

## Known gaps

- **ELSS lock-in** is not stated on Groww's ELSS page.
- **How to download capital-gains / account statements** is not covered. Groww only
  names the registrar (CAMS, camsonline.com).
- Groww figures differ from HDFC's own documents by date and basis. For example,
  the Large Cap expense ratio is 1.03% on Groww vs 0.98% (Direct) in the August
  2026 HDFC factsheet.
- **History:** until 2026-09-27 the corpus was official HDFC / AMFI / SEBI documents
  (scheme pages, KIM PDFs, the August factsheet, statement guides), and Groww
  URLs were seeds only (PRD §5.2). It was switched to Groww-only to follow the
  problem statement. The earlier evaluation results are in `docs/eval_notes.md`.
