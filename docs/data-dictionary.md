# Data dictionary

What each column of the results Sheet's tabs is and how it is computed.

## Columns in both tabs

| Column | What it is | How it is computed |
|---|---|---|
| `campaign_id` | Unique campaign code | From the file |
| `campaign_name` | Name: `COUNTRY_OBJECTIVE_PLATFORM_PERIOD` | From the file, without extra spaces. If a campaign has more than one, the most frequent (ties: the first alphabetically). Two campaigns can share a name (C1001 and C1006): use `campaign_id` to tell them apart |
| `channel` | Platform: Google Ads, Meta Ads or LinkedIn Ads | Recognized by keyword in the file's channel. An unknown channel is kept as it came |
| `country` | Campaign country | From the file |
| `objective` | Objective: Awareness, Consideration or Conversion | From the file |
| `currency` | Currency of every amount in the row | From the file |

## `clean_data`: one row per campaign and day

| Column | What it is | How it is computed |
|---|---|---|
| `date` | Day | From the file (accepts `YYYY-MM-DD` and `DD/MM/YYYY`) |
| `impressions` | Times the ad was shown that day | Sum of the rows of that campaign and day |
| `clicks` | Clicks of the day | Sum of the rows of that campaign and day |
| `conversions` | Conversions of the day | Sum of the rows of that campaign and day |
| `spend` | Spend of the day | Sum of the rows of that campaign and day. Negative spend was made positive (see `corrected_rows`) |
| `revenue` | Revenue of the day | Sum of the rows of that campaign and day |
| `ctr` | Click-through rate: clicks per impression | `clicks / impressions` |
| `cpc` | Cost per click | `spend / clicks` |
| `cpa` | Cost per conversion | `spend / conversions`. Blank if there were no conversions |
| `roas` | Dollars returned per dollar spent | `revenue / spend` |

## `campaign_summary`: one row per campaign

| Column | What it is | How it is computed |
|---|---|---|
| `impressions` | Campaign impressions | Sum of every day |
| `clicks` | Campaign clicks | Sum of every day |
| `conversions` | Campaign conversions | Sum of every day |
| `spend` | Total campaign spend | Sum of every day |
| `revenue` | Campaign revenue | Sum of every day |
| `ctr` | Campaign click-through rate | `clicks / impressions`, over the totals |
| `cpc` | Campaign cost per click | `spend / clicks`, over the totals |
| `cpa` | Campaign cost per conversion | `spend / conversions`, over the totals. Blank if there were no conversions |
| `roas` | Campaign return on spend | `revenue / spend`, over the totals |

## Blank cells

They only appear in the metrics, when they cannot be computed because it would mean dividing by 0
(for example, the CPA of a day with no conversions). **They never mean 0.** Rows that were missing
a number were discarded: they are in `rejected_rows` of the review Sheet, with their reason.
