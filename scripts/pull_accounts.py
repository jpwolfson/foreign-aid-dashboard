#!/usr/bin/env python3
"""Pull monthly USAspending File A snapshots for the seven focus accounts.

The custom-account download endpoint is asynchronous and throttles repeated
generated files. The filing cross-check only requires two checkpoints: the
year-one September close and the latest year-two month. Keeping that request
surface small makes scheduled refreshes reliable while the immutable filing
benchmark supplies the full historical profiles.
"""

import argparse
import csv
import http.client
import io
import json
import ssl
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "accounts.json"
STORE = ROOT / "data" / "file_a_snapshots.csv"
API = "https://api.usaspending.gov"
USER_AGENT = "foreign-aid-dashboard/1.0 (github.com/jpwolfson/foreign-aid-dashboard)"
HEADER = [
    "slug", "reporting_fy", "reporting_period", "treasury_account_symbol",
    "reporting_agency_name", "allocation_transfer_agency_identifier_code",
    "agency_identifier_code", "beginning_period_of_availability",
    "ending_period_of_availability", "main_account_code",
    "budget_authority_appropriated_amount", "total_budgetary_resources",
    "obligations_incurred", "gross_outlay_amount", "last_modified_date",
]


def request_json(path, payload=None, retries=6):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers)
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
                raise RuntimeError(f"USAspending request failed: {path}") from exc
            time.sleep(min(30, 2 ** attempt))


def download_bytes(url, retries=6):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.read()
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            ConnectionError,
            TimeoutError,
        ) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"download failed: {url}") from exc
            time.sleep(min(30, 2 ** attempt))


def available_periods():
    data = request_json("/api/v2/references/submission_periods/")
    out = {}
    for p in data["available_periods"]:
        if p["is_quarter"]:
            continue
        fy, month = p["submission_fiscal_year"], p["submission_fiscal_month"]
        out.setdefault(fy, set()).add(month)
    return out


def request_snapshot(agency, fy, period):
    payload = {
        "account_level": "treasury_account",
        "file_format": "csv",
        "filters": {
            "submission_types": ["account_balances"],
            "fy": str(fy), "period": str(period), "agency": agency,
        },
    }
    job = request_json("/api/v2/download/accounts/", payload)
    status_path = job["status_url"].removeprefix(API)
    for _ in range(90):
        status = request_json(status_path)
        if status["status"] == "finished":
            return download_bytes(status["file_url"])
        if status["status"] in {"failed", "error"}:
            raise RuntimeError(f"USAspending download failed: {status}")
        time.sleep(2)
    raise TimeoutError(f"USAspending download did not finish: {job['file_name']}")


def csv_rows(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("account download zip contained no CSV")
        for name in names:
            text = io.TextIOWrapper(archive.open(name), encoding="utf-8-sig", newline="")
            yield from csv.DictReader(text)


def normalize(blob, accounts, fy, period):
    by_key = {}
    lookup = {(a["aid"], a["main"]): a["slug"] for a in accounts}
    for row in csv_rows(blob):
        slug = lookup.get((row["agency_identifier_code"], row["main_account_code"]))
        if not slug:
            continue
        bpoa, epoa = row["beginning_period_of_availability"], row["ending_period_of_availability"]
        # Keep only two-year cohort TAFS. Other availability periods use the
        # same federal account but do not belong in the filing comparison.
        if not (bpoa.isdigit() and epoa.isdigit() and int(epoa) == int(bpoa) + 1):
            continue
        out = {k: row.get(k, "") for k in HEADER}
        out.update({"slug": slug, "reporting_fy": str(fy), "reporting_period": str(period)})
        key = (slug, str(fy), str(period), out["treasury_account_symbol"])
        # Quarter-end downloads may contain both monthly and quarterly rows.
        # Prefer the most recently published version deterministically.
        prior = by_key.get(key)
        if prior is None or out["last_modified_date"] >= prior["last_modified_date"]:
            by_key[key] = out
    return by_key


def load_store():
    if not STORE.exists():
        return {}
    rows = csv.DictReader(STORE.open(newline=""))
    return {
        (r["slug"], r["reporting_fy"], r["reporting_period"], r["treasury_account_symbol"]): r
        for r in rows
    }


def write_store(store):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for key in sorted(store, key=lambda k: (int(k[1]), int(k[2]), k[0], k[3])):
            writer.writerow(store[key])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="reconcile both filing cross-check checkpoints")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between download requests")
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text())
    periods = available_periods()
    store = load_store()
    present = {(int(k[1]), int(k[2])) for k in store}
    cohort = cfg["fileACrosscheck"]
    year_one, year_two = cohort["yearOne"], cohort["yearTwo"]
    if 12 not in periods.get(year_one, set()):
        raise RuntimeError(f"FY{year_one} P12 is not available from USAspending")
    if not periods.get(year_two):
        raise RuntimeError(f"FY{year_two} has no available USAspending periods")
    checkpoints = [(year_one, 12), (year_two, max(periods[year_two]))]
    wanted = [
        point for point in checkpoints
        if args.full or point not in present or point[0] == year_two
    ]
    print(f"{len(wanted)} fiscal-period snapshot(s); {len(store)} stored TAFS rows")
    for fy, period in wanted:
        replacement_keys = {k for k in store if int(k[1]) == fy and int(k[2]) == period}
        fresh = {}
        for agency in cfg["downloadAgencies"]:
            print(f"FY{fy} P{period:02d} {agency}")
            fresh.update(normalize(request_snapshot(agency, fy, period), cfg["accounts"], fy, period))
            time.sleep(args.pause)
        if not fresh:
            raise RuntimeError(f"FY{fy} P{period:02d} returned no configured account rows")
        for key in replacement_keys:
            store.pop(key, None)
        store.update(fresh)
        write_store(store)
    print(f"Wrote {STORE.relative_to(ROOT)} ({len(store)} TAFS rows)")
    from build_dashboard import main as build
    build()


if __name__ == "__main__":
    main()
