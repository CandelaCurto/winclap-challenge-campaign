# How to update the data

The pipeline always reads `data/campaigns.csv`. To process new data, replace that file **with the
same name**:

- **From the GitHub website:** `data` folder → *Add file → Upload files* → drag the new CSV named
  `campaigns.csv` → *Commit changes*.
- **From git:** copy the file to `data/campaigns.csv`, commit and push to `main`.

When the new file arrives, the workflow runs on its own. If the file is broken, the run ends in red
with the reason, the results Sheet keeps the previous data and the review Sheet shows what was
discarded or corrected.

The most common exports are accepted: comma- or semicolon-separated (Excel in Spanish), in UTF-8
(with or without BOM) or Latin-1 (Excel on Windows). Columns have to have the same names; their
order, upper or lower case, surrounding spaces and extra columns do not matter.

## In GitHub Actions

- **When it runs:** when a new CSV is pushed to `data/`, by hand (*Actions → Campaign pipeline →
  Run workflow*) and every Monday at 9:00 Argentina time (12:00 UTC).
- **What it does:** checks the formatting and runs the tests on Python 3.11 and 3.14; **only if both
  pass**, it runs the pipeline once, on Python 3.11. One run at a time, with a 10-minute limit.
- **What it leaves:** the run report as a table on the run's page, warnings as annotations, and
  `output/` as a downloadable artifact.
- **Configuration** (*Settings → Secrets and variables → Actions*):
  - Secret `GOOGLE_CREDENTIALS`: the content of the service account's JSON key.
  - Variables `SPREADSHEET_ID` and `REVIEW_SPREADSHEET_ID`: the IDs of the results and review
    Sheets (the part of their URL between `/d/` and `/edit`).
- GitHub disables a public repo's scheduled workflows after 60 days without activity; they are
  re-enabled with one click in the Actions tab.
