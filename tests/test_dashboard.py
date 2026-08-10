import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_dashboard
import pull_accounts
import pull_awards


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = json.loads((ROOT / "reference" / "court-filing-benchmark.json").read_text())
        cls.config = json.loads((ROOT / "config" / "accounts.json").read_text())

    def test_filing_table_one_is_reproduced(self):
        expected = {
            "esf": [59.75, 70.38, 41.01, 86.47, 75.00, 50.51],
            "da": [60.30, 50.51, 36.85, 26.68, 18.57, 2.80],
            "ghp": [75.58, 85.46, 67.42, 54.46, 46.87, 6.64],
            "aeeca": [58.66, 50.20, 18.37, 30.94, 64.48, 0.00],
            "incle": [38.02, 29.73, 22.07, 43.77, 37.86, 21.27],
            "nadr": [48.18, 44.54, 48.21, 50.26, 36.60, 36.23],
            "df": [10.31, 11.34, 1.35, 4.27, 2.51, 3.81],
        }
        i = self.benchmark["table1Month"] - 1
        for account in self.benchmark["accounts"]:
            actual = [account["profiles"][c][i] for c in self.benchmark["cohorts"]]
            self.assertEqual(actual, expected[account["slug"]])

    def test_all_profiles_have_valid_lengths(self):
        for account in self.benchmark["accounts"]:
            for cohort, values in account["profiles"].items():
                expected = 21 if cohort == "2025/2026" else 24
                self.assertEqual(len(values), expected, (account["slug"], cohort))
                self.assertTrue(all(v >= 0 for v in values))

    def test_headline_findings(self):
        i = 20
        current = []
        below = 0
        for account in self.benchmark["accounts"]:
            vals = [account["profiles"][c][i] for c in self.benchmark["cohorts"]]
            current.append(vals[-1])
            below += vals[-1] < min(vals[:-1])
        self.assertEqual(below, 5)
        self.assertEqual(sorted(current)[len(current) // 2], 6.64)

    def test_nadr_mapping_corrects_filing_subtitle(self):
        nadr = next(a for a in self.config["accounts"] if a["slug"] == "nadr")
        self.assertEqual(nadr["main"], "1075")
        self.assertNotEqual(nadr["main"], "1022")


class FileATests(unittest.TestCase):
    def make_zip(self, rows):
        fields = [
            "reporting_agency_name", "allocation_transfer_agency_identifier_code",
            "agency_identifier_code", "beginning_period_of_availability",
            "ending_period_of_availability", "main_account_code",
            "treasury_account_symbol", "budget_authority_appropriated_amount",
            "total_budgetary_resources", "obligations_incurred",
            "gross_outlay_amount", "last_modified_date",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("AccountBalances.csv", buf.getvalue())
        return out.getvalue()

    def test_transfer_tafs_are_kept_and_wrong_availability_is_excluded(self):
        base = {
            "reporting_agency_name": "USAID", "agency_identifier_code": "072",
            "beginning_period_of_availability": "2025", "ending_period_of_availability": "2026",
            "main_account_code": "1037", "budget_authority_appropriated_amount": "0",
            "total_budgetary_resources": "100", "obligations_incurred": "10",
            "gross_outlay_amount": "2", "last_modified_date": "2026-07-28",
        }
        rows = [
            {**base, "allocation_transfer_agency_identifier_code": "", "treasury_account_symbol": "072-2025/2026-1037-000"},
            {**base, "allocation_transfer_agency_identifier_code": "019", "treasury_account_symbol": "019-072-2025/2026-1037-000"},
            {**base, "allocation_transfer_agency_identifier_code": "", "beginning_period_of_availability": "2024", "ending_period_of_availability": "2025", "treasury_account_symbol": "072-2024/2025-1037-000"},
            {**base, "allocation_transfer_agency_identifier_code": "", "beginning_period_of_availability": "2025", "ending_period_of_availability": "2029", "treasury_account_symbol": "072-2025/2029-1037-000"},
        ]
        accounts = [{"slug": "esf", "aid": "072", "main": "1037"}]
        got = pull_accounts.normalize(
            self.make_zip(rows), accounts, 2026, 9,
            {"yearOne": 2025, "yearTwo": 2026},
        )
        self.assertEqual(len(got), 2)
        self.assertEqual(sum(float(r["obligations_incurred"]) for r in got.values()), 20)

    def test_year_two_crosscheck_adds_year_one_close(self):
        fields = pull_accounts.HEADER
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshots.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
                for fy, period, obligations in [(2025, 12, 400), (2026, 9, 100)]:
                    row = {k: "" for k in fields}
                    row.update({"slug":"esf","reporting_fy":fy,"reporting_period":period,
                                "treasury_account_symbol":f"tas-{fy}","obligations_incurred":obligations,
                                "last_modified_date":"2026-07-31"})
                    writer.writerow(row)
            old = build_dashboard.SNAPSHOTS
            try:
                build_dashboard.SNAPSHOTS = path
                result = build_dashboard.load_file_a_crosscheck([
                    {"slug":"esf","denominators":{"2025/2026":1000}}
                ], {"cohort":"2025/2026", "yearOne":2025, "yearTwo":2026})
            finally:
                build_dashboard.SNAPSHOTS = old
        self.assertEqual(result["accounts"][0]["cumulativeObligations"], 500)
        self.assertEqual(result["accounts"][0]["percent"], 50)


class AwardTests(unittest.TestCase):
    def test_month_partitioning_and_fiscal_year(self):
        windows = list(pull_awards.months(pull_awards.date(2025, 9, 1), pull_awards.date(2025, 11, 3)))
        self.assertEqual(windows[0][1].isoformat(), "2025-09-30")
        self.assertEqual(windows[-1][0].isoformat(), "2025-11-01")
        self.assertEqual(pull_awards.fiscal_year("2025-09-30"), 2025)
        self.assertEqual(pull_awards.fiscal_year("2025-10-01"), 2026)

    def test_archive_transactions_collapse_to_latest_award(self):
        rows = []
        for action, amount, modified in [
            ("2024-10-01", "100", "2024-10-02"),
            ("2025-02-01", "250", "2025-02-02"),
        ]:
            rows.append({
                "assistance_type_code": "03",
                "assistance_award_unique_key": "ASST_TEST_072",
                "award_id_fain": "TEST-1",
                "action_date": action,
                "last_modified_date": modified,
                "total_obligated_amount": amount,
                "total_outlayed_amount_for_overall_award": "50",
                "recipient_name": "Test Recipient",
                "cfda_number": "98.001",
                "awarding_agency_name": "Agency for International Development",
            })
        store = pull_awards.merge_archive({}, rows)
        self.assertEqual(len(store), 1)
        self.assertEqual(store["ASST_TEST_072"]["base_date"], "2024-10-01")
        self.assertEqual(store["ASST_TEST_072"]["amount"], "250.0")


if __name__ == "__main__":
    unittest.main()
