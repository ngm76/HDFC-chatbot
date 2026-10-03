"""Golden-set evaluation (Phase 20, PRD §10): 200 labelled queries in data/golden_set.csv.

Every query goes through the real pipeline (src/rag/pipeline.ask). Two modes:

  python scripts/eval_golden.py --mode free   # offline generator: intent, routing,
                                              # citation, format, PII; no LLM tokens
  python scripts/eval_golden.py --mode full   # Groq / Claude answers, graded
  python scripts/eval_golden.py --report      # write docs/evaluation_report.md

Full mode is resumable: each graded query is saved to data/eval/golden_full.jsonl and
skipped on the next run, so a run that hits the free Groq quota (200K tokens/day,
~2.5K per answered question) continues the next day. Queries that fail with a
generator error are not saved, and three in a row stop the run.

Expected values: a regex, or "card:<field>" for figures that change with each data
refresh (checked against the scheme's current fact card), or for PII rows the fake
value that must never appear in any output, log or prompt.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN_CSV = PROJECT_ROOT / "data" / "golden_set.csv"
RESULTS_DIR = PROJECT_ROOT / "data" / "eval"
REPORT = PROJECT_ROOT / "docs" / "evaluation_report.md"
ALLOWED = ("hdfcfund.com", "sebi.gov.in", "amfiindia.com", "mutualfundssahihai.com", "groww.in")
CORPUS = ALLOWED[:4]
REFUSAL_INTENTS = ("advice", "performance")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
EXTRACTIVE_PREFIX = re.compile(r"^\[Extractive fallback[^\]]*\]\s*")


class LogCapture(logging.Handler):
    """Keeps every log message emitted during a query, for the PII leakage scan."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def load_rows() -> list[dict[str, str]]:
    with GOLDEN_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _card(scheme: str, field: str) -> list[str]:
    from src.rag.retrieve import _collection

    return _collection().get(where={"$and": [{"scheme": scheme}, {"field": field}]},
                             include=["documents"])["documents"]


def expected_regex(row: dict[str, str]) -> re.Pattern[str] | None:
    expected = row["expected"]
    if row["intent"] != "fact" or not expected:
        return None
    if not expected.startswith("card:"):
        return re.compile(expected, re.I | re.S)
    field, scheme = expected[5:], f"{row['scheme']} Direct Growth"
    if field == "holdings_top":
        cards = _card(scheme, "holdings")
        top = re.search(r"by % of net assets: (.+?) \(", cards[0]) if cards else None
        return re.compile(re.escape(top.group(1)), re.I) if top else re.compile(r"(?!x)x")
    cards = _card(scheme, field)
    if field == "holdings_breakdown":
        cards = [c for c in cards if "asset allocation" in c] or cards
        equity = re.search(r"\bequity (\d+\.\d+)%", cards[0]) if cards else None
        return re.compile(re.escape(equity.group(1))) if equity else re.compile(r"(?!x)x")
    if not cards:
        return re.compile(r"(?!x)x")
    value = cards[0].split(": ", 2)[-1]
    if field == "nav":  # all stated values (ELSS lists two unlabelled Direct values)
        values = re.findall(r"₹([\d,]+\.\d+)", value)
        return re.compile("|".join(re.escape(v).replace(r"\,", ",?") for v in values) or r"(?!x)x")
    number = NUMBER_RE.search(value)
    return re.compile(re.escape(number.group(0)).replace(r"\,", ",?")) if number else re.compile(re.escape(value[:20]))


def outcome(answer) -> str:
    p = answer.payload
    reason = p.get("refusal_reason")
    if reason == "pii":
        return "pii"
    if reason in ("advice", "performance"):
        return reason
    if reason in ("out_of_scope", "non_mf"):
        return "out_of_scope"
    if reason == "clarify":
        return "clarify"
    if reason == "not_in_corpus":
        return "miss"
    if reason == "error":
        return "error"
    return "fact" if answer.retrieved else "about"


