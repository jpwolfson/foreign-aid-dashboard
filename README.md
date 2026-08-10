# U.S. foreign aid dashboard

A self-updating public dashboard for two related views of U.S. foreign aid:

1. **Appropriation execution** - monthly obligations for seven foreign-assistance
   accounts, normalized by adjusted appropriations. This reproduces Appendix A
   of the Carlile declaration in *Global Health Council v. Trump*, No.
   25-cv-402 (D.D.C.), ECF 202-2.
2. **Grant awards** - grant and cooperative-agreement records made by USAID and
   the Department of State, sourced from the USAspending Award Search API.

The execution view and the award view answer different questions. File A is
account-level budget execution and includes obligations that are not linked to
awards. Award Search provides recipient-level detail but is not a substitute
for the legal appropriation denominator used in the filing.

## What is included

- Exact court-filing benchmark data for the 20/21 through 25/26 cohorts.
- A File A puller that downloads monthly Treasury-account snapshots from
  USAspending, aggregates transfer-allocation TAFS, and cross-checks the live
  25/26 obligations against the filing.
- An award puller for USAID and State grants (award type codes 02-05), with a
  durable award store and compact dashboard aggregate.
- A dependency-free static site, tests, and GitHub Actions for weekly refreshes
  and GitHub Pages deployment.

## Repository layout

- `config/accounts.json` - account/TAFS mapping and curated denominators.
- `reference/court-filing-benchmark.json` - transcribed Appendix A values.
- `scripts/pull_accounts.py` - incremental/full File A downloader.
- `scripts/pull_awards.py` - incremental/full award downloader.
- `scripts/build_dashboard.py` - merges the immutable benchmark with live data.
- `data/dashboard.json` - execution data consumed by the site.
- `data/awards.json` - compact award aggregate consumed by the site.
- `data/file_a_snapshots.csv` and `data/awards.csv` - durable stores created by
  refresh runs; records are replaced by stable keys, never silently pruned.
- `site/index.html` - static dashboard.

## Local use

```bash
python scripts/build_dashboard.py
python -m unittest discover -s tests -v
python -m http.server 8000
```

Then open `http://localhost:8000/site/`. To call USAspending:

```bash
python scripts/pull_accounts.py --full
python scripts/pull_awards.py --full
```

The first full account backfill requests two agency files for each available
monthly reporting period. Later runs fetch only new/current snapshots. The
award pull is partitioned by agency and month so no large paginated query is
trusted as the sole source of a fiscal year.

## Methodological boundary

Appropriation denominators are legal/budgetary judgments, not mechanically
recoverable from award records. The 25/26 denominators in `accounts.json` are
the adjusted values documented in the declaration (appropriation less
rescissions and amounts precluded from obligation). A future cohort appears in
the live File A data automatically, but percentage-of-appropriation reporting
stays explicitly unavailable until its curated denominator is added. This is a
deliberate guardrail against publishing a plausible but legally wrong ratio.

The filing's Chart 6 subtitle repeats the INCLE account code `1022` for NADR.
The dashboard uses the actual NADR account code, `1075`, and records the
correction in the on-page methodology.
