# Scaling improvements

## Recovering the data of rows with missing values

Today they are discarded whole, and `discarded_rows` / `spend_excluded` show where (see
[cleaning rules](cleaning-rules.md)). Alternatives to keep their good data, from least to most
effort:

- **Base columns for each metric:** keep every row and add `spend_with_conversions` and
  `spend_with_revenue` to the summary, the spend of the days that do have that value. Total spend is
  complete and each metric stays verifiable at a glance
  (`cpa = spend_with_conversions / conversions`), at the cost of two columns to explain.
- **A completeness flag:** keep the rows with their blank in `clean_data`, mark each one with a
  `complete` (yes/no) column and compute the summary only with the complete ones. The analyst sees
  everything and chooses what to use.
- **Ask for the missing value:** the rows in `rejected_rows` are a list of what is missing. If the
  platform allows re-exporting those days (conversion data often arrives late), they are loaded in
  the next CSV and come in on their own.
- **Imputing** (estimating the missing value with an average) is not recommended: in a performance
  analysis an invented value is worse than a missing one.

## Beyond this file

- **Automatic data source:** instead of uploading the CSV to the repo, read it from a Google Drive
  folder or from each platform's API (Google Ads, Meta, LinkedIn).
- **Incremental files:** if the platforms exported only the new days, store each file and combine
  them by date and campaign, keeping the most recent version of each day.
- **Retries:** enable gspread's retries for transient Google API errors. A failed write no longer
  empties a tab, but it can leave it with part of the new data until the next run.
- **History:** store each run with its load date in a database (BigQuery, for example) to compare
  weeks, with the Sheet as a view.
