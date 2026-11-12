"""Builders shared by the tests: a CSV header, one data row, and cleaning a few rows."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import pipeline as p

HEADER = ",".join(p.RAW_COLS)
# A fixed copy of the CSV Winclap delivered, not data/campaigns.csv: that file is replaced every
# week and its numbers change. The tests check the rules; the quality gate checks each file.
CASE_CSV = Path(__file__).parent / "fixtures" / "campaigns_case.csv"


def row(
    date: str = "2026-09-04",
    campaign: str = "C1004",
    name: str = "AR_CONV_Meta_Q4",
    channel: str = "Meta Ads",
    impressions: str = "1000",
    clicks: str = "100",
    spend: str = "50",
    conversions: str = "5",
    revenue: str = "200",
    currency: str = "USD",
) -> str:
    """Returns one CSV data row; every value can be overridden.

    Args:
        date: The date as written in the file.
        campaign: The campaign_id.
        name: The campaign_name.
        channel: The channel as written in the file.
        impressions: Impressions as written in the file.
        clicks: Clicks as written in the file.
        spend: Spend as written in the file.
        conversions: Conversions as written in the file.
        revenue: Revenue as written in the file.
        currency: The currency code.

    Returns:
        The row as a comma-separated line, in RAW_COLS order.
    """
    return (
        f"{date},{campaign},{name},{channel},AR,Conversion,"
        f"{impressions},{clicks},{spend},{conversions},{revenue},{currency}"
    )


def write_csv(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    """Writes a CSV with the given header and rows.

    Args:
        tmp_path: The folder to write in.
        *rows: The data rows.
        header: The header line.

    Returns:
        The path of the file.
    """
    path = tmp_path / "campaigns.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def run_clean(tmp_path: Path, *rows: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Loads and cleans a CSV made of the given rows.

    Args:
        tmp_path: The folder to write the CSV in.
        *rows: The data rows.

    Returns:
        The clean rows, the rejected rows and the report.
    """
    result = p.clean(p.load_raw(write_csv(tmp_path, *rows)))
    return result.valid, result.rejected, result.report


@dataclass(frozen=True)
class CaseRun:
    """Every table the case file produces, step by step."""

    valid: pd.DataFrame
    rejected: pd.DataFrame
    corrected: pd.DataFrame
    report: dict[str, int]
    excluded: pd.DataFrame
    daily: pd.DataFrame
    summary: pd.DataFrame
