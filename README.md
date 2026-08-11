# U.S. foreign aid dashboard

A self-updating public dashboard for two related views of U.S. foreign aid:

1. **Appropriation execution** - monthly obligations for seven foreign-assistance
   accounts, normalized by adjusted appropriations. This reproduces Appendix A
   of the Carlile declaration in *Global Health Council v. Trump*, No.
   25-cv-402 (D.D.C.), ECF 202-2.
2. **Grant awards** - grant and cooperative-agreement records made by USAID and
   the Department of State, sourced from USAspending's Award Data Archive API.

The execution view and the award view answer different questions. File A is
account-level budget execution and includes obligations that are not linked to
awards. Award archive records provide recipient-level detail but are not a substitute
for the legal appropriation denominator used in the filing.

## What is included

- Exact court-filing benchmark data for the 20/21 through 25/26 cohorts.
- A File A puller that downloads the two Treasury-account checkpoints needed
  for the filing comparison, aggregates transfer-allocation TAFS, and
  cross-checks the live 25/26 obligations.
- An award puller for USAID and State grants (award type codes 02-05), using
  pre-generated annual archives for history and current-year updates, with a
  durable award store, daily transaction-obligation series, and compact
  dashboard aggregate. Award cohorts use performance start dates; fiscal-year
  flows use `federal_action_obligation` by `action_date`.
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
- `data/execution_profiles.csv` - flat account/cohort/month values behind the
  appropriation execution chart.
- `data/award_obligations_daily.csv` - daily USAID and State transaction flows
  behind the cumulative fiscal-year chart.
- `data/file_a_snapshots.csv` and `data/awards.csv` - durable stores created by
  refresh runs; records are replaced by stable keys, never silently pruned.
- `site/index.html` - static dashboard.

The public site links each CSV directly and provides an expandable table for
every chart. The browser award table intentionally loads only the 1,000 most
recent records (and displays at most 200 filtered results); `data/awards.csv`
is the complete downloadable store.

## Local use

```bash
python scripts/build_dashboard.py
python -m unittest discover -s tests -v
python -m http.server 8000
```

Then open `http://localhost:8000/site/`. To call USAspending:

```bash
python scripts/pull_accounts.py --full
for fy in $(seq 2016 2026); do python scripts/pull_awards.py --archive-fy "$fy"; done
```

The account refresh requests two agency files for the year-one September close
and the latest year-two reporting period. This is deliberately bounded because
USAspending throttles repeated generated custom-download files; the filing
supplies the full historical profiles. The award pull is partitioned by agency
and fiscal year so no large paginated query is trusted as the sole source of
history. The current fiscal year is refreshed on every weekly run. Each annual
archive replaces its daily-obligation partition, so repeated refreshes do not
duplicate transactions. Each archive is checkpointed separately by the
workflow so an API interruption resumes at the incomplete year rather than
restarting history.

## Methodological boundary

Appropriation denominators are legal/budgetary judgments, not mechanically
recoverable from award records. The 25/26 denominators in `accounts.json` are
the adjusted values documented in the declaration (appropriation less
rescissions and amounts precluded from obligation). Adding a future cohort
requires both its year pair and curated denominator in `accounts.json`. This is
a deliberate guardrail against publishing a plausible but legally wrong ratio.

The filing's Chart 6 subtitle repeats the INCLE account code `1022` for NADR.
The dashboard uses the actual NADR account code, `1075`, and records the
correction in the on-page methodology.
