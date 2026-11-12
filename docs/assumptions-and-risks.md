# Assumptions and risks

- **Published totals are below the real ones**, because rows with a missing value are discarded
  along with their good data (see [cleaning rules](cleaning-rules.md)). `discarded_rows` in
  `clean_data` and `spend_excluded` in `campaign_summary` show where and how much; the rows
  themselves are in `rejected_rows`.
- **Each CSV brings the complete history**, not just the new days. That is why every run replaces
  the content of the Sheets.
- **Different rows of the same day are parts, not corrections.** If they were corrected versions of
  the same value, adding them would count it twice. It is the first thing I would validate with
  whoever knows the export.
- **Negative spend is a sign error.** If it were a refund or an adjustment, making it positive would
  add spend that never existed; each case is in `corrected_rows` to validate it.
- **`DD/MM/YYYY` is day/month.** A file with only ambiguous dates (`05/09`) would need the source
  format confirmed. `MM/DD/YYYY` is never accepted, even when unambiguous (`09/17/2026`): the row is
  discarded as an unreadable date.
- **"Today" is the UTC date.** A row dated today is valid and one dated tomorrow is discarded as a
  future date, both judged in UTC (the runner's clock). From 21:00 Argentina time, UTC is already the
  next day.
- **The 20% thresholds** are a judgment call, not a fact: they are adjusted in one line
  (`MAX_DISCARDED_SHARE`, `MAX_CORRECTED_SHARE`).
- **Known number-reading gaps** (covered by `xfail` tests, not fixed yet): thousands groups shorter
  than 3 digits are accepted (`"1,2,3"` reads as 12.3 instead of blank), and a minus sign inside
  accounting parentheses cancels out (`"(-5)"` reads as 5).
