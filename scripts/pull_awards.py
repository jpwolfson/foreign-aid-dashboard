#!/usr/bin/env python3
"""Pull USAID and State grant/cooperative-agreement awards from USAspending."""

import argparse
import calendar
import csv
import http.client
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "accounts.json"
STORE = ROOT / "data" / "awards.csv"
OUTPUT = ROOT / "data" / "awards.json"
API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USER_AGENT = "foreign-aid-dashboard/1.0 (github.com/jpwolfson/foreign-aid-dashboard)"
AWARD_TYPES = ["02", "03", "04", "05"]
FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Start Date", "End Date",
    "Award Amount", "Total Outlays", "Awarding Agency", "Awarding Sub Agency",
    "Funding Agency", "Funding Sub Agency", "Award Type", "Description",
    "Base Obligation Date", "Last Modified Date", "generated_internal_id",
    "primary_assistance_listing",
]
HEADER = [
    "id", "award_id", "base_date", "start_date", "end_date", "amount",
    "outlays", "recipient", "recipient_uei", "award_type", "assistance_listing",
    "awarding_agency", "awarding_subagency", "funding_agency",
    "funding_subagency", "description", "last_modified",
]


def api_post(payload, retries=6):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            ConnectionError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            if attempt == retries - 1:
                raise RuntimeError("USAspending award query failed") from exc
            time.sleep(min(30, 2 ** attempt))


def months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        last = calendar.monthrange(y, m)[1]
        yield date(y, m, 1), date(y, m, last)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def query_month(agency, start, end):
    page, out = 1, {}
    while True:
        payload = {
            "subawards": False, "limit": 100, "page": page,
            "filters": {
                "award_type_codes": AWARD_TYPES,
                "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
                "agencies": [{"type": "awarding", "tier": "toptier", "name": agency}],
            },
            "fields": FIELDS, "sort": "Award ID", "order": "asc",
        }
        data = api_post(payload)
        for row in data.get("results", []):
            aid = str(row.get("generated_internal_id") or row.get("internal_id") or row.get("Award ID"))
            listing = row.get("primary_assistance_listing") or {}
            if isinstance(listing, dict):
                listing = listing.get("code") or listing.get("program_number") or ""
            out[aid] = {
                "id": aid, "award_id": row.get("Award ID") or "",
                "base_date": row.get("Base Obligation Date") or row.get("Start Date") or "",
                "start_date": row.get("Start Date") or "", "end_date": row.get("End Date") or "",
                "amount": str(round(float(row.get("Award Amount") or 0), 2)),
                "outlays": str(round(float(row.get("Total Outlays") or 0), 2)),
                "recipient": row.get("Recipient Name") or "", "recipient_uei": row.get("Recipient UEI") or "",
                "award_type": row.get("Award Type") or "", "assistance_listing": str(listing),
                "awarding_agency": row.get("Awarding Agency") or "",
                "awarding_subagency": row.get("Awarding Sub Agency") or "",
                "funding_agency": row.get("Funding Agency") or "",
                "funding_subagency": row.get("Funding Sub Agency") or "",
                "description": row.get("Description") or "",
                "last_modified": row.get("Last Modified Date") or "",
            }
        meta = data.get("page_metadata", {})
        if not meta.get("hasNext"):
            break
        page += 1
        if page > 10000:
            raise RuntimeError("award pagination exceeded safety cap")
    return out


def load_store():
    if not STORE.exists():
        return {}
    return {r["id"]: r for r in csv.DictReader(STORE.open(newline=""))}


def fiscal_year(iso):
    d = date.fromisoformat(iso[:10])
    return d.year + (d.month >= 10)


def write_outputs(store):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for row in sorted(store.values(), key=lambda r: (r["base_date"], r["id"])):
            writer.writerow(row)

    monthly, fys = defaultdict(lambda: {"awards": 0, "obligations": 0.0}), defaultdict(lambda: {"awards": 0, "obligations": 0.0})
    valid = []
    for row in store.values():
        try:
            month, fy = row["base_date"][:7], fiscal_year(row["base_date"])
        except (ValueError, TypeError):
            continue
        amount = float(row["amount"] or 0)
        monthly[month]["awards"] += 1; monthly[month]["obligations"] += amount
        fys[fy]["awards"] += 1; fys[fy]["obligations"] += amount
        valid.append(row)
    recent = sorted(valid, key=lambda r: (r["base_date"], float(r["amount"] or 0)), reverse=True)[:1000]
    payload = {
        "generated": date.today().isoformat(), "status": "available" if valid else "awaiting-refresh",
        "definition": "Prime grants and cooperative agreements (USAspending award type codes 02-05) awarded by USAID or the Department of State.",
        "totalAwards": len(valid),
        "monthly": [{"month": k, "awards": v["awards"], "obligations": round(v["obligations"], 2)} for k, v in sorted(monthly.items())],
        "fiscalYears": [{"fy": k, "awards": v["awards"], "obligations": round(v["obligations"], 2)} for k, v in sorted(fys.items())],
        "recentAwards": recent,
    }
    OUTPUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"Wrote {STORE.relative_to(ROOT)} ({len(store)} awards) and {OUTPUT.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="reconcile all history")
    parser.add_argument("--months", type=int, default=6, help="trailing months for incremental refresh")
    parser.add_argument("--pause", type=float, default=.35)
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text())
    today = date.today()
    start = date.fromisoformat(cfg["awardSeriesStart"])
    if not args.full:
        y, m = today.year, today.month - args.months + 1
        while m < 1:
            y, m = y - 1, m + 12
        start = max(start, date(y, m, 1))
    store = load_store()
    for first, last in months(start, today):
        last = min(last, today)
        for agency in cfg["awardAgencies"]:
            print(f"{agency}: {first} .. {last}")
            fresh = query_month(agency, first, last)
            store.update(fresh)  # old awards touched by amendments are refreshed
            time.sleep(args.pause)
        write_outputs(store)
    write_outputs(store)


if __name__ == "__main__":
    main()
