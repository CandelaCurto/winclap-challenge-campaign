"""Campaign performance pipeline.

Reads the CSV as exported by the ad platforms, cleans it, computes metrics and publishes the result
to Google Sheets. The cleaning decisions are explained in the README.

Usage: python src/pipeline.py [--no-publish] [--input PATH]
"""

import argparse
import io
import json
import logging
import os
import re
from pathlib import Path

import gspread
import pandas as pd

log = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parent.parent  # src/pipeline.py -> repo root
RAW_CSV = ROOT / "data" / "campaigns.csv"
# Local copies of what goes to each tab, to review without opening the Sheets.
DAILY_CSV = ROOT / "output" / "campaigns_daily.csv"
SUMMARY_CSV = ROOT / "output" / "campaign_summary.csv"
REJECTED_CSV = ROOT / "output" / "rejected_rows.csv"
CORRECTED_CSV = ROOT / "output" / "corrected_rows.csv"

# Results Sheet (SPREADSHEET_ID)
DAILY_TAB = "clean_data"
SUMMARY_TAB = "campaign_summary"
# Review Sheet (REVIEW_SPREADSHEET_ID): what the cleaning removed or changed, so it can be audited.
REJECTED_TAB = "rejected_rows"
CORRECTED_TAB = "corrected_rows"

# If the cleaning discards more than this, the file is broken and nothing is published: the Sheet
# keeps the data of the previous run. Today 10.7% is discarded; 20% leaves room for a bad day
# without letting through a file with, say, a whole column exported wrong.
MAX_DISCARDED_SHARE = 0.20
# Same for corrections: a few are data-entry errors, but if many rows need correcting, the way the
# platform exports has changed (for example, spend as negative) and someone has to look before
# publishing. Today 1.9% is corrected.
MAX_CORRECTED_SHARE = 0.20

RAW_COLS = [
    "date",
    "campaign_id",
    "campaign_name",
    "channel",
    "country",
    "objective",
    "impressions",
    "clicks",
    "spend",
    "conversions",
    "revenue",
    "currency",
]
TEXT_COLS = ["campaign_id", "campaign_name", "channel", "country", "objective", "currency"]
COUNT_COLS = ["impressions", "clicks", "conversions"]
MONEY_COLS = ["spend", "revenue"]
NUMERIC_COLS = COUNT_COLS + MONEY_COLS
METRIC_COLS = ["ctr", "cpc", "cpa", "roas"]

# Primary key of the clean data: one row per campaign, day and currency. Currency is part of the
# key because adding dollars to pesos gives a meaningless number; today everything is USD.
KEY_COLS = ["date", "campaign_id", "currency"]
# Fixed attributes of each campaign. They are not part of the key: if one day they come written
# differently, they would split that day's row in two. A single value per campaign is used (see
# campaign_attributes).
CAMPAIGN_ATTRS = ["campaign_name", "channel", "country", "objective"]
OUTPUT_ID_COLS = ["date", "campaign_id", *CAMPAIGN_ATTRS, "currency"]

# Each platform is recognized by a keyword, however its name is written ("GOOGLE ADS",
# "Google Ads Search", "Facebook Ads"...). A new platform is added here.
CHANNEL_KEYWORDS = {
    "Google Ads": ["google", "youtube"],
    "Meta Ads": ["meta", "facebook", "instagram"],  # Facebook Ads is Meta Ads' former name
    "LinkedIn Ads": ["linkedin"],
}


