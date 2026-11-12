# Cleaning rules

Every rule the pipeline applies, and why. The numbers of the case file are in
[case analysis](case-analysis.md); what each published column means is in the
[data dictionary](data-dictionary.md).

## A row with any missing number is discarded

If a row is missing any of its numbers (impressions, clicks, spend, conversions or revenue), the
whole row is discarded and the reason says which column was missing (`missing conversions`). Other
rules were tried before this one; these are the reasons it was chosen:

1. **Blank is not zero, and it cannot be filled in.** A 0 is a value ("we measured and there was
   none"); a blank is its absence ("we don't know"). Turning it into 0 would invent a value: it
   would say those conversions did not exist.
2. **An incomplete row contaminates the totals.** If a row with spend but no conversions is kept,
   when the campaign is added up the spend counts in full and the conversions only in part: the CPA
   looks worse because of a missing value, not because of the campaign. Keeping those rows forces a
   special rule (computing the CPA only with the days that have the value), and then
   `spend / conversions` in the table no longer gives the `cpa` shown: an analyst who does not know
   the rule reads it as an error.
3. **What is published can be verified without knowing any rule.** With every row complete, each
   metric is redone from the columns of the same row (`cpa = spend / conversions`), per day and in
   the summary.
4. **The rule scales.** It is the same for any numeric column: it does not depend on which value
   comes blank in this file (today, conversions and revenue; tomorrow it may be another).
5. **It is not lost from sight.** Each discarded row stays in `rejected_rows`, as it came and with
   its reason; if too much is discarded (more than 20%) the pipeline does not publish.

**The cost:** along with the missing value, the good ones in that row (its impressions, clicks and
spend) are lost, so the published totals are below the real ones. For an efficiency analysis (CTR,
CPC, CPA, ROAS), complete and verifiable data was preferred over complete totals with biased
metrics. **That cost is visible:** the rows of one day are added up as parts, so a day that lost a
part would otherwise be published with only the rest. `clean_data.discarded_rows` says how many rows
of each campaign-day were discarded (above 0 means the day is incomplete), and
`campaign_summary.spend_excluded` says how much spend each campaign lost that way. Alternatives to
recover that data are in [scaling improvements](scaling-improvements.md).

## The rest of the rules

| Situation | What it does | Why |
|---|---|---|
| Dates `YYYY-MM-DD` or `DD/MM/YYYY` | Converts them to dates | Same value in another format |
| Extra spaces in text | Trims them | Otherwise the same campaign looks like two |
| Channel written many ways | Recognizes it by keyword: "google"/"youtube" → Google Ads; "meta"/"facebook"/"instagram" → Meta Ads; "linkedin" → LinkedIn Ads | A new variant (`Google Ads Search`) is recognized on its own; only a truly new platform needs one more line |
| Unknown channel | Keeps it as it came and warns | The row has valid data: discarding it would make spend disappear |
| Channel different from the campaign name's (`AR_CONV_Meta_Q4`) | Warns | Cross-check: something was loaded wrong |
| Same campaign name in more than one `campaign_id` | Warns | Everything is grouped by ID, but in the Sheet they look like the same campaign |
| Numbers with `$`, `USD`, comma or dot (`"$ 182,41"`, `"1.234,5"`) | Converts them | The last separator is decimal if 1 or 2 digits follow it; otherwise it is a thousands separator |
| Number in parentheses (`"(182.41)"`) | Reads it as negative | Accounting convention |
| Text that is not a number (`1e3`, `n/a`) | Treats it as blank and discards the row | Never guessed: `rejected_rows` shows what came |
| Negative spend | Makes it positive and records it in `corrected_rows` | Spend cannot be negative: a sign error is assumed and the row is kept |
| Row identical to another (once normalized) | Discards the copy | A duplicate would count the same thing twice |
| More clicks than impressions | Discards the row | A click needs an impression |
| Negative impressions, clicks, conversions or revenue | Discards the row | Impossible value |
| Unreadable or future date | Discards the row | A day that has not happened cannot have performance (`2062-09-17` is a typo). "Today" is the UTC date, the GitHub Actions runner's clock: today is valid, tomorrow is future |
| Any missing number | Discards the row (`missing <column>`) | See above |
| Count with decimals (12.5 clicks) | Treats it as blank and discards the row | Never silently rounded |

Every discarded row stays in `rejected_rows` and every corrected row in `corrected_rows`, as they
came in the file, to audit what was removed or changed without trusting the script blindly.

## One row per campaign and day

**The key is date + `campaign_id` + currency.** If several **different** rows arrive for the same
campaign and day, they are read as **parts** of the day (for example, ad groups) and added up. If
they are **identical**, they are a duplicate and the copy is discarded. Currency is in the key
because adding dollars to pesos gives a meaningless number. Name, channel, country and objective are
not in the key: they are fixed attributes of the campaign, and if one came written differently one
day, it must not split the row; the most frequent value is used (on a tie, the first
alphabetically) and the log warns.

**Summed amounts are rounded to the cent**, to remove the noise of adding decimals
(`486.29999999999995`). Metrics are not rounded: the format is applied when publishing.

## Metrics

**CTR = clicks / impressions · CPC = spend / clicks · CPA = spend / conversions · ROAS = revenue /
spend.** A single function computes them per row and over the summary totals, so the formulas cannot
drift apart between the two tables.

**If the denominator is 0, the metric is left blank.** For example, the CPA of a day with no
conversions. Not 0, because a CPA of 0 would say the conversions came for free. Not infinity,
because it cannot be added, charted or compared. A 0 on top is valid: revenue 0 gives ROAS 0 (money
was spent and nothing came back).

**The summary recomputes the metrics over the totals**, never averaging the daily ones: the average
gives a USD 10 day the same weight as a USD 1,000 one.

**The campaign objective is for reading the metrics, not for computing them.** An Awareness campaign
is not judged by its CPA, but the CPA is computed the same as for the rest: if the rule changed with
the objective, the same column would mean different things depending on the row.

## Quality

- **The file is validated before processing.** If a column is missing, it is empty or it only has
  the header, it stops with a message that says what happened (`is missing columns: ['spend']`).
- **A broken file is not published.** If no valid row is left, if more than 20% of the rows are
  discarded or if spend has to be corrected in more than 20% (a sign that the platform's export
  changed), the results Sheet is not touched and the run fails: the Sheet keeps the previous data
  and GitHub notifies by email. The review is published anyway, because it is exactly what needs
  looking at.
- **Tests before publishing.** They cover each rule and the case file end to end, on Python 3.11 and
  3.14. They use a fixed copy of the case CSV, not `data/campaigns.csv`, which changes with every
  load: the tests check the rules; the quality gate checks each week's file.
- **A tab is never left empty.** Each tab is resized to the new table and overwritten (blank cells
  are written as empty, which clears them); nothing is cleared first, so a failed write leaves data
  in the tab.
- **Values are written as they are** (`RAW` mode): a text starting with `=` does not run as a
  formula. Dates go as real dates, formatted `YYYY-MM-DD`.
- **Amounts are shown without a currency symbol:** `$` is mistaken for pesos; the `currency` column
  says which currency it is. CTR is shown as a percentage, and amounts and ROAS with two decimals.