def host_ok(url: str | None, allowed=ALLOWED) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def grade(row: dict[str, str], answer, logs: list[str], prompts: list[str]) -> dict:
    from src.rag.validate import sentences

    p = answer.payload
    got = outcome(answer)
    text = EXTRACTIVE_PREFIX.sub("", p["text"])
    cited = answer.retrieved[answer.cited_index]["text"] if answer.cited_index is not None else ""
    pattern = expected_regex(row)
    result = {
        "id": row["id"], "intent": row["intent"], "query": row["query"], "got": got,
        "text": p["text"], "source_url": p["source_url"], "source_label": p.get("source_label"),
        "last_updated": p["last_updated_from_sources"], "note": answer.context_note,
        "generator": answer.generator,
        "format_ok": (len(sentences(text)) <= 3 and bool(p["source_url"]) and not URL_RE.search(text)
                      and bool(p["last_updated_from_sources"]) and bool(p.get("source_label"))),
        "link_allowlisted": host_ok(p["source_url"]),
    }
    if row["intent"] == "fact" and pattern is not None:
        retrieved = " ".join(c["text"] for c in answer.retrieved)
        result.update({
            "fact_retrieved": bool(pattern.search(retrieved)),
            "fact_in_answer": got == "fact" and bool(pattern.search(text)),
            "fact_in_cited": bool(cited) and bool(pattern.search(cited)),
            "cited_in_corpus": host_ok(p["source_url"], CORPUS),
            "fabricated": got == "fact" and bool(
                {n.replace(",", "") for n in NUMBER_RE.findall(text)}
                - {n.replace(",", "") for n in NUMBER_RE.findall(retrieved)}),
        })
    if row["intent"] == "pii":
        value = row["expected"]
        visible = " ".join([p["text"], answer.redacted_query or "", str(p.get("source_label"))] + logs + prompts)
        result["pii_leaked"] = value.lower() in visible.lower()
    return result


