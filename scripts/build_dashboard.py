#!/usr/bin/env python3
"""Build the public execution JSON from the immutable filing benchmark.

If a File A snapshot store exists, add a live cross-check for the 25/26
cohort. The filing remains the display baseline; live data never silently
overwrites the independently published values.
"""

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "accounts.json"
BENCHMARK = ROOT / "reference" / "court-filing-benchmark.json"
SNAPSHOTS = ROOT / "data" / "file_a_snapshots.csv"
OUTPUT = ROOT / "data" / "dashboard.json"


def money(value):
    return float(value or 0)


def load_file_a_crosscheck(accounts):
    if not SNAPSHOTS.exists():
        return {
            "status": "awaiting-refresh",
            "message": "Run scripts/pull_accounts.py to add the live USAspending File A cross-check.",
            "latestPeriod": None,
            "accounts": [],
        }

    with SNAPSHOTS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"status": "awaiting-refresh", "latestPeriod": None, "accounts": []}

    # Filing cohort 25/26: year-one P12 plus year-two cumulative obligations.
    # Period 1 (October) is not a monthly DATA Act submission.
    latest_p = max(
        (int(r["reporting_period"]) for r in rows if int(r["reporting_fy"]) == 2026),
        default=None,
    )
    index = defaultdict(float)
    newest_date = None
    for r in rows:
        key = (
            r["slug"], int(r["reporting_fy"]), int(r["reporting_period"])
        )
        index[key] += money(r["obligations_incurred"])
        if r.get("last_modified_date"):
            newest_date = max(newest_date or r["last_modified_date"], r["last_modified_date"])

    result = []
    for account in accounts:
        denom = account.get("denominators", {}).get("2025/2026")
        if not latest_p or not denom:
            continue
        first = index[(account["slug"], 2025, 12)]
        second = index[(account["slug"], 2026, latest_p)]
        obligations = first + second
        result.append({
            "slug": account["slug"],
            "denominator": denom,
            "yearOneObligations": round(first, 2),
            "yearTwoObligations": round(second, 2),
            "cumulativeObligations": round(obligations, 2),
            "percent": round(obligations / denom * 100, 4),
        })
    return {
        "status": "available" if result else "partial",
        "latestPeriod": f"FY2026P{latest_p:02d}" if latest_p else None,
        "lastModified": newest_date,
        "accounts": result,
    }


def main():
    cfg = json.loads(CONFIG.read_text())
    benchmark = json.loads(BENCHMARK.read_text())
    definitions = {a["slug"]: a for a in cfg["accounts"]}
    cohorts = benchmark["cohorts"]
    cutoff_index = benchmark["table1Month"] - 1

    accounts = []
    for item in benchmark["accounts"]:
        definition = definitions[item["slug"]]
        table_values = [item["profiles"][c][cutoff_index] for c in cohorts]
        current, priors = table_values[-1], table_values[:-1]
        rank = 1 + sum(v < current for v in priors)
        accounts.append({
            **definition,
            "profiles": item["profiles"],
            "juneSecondYear": dict(zip(cohorts, table_values)),
            "currentPercent": current,
            "priorMin": min(priors),
            "priorMax": max(priors),
            "gapToPriorMin": round(current - min(priors), 2),
            "rankOfSix": rank,
            "belowAllFivePriors": current < min(priors),
        })

    current_values = [a["currentPercent"] for a in accounts]
    output = {
        "generated": date.today().isoformat(),
        "benchmark": benchmark["source"],
        "cohorts": cohorts,
        "cutoffMonth": benchmark["table1Month"],
        "summary": {
            "medianCurrentPercent": statistics.median(current_values),
            "medianPriorLow": min(benchmark["table1Medians"][:-1]),
            "belowAllFivePriors": sum(a["belowAllFivePriors"] for a in accounts),
            "accountCount": len(accounts),
        },
        "accounts": accounts,
        "table1Medians": dict(zip(cohorts, benchmark["table1Medians"])),
        "fileA": load_file_a_crosscheck(cfg["accounts"]),
        "method": {
            "numerator": "Cumulative new obligations and upward adjustments; year-two values add the year-one September total.",
            "denominator": "Enacted appropriation net of rescissions and amounts precluded from obligation, as documented in the filing.",
            "monthConvention": "Month 1 is October and shown as zero; month 13 carries forward the prior September value.",
            "nadrCorrection": "NADR is matched to main account 1075. Chart 6 prints 1022, the INCLE code, in its subtitle.",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(accounts)} accounts)")


if __name__ == "__main__":
    main()
