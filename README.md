# Campaign performance pipeline

A Python pipeline that takes the daily campaign performance CSV as the ad platforms export it,
cleans it, computes CTR, CPC, CPA and ROAS, builds a per-campaign summary and publishes it to Google
Sheets. It runs on GitHub Actions when new data is pushed, by hand, and every Monday.

## TL;DR

**Deliverables**

- Repository: [CandelaCurto/winclap-challenge-campaign](https://github.com/CandelaCurto/winclap-challenge-campaign)
- Results Sheet: [`clean_data` and `campaign_summary`](https://docs.google.com/spreadsheets/d/1fSj01Pwtsq3kPatY8jxhsvIrMPL7OUkeMafvnGNybZ8/edit)
- Review Sheet: [`rejected_rows` and `corrected_rows`](https://docs.google.com/spreadsheets/d/1riiICt4jCo14nDha1lX9h72UQN_Sf_pY5PiILsG72cw/edit)
- A successful workflow run: [Actions run 43228363428](https://github.com/CandelaCurto/winclap-challenge-campaign/actions/runs/43228363428)

**Key cleaning decisions**

1. **A row missing any number is discarded, never filled with 0**, and kept with its reason in
   the review Sheet.
2. **One row per date + `campaign_id` + currency:** different rows of the same day are parts and
   are added up; identical rows (after normalizing) are duplicates and are dropped.
3. **Metrics are recomputed over totals, never averaged**, and are left blank (not 0) when the
   denominator is 0.
4. **Negative spend is a sign error:** it is made positive and logged in `corrected_rows`.
5. **Impossible rows are discarded with their reason:** more clicks than impressions, negative
   values, unreadable or future dates (judged in UTC).
6. **Messy formats are normalized, not guessed:** two date formats, `"$ 182,41"`-style amounts,
   channels recognized by keyword; anything ambiguous (`1e3`, `09/17/2026`) is discarded.
7. **Nothing disappears silently:** every discarded or corrected row goes to the review Sheet as it
   came, with its file line.
8. **A broken file is never published:** if more than 20% of the rows are discarded or corrected,
   the run fails and the Sheets keep the previous data.

## How to run it

Requires Python 3.11 or newer and `make`.

```bash
make install          # creates .venv and installs the dependencies
make check            # black --check + tests: nothing is published, no credentials needed
make run-local        # processes data/campaigns.csv into output/, without publishing
```

`make help` lists every command. To process another file:
`.venv/bin/python src/pipeline.py --input other.csv --no-publish`.

To publish to Google Sheets:

1. A Google Cloud service account with the Sheets and Drive APIs enabled, and its JSON key.
2. Both Sheets shared as **Editor** with that service account's email.
3. `cp .env-template .env`, fill in `SPREADSHEET_ID`, `REVIEW_SPREADSHEET_ID` (optional) and
   `GOOGLE_APPLICATION_CREDENTIALS`, then `make run`.

In GitHub Actions the key is the `GOOGLE_CREDENTIALS` secret and the Sheet IDs are the
`SPREADSHEET_ID` and `REVIEW_SPREADSHEET_ID` repository variables; see
[how to update the data](docs/updating-data.md).

## What it publishes

| Sheet | Tab | Content |
|---|---|---|
| Results | `clean_data` | One row per campaign and day, with its metrics |
| Results | `campaign_summary` | One row per campaign: totals and metrics recomputed over the totals |
| Review | `rejected_rows` | Each discarded row as it came, its file line and the reason |
| Review | `corrected_rows` | Each corrected row as it came and the correction made |

Each run replaces the tabs' content (running twice never duplicates data) and also writes them as
CSVs in `output/` (`clean_data.csv`, `campaign_summary.csv`, `rejected_rows.csv`,
`corrected_rows.csv`).

```
data/campaigns.csv → validate → clean → merge by campaign-day → metrics → summary → quality gate → Google Sheets
```

## Repository

| Path | What it is |
|---|---|
| `src/pipeline.py` | The whole pipeline |
| `tests/` | One file per stage; `tests/fixtures/` has a fixed copy of the case CSV |
| `data/campaigns.csv` | The CSV that is processed (today, the case's original) |
| `requirements.txt`, `requirements-dev.txt` | Pinned dependencies (runtime, and black + pytest) |
| `pyproject.toml`, `.python-version` | Tool configuration; Python 3.11, the minimum supported |
| `Makefile`, `.env-template` | Local commands and the environment variables they read |
| `.github/workflows/pipeline.yml` | Lint and tests on Python 3.11 and 3.14, then publish |

## More detail

- [Cleaning rules](docs/cleaning-rules.md): every rule and why, merging, metrics and quality checks.
- [Data dictionary](docs/data-dictionary.md): what each published column is and how it is computed.
- [Case file analysis](docs/case-analysis.md): the problems of the delivered CSV and its numbers.
- [How to update the data](docs/updating-data.md): new CSVs and the GitHub Actions setup.
- [Assumptions and risks](docs/assumptions-and-risks.md)
- [Scaling improvements](docs/scaling-improvements.md)