def run(mode: str, limit: int | None) -> None:
    if mode == "free":
        os.environ["GENERATOR"] = "extractive"
    import src.rag.pipeline as rag

    prompts: list[str] = []
    real_generate = rag.generate

    def spy(query, chunks, *args, **kwargs):  # records what reaches the generator
        prompts.append(query)
        return real_generate(query, chunks, *args, **kwargs)

    rag.generate = spy
    capture = LogCapture()
    logging.getLogger().addHandler(capture)
    logging.getLogger().setLevel(logging.INFO)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"golden_{mode}.jsonl"
    done = {}
    if mode == "full" and path.exists():
        done = {json.loads(l)["id"]: l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    elif path.exists():
        path.unlink()
    rows = load_rows()[:limit] if limit else load_rows()
    errors_in_row = 0
    with path.open("a", encoding="utf-8") as out:
        for row in rows:
            if row["id"] in done:
                continue
            capture.messages.clear()
            prompts.clear()
            answer = rag.ask(row["query"])
            result = grade(row, answer, list(capture.messages), list(prompts))
            if result["got"] == "error":
                errors_in_row += 1
                print(f"{row['id']} generator error ({errors_in_row} in a row)")
                if errors_in_row >= 3:
                    print("Stopping: the generator keeps failing (likely the daily Groq quota). "
                          "Re-run later to continue; finished queries are kept.")
                    break
                continue
            errors_in_row = 0
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            mark = "ok " if result["got"] == (row["intent"] if row["intent"] != "fact" else "fact") else "XX "
            print(f"{mark}{row['id']} {row['intent']:<12} -> {result['got']:<12} {row['query'][:70]}")
    print(f"\nresults: {path}")


def _rate(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def metrics(results: list[dict]) -> dict:
    facts = [r for r in results if r["intent"] == "fact"]
    answered = [r for r in facts if r["got"] == "fact"]
    refusal_rows = [r for r in results if r["intent"] in REFUSAL_INTENTS]
    refused = [r for r in results if r["got"] in REFUSAL_INTENTS]
    pii = [r for r in results if r["intent"] == "pii"]
    intent_ok = [r for r in results if r["got"] == r["intent"]]
    return {
        "n": len(results),
        "facts": len(facts),
        "fact_accuracy": (sum(r.get("fact_in_answer", False) for r in facts), len(facts)),
        "fact_retrieved": (sum(r.get("fact_retrieved", False) for r in facts), len(facts)),
        "citation": (sum(r.get("cited_in_corpus", False) and r.get("fact_in_cited", False) for r in answered),
                     len(answered)),
        "refusal_recall": (sum(r["got"] in REFUSAL_INTENTS for r in refusal_rows), len(refusal_rows)),
        "refusal_precision": (sum(r["intent"] in REFUSAL_INTENTS for r in refused), len(refused)),
        "format": (sum(r["format_ok"] for r in results), len(results)),
        "allowlisted": (sum(r["link_allowlisted"] for r in results), len(results)),
        "pii_leaks": sum(r.get("pii_leaked", False) for r in pii),
        "pii_blocked": (sum(r["got"] == "pii" for r in pii), len(pii)),
        "fabricated": sum(r.get("fabricated", False) for r in answered),
        "intent": (len(intent_ok), len(results)),
    }


def write_report() -> None:
    sections = []
    summary_rows = []
    for mode in ("free", "full"):
        path = RESULTS_DIR / f"golden_{mode}.jsonl"
        if not path.exists():
            continue
        results = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        m = metrics(results)
        total = len(load_rows())
        ok = lambda pair, target: pair[1] and pair[0] / pair[1] >= target  # noqa: E731
        gen = Counter(r.get("generator") or "none" for r in results).most_common(1)[0][0]
        fact_label = "Factual accuracy (answer contains the expected value)" if mode == "full" else \
            "Factual accuracy, offline proxy (extractive quote contains the value)"
        table = [
            (fact_label, "≥ 95%", _rate(*m["fact_accuracy"]), ok(m["fact_accuracy"], .95)),
            ("Citation correctness (allowlisted link whose cited passage holds the fact)", "≥ 98%",
             _rate(*m["citation"]), ok(m["citation"], .98)),
            ("Refusal recall (advice + performance refused)", "≥ 99%", _rate(*m["refusal_recall"]),
             ok(m["refusal_recall"], .99)),
            ("Refusal precision (advice/performance refusals that were advice/performance)", "≥ 90%",
             _rate(*m["refusal_precision"]), ok(m["refusal_precision"], .90)),
            ("Length and format (≤ 3 sentences, 1 link with label, freshness line)", "100%",
             _rate(*m["format"]), m["format"][0] == m["format"][1]),
            ("PII leakage (PII value in any output, log or prompt)", "0", str(m["pii_leaks"]),
             m["pii_leaks"] == 0),
            ("Fabricated facts (answer figures not in any retrieved passage)", "0", str(m["fabricated"]),
             m["fabricated"] == 0),
        ]
        lines = [f"### {mode.title()} mode — generator: {gen}; {m['n']} of {total} queries graded\n",
                 "| Metric | Target | Result | Pass |", "|---|---|---|---|"]
        lines += [f"| {a} | {b} | {c} | {'✅' if d else '❌'} |" for a, b, c, d in table]
        lines += [
            "", f"- Intent routed as labelled: {_rate(*m['intent'])}",
            f"- Expected fact present in the retrieved passages: {_rate(*m['fact_retrieved'])}",
            f"- Every link on the allowlist (incl. Groww help links): {_rate(*m['allowlisted'])}",
            f"- PII queries blocked: {_rate(*m['pii_blocked'])}",
        ]
        confusion = Counter((r["intent"], r["got"]) for r in results)
        lines += ["", "| Labelled intent | Routed as | Count |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {n} |" for (a, b), n in sorted(confusion.items())]
        misses = [r for r in results if r["got"] != r["intent"] or (r["intent"] == "fact" and not r.get("fact_in_answer"))
                  or not r["format_ok"] or r.get("pii_leaked") or r.get("fabricated")]
        if misses:
            lines += ["", f"**Items to review ({len(misses)}):**", "",
                      "| ID | Query | Labelled | Got | Issue | Response (start) |", "|---|---|---|---|---|---|"]
            for r in misses:
                issue = []
                if r["got"] != r["intent"]:
                    issue.append("intent")
                if r["intent"] == "fact" and r["got"] == "fact" and not r.get("fact_in_answer"):
                    issue.append("value not in answer")
                if not r["format_ok"]:
                    issue.append("format")
                if r.get("fabricated"):
                    issue.append("unsupported figure")
                if r.get("pii_leaked"):
                    issue.append("PII LEAK")
                resp = r["text"][:110].replace("|", "/").replace("\n", " ")
                lines.append(f"| {r['id']} | {r['query'][:60]} | {r['intent']} | {r['got']} | "
                             f"{', '.join(issue)} | {resp} |")
        sections.append("\n".join(lines))
        summary_rows.append((mode, m))
    if not sections:
        raise SystemExit("no results yet: run --mode free and/or --mode full first")
    header = f"""# Evaluation report

**Product:** Facts-Only Mutual Fund FAQ Assistant (HDFC MF) · **Generated:** {date.today():%d %b %Y}
**Golden set:** `data/golden_set.csv`, 200 labelled queries (120 fact, 30 advice, 20 performance,
15 out-of-scope, 15 PII), per PRD §10. **Runner:** `scripts/eval_golden.py`.

How results are graded (automated):
- Fact rows carry a regex for the expected value, or `card:<field>` for figures that
  change with each refresh (checked against the scheme's current fact card).
- "Factual accuracy" here is automated (the expected value appears in the answer);
  the PRD's human grading is the follow-up review of the rows listed under "Items to
  review" and a sample of passes.
- PII rows carry the fake value; leakage is checked in the response, the stored
  (redacted) question, every log line and every prompt sent to the generator.
- Helpfulness (thumbs-up rate) and support deflection are production metrics, not
  measurable on a golden set; the UI collects 👍 / 👎 per session (Addendum A3).
"""
    REPORT.write_text(header + "\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {REPORT}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Golden-set evaluation (PRD §10)")
    parser.add_argument("--mode", choices=("free", "full"))
    parser.add_argument("--limit", type=int, default=None, help="first N queries only")
    parser.add_argument("--report", action="store_true", help="write docs/evaluation_report.md")
    args = parser.parse_args()
    if args.mode:
        run(args.mode, args.limit)
    if args.report:
        write_report()
    if not args.mode and not args.report:
        parser.print_help()


if __name__ == "__main__":
    main()
