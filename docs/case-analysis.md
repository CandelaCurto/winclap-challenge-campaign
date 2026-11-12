# Case file analysis

The problems `campaigns.csv`, the file delivered for the case, had, and how it looked after
processing. The general rules are in [cleaning rules](cleaning-rules.md); this page has the numbers
of this load.

## The file

- **214 rows and 12 columns**, from September 1 to 22, 2026.
- **12 campaigns** (C1001 to C1012) in 4 countries (AR, CL, CO, MX), 3 objectives (Awareness,
  Consideration, Conversion) and 3 platforms (Google Ads, Meta Ads, LinkedIn Ads). All in USD.
- When read, every column arrives as text: one `"$ 182,41"` cell is enough for the whole spend
  column not to be recognized as a number.

## Problems found

| Problem | Rows | What was done |
|---|---|---|
| Dates in two formats (`2026-09-17` and `17/09/2026`) | 25 | All to dates. With slashes it is day/month: `17/09` allows no other reading |
| Extra spaces in the campaign name | 9 | Trimmed |
| The channel written 8 ways (`GOOGLE ADS`, `google ads`, `meta`, `Facebook Ads`…) | all | Recognized by keyword → `Google Ads`, `Meta Ads`, `LinkedIn Ads` |
| Spend as text with a currency format (`"$ 182,41"`) | 9 | Converted to a number |
| Exact duplicates | 6 | Discarded |
| Negative spend | 5 | Made positive. 4 are kept; the fifth is discarded anyway for other reasons |
| More clicks than impressions (e.g. 114,055 impressions, 114,102 clicks) | 6 | Row discarded |
| Missing conversions | 8 (7 not counting duplicates) | Row discarded (`missing conversions`) |
| Missing revenue | 7 (6 not counting duplicates) | Row discarded (`missing revenue`) |
| Several different rows of the same campaign on the same day | 41 campaign-days | Merged into one row, adding up |
| Two different campaigns with the same name (C1001 and C1006, `CO_AWAR_Google_Q4`) | — | Everything is grouped by `campaign_id`, never by name; the run warns about it |

One row can have several problems: the one for C1011 on 09/17 (line 6) has negative spend, more
clicks than impressions and missing conversions and revenue, and it is also duplicated (line 8). In
`rejected_rows` line 6 carries all its reasons and line 8 says it is a copy of line 6.

## Result

| Step | Rows |
|---|---|
| Rows read | 214 |
| Duplicates discarded | 6 |
| Invalid rows discarded | 17: 6 with more clicks than impressions, 7 without conversions and 6 without revenue (one row has all three reasons) |
| **Valid rows** | **191** (10.7% discarded, below the 20% maximum) |
| Of which, with spend corrected to positive | 4 (1.9%) |
| **Campaign-day rows** | **141** (41 made of 2 or 3 original rows) |
| **Campaigns in the summary** | **12** |

Merge check: total spend and impressions are the same before and after merging.

## Cases that show why each rule

**What costs the most is discarding rows with missing values.** 11 rows were discarded only for
missing conversions or revenue. Their impressions, clicks and spend were valid and are lost with
them: they add up to **USD 11,254.61, 6.6% of the file's spend**. For example, C1004 on 9/4 had two
rows: one of USD 288.06 with 9 conversions and another of USD 2,275.52 with no conversions. Only
the first is kept, so that day shows USD 288.06 of spend. Counting every row discarded by a rule
(not duplicates), USD 15,781.68 of spend is left out of the totals. 10 of the 17 discarded rows
belonged to a day that still has other rows, so 10 published campaign-days are incomplete; the
other 7 were the only row of their day, which is therefore not in `clean_data`. The price of
publishing only complete, verifiable rows; all of them, with their spend, are in `rejected_rows`.

**Blank metrics.** Only CPA is left blank, on 7 days, the ones with 0 conversions: dividing by 0
has no result. CTR, CPC and ROAS have no blanks.

**Why the objective matters when reading.** C1006 is an Awareness campaign with a CPA of
USD 205.85: high, but expected, because it does not seek conversions. It is judged by how much it
was seen (impressions, CTR).

**The negative spend assumption.** The 4 corrected rows add up to USD 2,085.86. If any were a
refund and not a sign error, that amount would be adding spend that never existed; they are listed
in `corrected_rows` to validate it.