def load_raw(path: Path) -> pd.DataFrame:
    """Reads the CSV and checks its shape before going on.

    If it is not the expected file, it stops with a message that says what is missing, instead of
    failing later with an error nobody understands. It accepts the two most common exports:
    comma- or semicolon-separated (Excel in Spanish), and encoded as UTF-8 or Latin-1 (Excel on
    Windows).

    Args:
        path: The CSV to read.

    Returns:
        Every column of RAW_COLS as text, in that order. The index is the file's line number (the
        header is line 1).

    Raises:
        SystemExit: If the file is empty, is not a CSV, lacks a column or has no data rows.
    """
    content = path.read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
        log.warning("%s is not UTF-8: read as Latin-1", path.name)
    header = text.split("\n", 1)[0]
    separator = ";" if header.count(";") > header.count(",") else ","
    try:
        # Everything is read as text: each type is converted explicitly in normalize().
        raw = pd.read_csv(io.StringIO(text), sep=separator, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raise SystemExit(f"{path.name} is empty: it does not even have the header.")
    except pd.errors.ParserError as error:
        raise SystemExit(f"{path.name} cannot be read as a CSV: {error}")
    raw.columns = raw.columns.str.strip().str.lower()  # 'Spend ' is the same column as 'spend'

    missing = [col for col in RAW_COLS if col not in raw.columns]
    if missing:
        raise SystemExit(
            f"{path.name} is missing columns: {missing}. Received: {list(raw.columns)}."
        )
    extra = [col for col in raw.columns if col not in RAW_COLS]
    if extra:
        log.warning("Columns the pipeline does not use, ignored: %s", extra)
    if raw.empty:
        raise SystemExit(f"{path.name} has no rows: only the header.")

    raw = raw[RAW_COLS]
    raw.index = raw.index + 2  # the index is the file's line (line 1 is the header)
    return raw


def parse_dates(raw: pd.Series) -> pd.Series:
    """Parses dates written as YYYY-MM-DD or DD/MM/YYYY.

    Args:
        raw: Dates as text.

    Returns:
        The parsed dates. Whatever fits neither format is left blank (NaT).
    """
    iso = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    day_first = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(day_first)


# The only things that may come with a number: a symbol or a 3-letter currency code.
CURRENCY_MARKS = re.compile(r"(?i)\bUS\$|\b[a-z]{3}\b|[$€£]")


def to_number(text: str) -> float | None:
    """Reads a number written with comma or dot, as decimal or thousands separator.

    The last separator is decimal only when 1 or 2 digits (the cents) follow it; otherwise every
    separator is a thousands separator:
    '$ 182,41' -> 182.41 · '1.234,5' -> 1234.5 · '1,234.50' -> 1234.5 · '114.055' -> 114055.
    Between parentheses it is negative, as in accounting: '(182.41)' -> -182.41.

    Args:
        text: The value as it came in the file.

    Returns:
        The number, or None when the text is blank or something is left that is not part of a
        number ('1e3', 'n/a'): it is never guessed.
    """
    digits = CURRENCY_MARKS.sub("", text).replace(" ", "")
    negative = digits.startswith("(") and digits.endswith(")")
    if negative:
        digits = digits[1:-1]
    if not re.fullmatch(r"-?[\d.,]*\d[\d.,]*", digits):
        return None  # blank, or something that is not a number
    decimals = re.search(r"[.,](\d{1,2})$", digits)
    if decimals:
        whole = re.sub(r"[.,]", "", digits[: decimals.start()])
        digits = f"{whole}.{decimals.group(1)}"
    else:
        digits = re.sub(r"[.,]", "", digits)
    value = float(digits)
    return -value if negative else value


def parse_numbers(raw: pd.Series) -> pd.Series:
    """Converts a column of numbers written as text, warning about what could not be read.

    Args:
        raw: The column as text.

    Returns:
        The column as floats; unreadable or blank values are NaN.
    """
    values = pd.to_numeric(raw.map(to_number), errors="coerce")
    unreadable = values.isna() & raw.str.strip().ne("")
    if unreadable.any():
        log.warning(
            "%s: %d values that are not numbers are left blank: %s",
            raw.name,
            int(unreadable.sum()),
            sorted(raw[unreadable].unique())[:5],
        )
    return values


def classify_channel(text: str) -> str | None:
    """Maps however a channel is written to its canonical platform name.

    Args:
        text: The channel as written ('GOOGLE ADS', 'Facebook Ads'...).

    Returns:
        The platform from CHANNEL_KEYWORDS, or None when no keyword matches.
    """
    lowered = text.lower()
    for channel, keywords in CHANNEL_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            return channel
    return None


def name_platform(campaign_name: str) -> str | None:
    """Returns the platform named in the campaign name: AR_CONV_Meta_Q4 -> Meta Ads.

    Args:
        campaign_name: A name following COUNTRY_OBJECTIVE_PLATFORM_..., as the file uses.

    Returns:
        The platform, or None when the name does not follow the convention.
    """
    parts = campaign_name.split("_")
    return classify_channel(parts[2]) if len(parts) >= 3 else None


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Gives each column its type and writes every value in a single way. Discards no rows.

    Args:
        raw: The file as returned by load_raw.

    Returns:
        A copy with trimmed text, dates, canonical channels, counts as Int64 and money as floats.
    """
    df = raw.copy()
    for col in TEXT_COLS:
        df[col] = df[col].str.strip()

    df["date"] = parse_dates(df["date"].str.strip())

    channel = df["channel"].map(classify_channel)
    unknown = df.loc[channel.isna(), "channel"].unique()
    if len(unknown):
        # A new channel does not stop the pipeline: it is kept as it came and a warning is logged.
        log.warning("Unrecognized channels, kept as they come: %s", list(unknown))
    df["channel"] = channel.fillna(df["channel"])

    # Cross-check: the channel has to match the platform in the campaign name.
    from_name = df["campaign_name"].map(name_platform)
    mismatch = from_name.notna() & (from_name != df["channel"])
    if mismatch.any():
        log.warning(
            "Channel differs from the one in the campaign name on lines %s",
            list(df.index[mismatch]),
        )

    for col in COUNT_COLS:
        counts = parse_numbers(df[col])
        fractional = counts.notna() & (counts % 1 != 0)
        if fractional.any():
            # A count with decimals is not silently rounded: it is left blank and reported.
            log.warning("%s with decimals, left blank: %d rows", col, int(fractional.sum()))
        df[col] = counts.mask(fractional).astype("Int64")
    for col in MONEY_COLS:
        df[col] = parse_numbers(df[col])
    return df


def invalid_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """Evaluates every validity rule on every row.

    Args:
        df: Normalized rows.

    Returns:
        One boolean column per rule, named after the reason; True where the row breaks it.
    """
    rules = {
        "unreadable date": df["date"].isna(),
        # A day that has not happened yet cannot have performance: it is a typo (2062).
        "future date": df["date"] > pd.Timestamp.today().normalize(),
    }
    # A row missing any of its numbers is discarded, whatever the column: so the rule does not
    # depend on which value is missing in this file, and everything left is complete to compute.
    # The reason names the column, and also covers a value that was not a number ('n/a').
    for col in NUMERIC_COLS:
        rules[f"missing {col}"] = df[col].isna()
    rules["negative value"] = (df[NUMERIC_COLS] < 0).any(axis=1)
    rules["more clicks than impressions"] = df["clicks"] > df["impressions"]
    return pd.DataFrame(rules).fillna(False)


def duplicate_reasons(df: pd.DataFrame) -> pd.Series:
    """Finds the extra copies of identical rows.

    Args:
        df: Normalized rows.

    Returns:
        For each extra copy, the reason naming the line of the row that is kept; NaN for rows that
        are not copies.
    """
    group = df.groupby(list(df.columns), dropna=False, sort=False).ngroup()
    first_line = df.index.to_series().groupby(group).transform("min")
    copies = df.duplicated()
    return ("exact duplicate of line " + first_line.astype(str)).where(copies)


def correct_negative_spend(df: pd.DataFrame) -> pd.Series:
    """Makes negative spend positive, in place, and records each correction.

    Assumption: spend cannot be negative, so the sign is a data-entry error and the amount is
    right. It runs before looking for duplicates, so two copies of the same row are still equal.

    Args:
        df: Normalized rows; modified in place.

    Returns:
        The correction made, indexed by line.
    """
    negative = df["spend"].lt(0).fillna(False)
    corrections = "spend " + df.loc[negative, "spend"].astype(str) + " made positive"
    df.loc[negative, "spend"] = df.loc[negative, "spend"].abs()
    return corrections


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Normalizes the rows, corrects negative spend and discards duplicates and invalid rows.

    Args:
        raw: The file as returned by load_raw.

    Returns:
        A tuple with the clean rows, the discarded rows as they came with their `reason`, the
        corrected rows as they came with their `correction`, and a report of counts per step.
    """
    df = normalize(raw)
    report = {"rows read": len(df)}
    corrections = correct_negative_spend(df)

    # Rows are compared once normalized: so a duplicate that only differs in the date format or in
    # spaces is detected too.
    duplicate = duplicate_reasons(df)
    report["exact duplicates"] = int(duplicate.notna().sum())
    df = df[duplicate.isna()]

    reasons = invalid_reasons(df)
    for reason, hits in reasons.items():
        report[f"invalid: {reason}"] = int(hits.sum())
    invalid = reasons.apply(lambda flags: "; ".join(flags.index[flags]), axis=1)
    # A row can break several rules: this is the real total, not the sum of the ones above.
    report["invalid rows discarded"] = int((invalid != "").sum())
    df = df[invalid == ""]

    report["valid rows"] = len(df)

    reason = pd.concat([duplicate.dropna(), invalid[invalid != ""]])
    rejected = raw.loc[reason.index].assign(reason=reason).sort_index()
    rejected = rejected.rename_axis("source_line").reset_index()

    # Only the corrected rows that were kept: one corrected and then discarded is in rejected.
    kept = corrections[corrections.index.isin(df.index)]
    report["negative spend made positive"] = len(kept)
    corrected = raw.loc[kept.index].assign(correction=kept).sort_index()
    corrected = corrected.rename_axis("source_line").reset_index()
    return df, rejected, corrected, report


def campaign_attributes(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Picks a single name, channel, country and objective per campaign: the most frequent one.

    If a campaign comes with more than one value, a warning lists all of them. On a tie the first
    in alphabetical order wins, so the result does not depend on the order of the rows.

    Args:
        df: Clean rows.

    Returns:
        The attributes indexed by campaign_id, and how many campaigns had more than one value.
    """
    attrs = df.groupby("campaign_id")[CAMPAIGN_ATTRS].agg(lambda values: values.mode().iloc[0])
    variants = df.groupby("campaign_id")[CAMPAIGN_ATTRS].nunique()
    inconsistent = variants[variants.gt(1).any(axis=1)]
    for campaign_id, counts in inconsistent.iterrows():
        rows = df[df["campaign_id"] == campaign_id]
        for col in counts.index[counts.gt(1)]:
            log.warning(
                "%s has more than one %s: %s. Using '%s'",
                campaign_id,
                col,
                sorted(rows[col].unique()),
                attrs.loc[campaign_id, col],
            )
    return attrs, len(inconsistent)


def merge_same_day(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Builds one row per campaign, day and currency, adding up the rows that share the key.

    Rows arrive complete (clean discards those with a missing number). skipna=False is a safety
    net: if a blank ever arrived, the total is left blank instead of adding up only one part.

    Args:
        df: Clean rows.

    Returns:
        The merged rows with the campaign attributes, and a report of counts.
    """
    attrs, inconsistent = campaign_attributes(df)
    grouped = df.groupby(KEY_COLS, dropna=False)
    merged = grouped[NUMERIC_COLS].sum(skipna=False)
    merged[MONEY_COLS] = merged[MONEY_COLS].round(2)  # 486.29999999999995 -> 486.3, summing noise
    merged = merged.reset_index().join(attrs, on="campaign_id")
    merged = merged[OUTPUT_ID_COLS + NUMERIC_COLS]

    report = {
        "campaigns with inconsistent attributes": inconsistent,
        "campaign-day rows": len(merged),
        "of which merged from several rows": int((grouped.size() > 1).sum()),
    }
    return merged, report


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divides row by row, leaving the result blank when it cannot be computed.

    A 0 is never used in those cases: a CPA of 0 would say the conversions came for free.

    Args:
        numerator: The values on top.
        denominator: The values below.

    Returns:
        The quotient as Float64; blank where the denominator is 0 or either value is missing.
    """
    numerator = numerator.astype("Float64")
    denominator = denominator.astype("Float64")
    denominator = denominator.mask(denominator.eq(0).fillna(False))
    return numerator / denominator


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Adds CTR, CPC, CPA and ROAS. Used the same way per row and on the summary totals.

    Args:
        df: Rows with impressions, clicks, spend, conversions and revenue.

    Returns:
        A copy with the four metric columns added.
    """
    return df.assign(
        ctr=safe_divide(df["clicks"], df["impressions"]),
        cpc=safe_divide(df["spend"], df["clicks"]),
        cpa=safe_divide(df["spend"], df["conversions"]),
        roas=safe_divide(df["revenue"], df["spend"]),
    )


def summarize(daily: pd.DataFrame) -> pd.DataFrame:
    """Builds one row per campaign: totals, and metrics recomputed over those totals.

    Daily metrics are never averaged: the average would give a USD 10 day the same weight as a
    USD 1,000 one. Since no blanks are left, each summary metric can be redone from the columns of
    the same row (cpa = spend / conversions).

    Args:
        daily: The campaign-day rows.

    Returns:
        One row per campaign and currency, with totals and metrics.
    """
    # The attributes are already unique per campaign (merge_same_day): grouping by them splits no
    # row.
    campaign_cols = [col for col in OUTPUT_ID_COLS if col != "date"]
    totals = daily.groupby(campaign_cols, dropna=False)[NUMERIC_COLS].sum().reset_index()
    totals[MONEY_COLS] = totals[MONEY_COLS].round(2)  # the summed amounts, without decimal noise
    return add_metrics(totals)


def quality_gate(report: dict[str, int]) -> list[str]:
    """Decides whether the data can be published.

    Args:
        report: The run report, with at least 'rows read' and 'valid rows'.

    Returns:
        The reasons not to publish; empty when the data can be published.
    """
    read, valid = report["rows read"], report["valid rows"]
    if valid == 0:
        return [f"no valid row left out of {read} read"]
    problems = []
    discarded = (read - valid) / read
    if discarded > MAX_DISCARDED_SHARE:
        problems.append(
            f"{discarded:.0%} of the rows were discarded ({read - valid} of {read}), "
            f"more than the maximum of {MAX_DISCARDED_SHARE:.0%}"
        )
    corrected = report.get("negative spend made positive", 0)
    if corrected / read > MAX_CORRECTED_SHARE:
        problems.append(
            f"negative spend was corrected in {corrected / read:.0%} of the rows "
            f"({corrected} of {read}), more than the maximum of {MAX_CORRECTED_SHARE:.0%}: "
            f"the way the platform exports may have changed"
        )
    return problems


def sheets_client() -> gspread.Client:
    """Authenticates with Google using a service account.

    In GitHub Actions the key arrives as text in GOOGLE_CREDENTIALS (a repo secret); on a computer,
    as the path to a file in GOOGLE_APPLICATION_CREDENTIALS.

    Returns:
        An authorized gspread client.

    Raises:
        SystemExit: If neither variable is set.
    """
    if os.environ.get("GOOGLE_CREDENTIALS"):
        return gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]))
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return gspread.service_account(filename=os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    raise SystemExit(
        "Google credentials are missing: set GOOGLE_CREDENTIALS or "
        "GOOGLE_APPLICATION_CREDENTIALS, or run with --no-publish."
    )


SHEETS_EPOCH = pd.Timestamp("1899-12-30")  # Google Sheets' day 0

# Display format: the value is stored with all its decimals. Amounts go without a symbol: "$" is
# mistaken for pesos, and each row's currency is already in the currency column.
# Every published numeric column has to be here (a test checks it): deleting a tab's content does
# not delete its cells' format, and a column that moves would inherit the previous one's format.
SHEET_FORMATS = {
    "date": ("DATE", "yyyy-mm-dd"),
    "impressions": ("NUMBER", "#,##0"),
    "clicks": ("NUMBER", "#,##0"),
    "conversions": ("NUMBER", "#,##0"),
    "spend": ("NUMBER", "#,##0.00"),
    "revenue": ("NUMBER", "#,##0.00"),
    "ctr": ("NUMBER", "0.00%"),
    "cpc": ("NUMBER", "#,##0.00"),
    "cpa": ("NUMBER", "#,##0.00"),
    "roas": ("NUMBER", "0.00"),
    "source_line": ("NUMBER", "0"),
}


def to_sheet_values(df: pd.DataFrame) -> list[list[object]]:
    """Converts a table into the values to write as they are, without Sheets interpreting anything.

    Dates go as the day number Sheets uses, so they are real dates (they sort and filter as dates)
    regardless of the spreadsheet's locale. Blanks go as an empty cell.

    Args:
        df: The table to publish.

    Returns:
        The header followed by one list per row.
    """
    out = df.copy()
    for col in out.select_dtypes("datetime").columns:
        out[col] = (out[col] - SHEETS_EPOCH).dt.days
    out = out.astype(object).where(out.notna(), "")
    return [list(out.columns)] + out.values.tolist()


def column_letter(df: pd.DataFrame, col: str) -> str:
    """Returns the Sheets column letter of a column of the table ('A', 'B'...).

    Args:
        df: The table as it will be written from A1.
        col: The column name.

    Returns:
        The column letter.
    """
    return gspread.utils.rowcol_to_a1(1, df.columns.get_loc(col) + 1).rstrip("1")


def write_tab(book: gspread.Spreadsheet, title: str, df: pd.DataFrame) -> None:
    """Replaces the content of a tab: every run deletes the previous one and writes everything.

    Args:
        book: The spreadsheet.
        title: The tab name; it is created if it does not exist.
        df: The table to write.
    """
    try:
        sheet = book.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = book.add_worksheet(title, rows=len(df) + 1, cols=len(df.columns))
    sheet.clear()
    sheet.resize(rows=len(df) + 1, cols=len(df.columns))  # no rows left over from earlier runs
    # RAW: each value is written as it is. With USER_ENTERED, Sheets interprets text as if someone
    # typed it: a name starting with "=" would run as a formula.
    sheet.update(to_sheet_values(df), "A1", value_input_option="RAW")

    last = len(df) + 1
    sheet.batch_format(
        [{"range": "1:1", "format": {"textFormat": {"bold": True}}}]
        + [
            {
                "range": f"{column_letter(df, col)}2:{column_letter(df, col)}{last}",
                "format": {"numberFormat": {"type": kind, "pattern": pattern}},
            }
            for col, (kind, pattern) in SHEET_FORMATS.items()
            if col in df.columns
        ]
    )
    sheet.freeze(rows=1)
    log.info("Tab '%s' replaced: %d rows", title, len(df))


def publish(daily: pd.DataFrame, summary: pd.DataFrame) -> str:
    """Publishes the clean data and the summary to the results Sheet.

    Args:
        daily: The campaign-day rows, for the clean_data tab.
        summary: The campaign summary, for the campaign_summary tab.

    Returns:
        The Sheet's URL.

    Raises:
        SystemExit: If SPREADSHEET_ID or the credentials are missing.
    """
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise SystemExit("SPREADSHEET_ID is missing: the ID of the Google Sheet to publish to.")
    book = sheets_client().open_by_key(spreadsheet_id)
    write_tab(book, DAILY_TAB, daily)
    write_tab(book, SUMMARY_TAB, summary)
    log.info("Published to %s", book.url)
    return book.url


def publish_review(rejected: pd.DataFrame, corrected: pd.DataFrame) -> str | None:
    """Publishes what the cleaning discarded or corrected to a separate Sheet, for later review.

    It is optional: without REVIEW_SPREADSHEET_ID the pipeline works the same and the review stays
    in output/.

    Args:
        rejected: The discarded rows with their reason.
        corrected: The corrected rows with their correction.

    Returns:
        The review Sheet's URL, or None when REVIEW_SPREADSHEET_ID is not set.
    """
    spreadsheet_id = os.environ.get("REVIEW_SPREADSHEET_ID")
    if not spreadsheet_id:
        log.info("No REVIEW_SPREADSHEET_ID: the review stays only in output/")
        return None
    book = sheets_client().open_by_key(spreadsheet_id)
    write_tab(book, REJECTED_TAB, rejected)
    write_tab(book, CORRECTED_TAB, corrected)
    log.info("Review published to %s", book.url)
    return book.url


class GitHubAnnotations(logging.Handler):
    """Logging handler that turns warnings and errors into GitHub Actions annotations.

    They show up on the run's page: an unknown channel or a rejected file is visible without
    opening the log.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Prints the record as a workflow command (::warning:: or ::error::).

        Args:
            record: The log record.
        """
        kind = "error" if record.levelno >= logging.ERROR else "warning"
        print(f"::{kind}::{record.getMessage()}", flush=True)


def write_step_summary(report: dict[str, int], outcome: str) -> None:
    """Writes the run report as a table on the GitHub Actions run page.

    Does nothing outside GitHub Actions (when GITHUB_STEP_SUMMARY is not set).

    Args:
        report: Count per step; may be empty.
        outcome: One line saying whether the data was published and why.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Campaign pipeline", "", outcome]
    if report:
        lines += ["", "| Step | Rows |", "|---|---:|"]
        lines += [f"| {step} | {count} |" for step, count in report.items()]
    with open(path, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def main() -> None:
    """Runs the pipeline from the command line.

    Raises:
        SystemExit: With code 1 if the file has the wrong shape or fails the quality gate.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-publish", action="store_true", help="only write the local CSVs in output/"
    )
    parser.add_argument(
        "--input", type=Path, default=RAW_CSV, help="CSV to process (default data/campaigns.csv)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        log.addHandler(GitHubAnnotations(level=logging.WARNING))
    try:
        raw = load_raw(args.input)
    except SystemExit as bad_file:  # the file does not have the expected shape
        log.error("Not published: %s", bad_file)
        write_step_summary({}, f"❌ **Not published:** {bad_file}")
        raise SystemExit(1)
    clean_df, rejected, corrected, report = clean(raw)
    daily, merge_report = merge_same_day(clean_df)
    report.update(merge_report)
    daily = add_metrics(daily)
    for metric in METRIC_COLS:
        report[f"missing {metric}"] = int(daily[metric].isna().sum())
    for step, count in report.items():
        log.info("%-48s %d", step, count)
    summary = summarize(daily)

    REJECTED_CSV.parent.mkdir(exist_ok=True)
    outputs = {
        DAILY_CSV: daily,
        SUMMARY_CSV: summary,
        REJECTED_CSV: rejected,
        CORRECTED_CSV: corrected,
    }
    for path, table in outputs.items():
        table.to_csv(path, index=False, encoding="utf-8-sig")  # with BOM: Excel reads accents fine
        log.info("Wrote %s", path.relative_to(ROOT))

    # The review is published before the gate: if the file is broken, that is exactly what to see.
    if not args.no_publish:
        publish_review(rejected, corrected)

    # The gate runs after writing the CSVs: if it stops, they are still there to see what happened.
    problems = quality_gate(report)
    if problems:
        for problem in problems:
            log.error("Not published: %s", problem)
        log.error("The Sheet keeps the data of the previous run. Review the discarded rows.")
        write_step_summary(report, "❌ **Not published:** " + "; ".join(problems) + ".")
        raise SystemExit(1)

    if args.no_publish:
        write_step_summary(report, "Run without publishing (`--no-publish`).")
    else:
        url = publish(daily, summary)
        write_step_summary(report, f"✅ Published to [Google Sheets]({url}).")


if __name__ == "__main__":
    main()
