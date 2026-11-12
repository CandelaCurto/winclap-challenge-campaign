"""clean: corrections, duplicates and invalid rows, each with its reason."""

from pathlib import Path

import pandas as pd
import pytest

import pipeline as p
from helpers import row, run_clean, write_csv


def test_duplicate_is_detected_even_with_a_different_date_format(tmp_path: Path) -> None:
    valid, rejected, report = run_clean(tmp_path, row(date="2026-09-04"), row(date="04/09/2026"))
    assert len(valid) == 1
    assert report["exact duplicates"] == 1
    assert rejected.loc[0, "reason"] == "exact duplicate of line 2"
    assert rejected.loc[0, "source_line"] == 3


def test_duplicate_is_detected_even_with_extra_spaces(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(
        tmp_path, row(), row(name="  AR_CONV_Meta_Q4 ", channel=" Meta Ads", date=" 2026-09-04")
    )
    assert len(valid) == 1
    assert rejected["reason"].tolist() == ["exact duplicate of line 2"]


def test_three_copies_keep_the_first_and_point_to_it(tmp_path: Path) -> None:
    valid, rejected, report = run_clean(tmp_path, row(), row(), row())
    assert valid.index.tolist() == [2]
    assert report["exact duplicates"] == 2
    assert rejected["source_line"].tolist() == [3, 4]
    assert set(rejected["reason"]) == {"exact duplicate of line 2"}


def test_duplicated_invalid_row_appears_once_per_line_with_every_reason(tmp_path: Path) -> None:
    bad = row(clicks="2000", conversions="")
    valid, rejected, report = run_clean(tmp_path, row(date="2026-09-05"), bad, bad)
    assert len(valid) == 1
    assert rejected["source_line"].tolist() == [3, 4]  # each line once, never twice
    assert rejected["reason"].tolist() == [
        "missing conversions; more clicks than impressions",
        "exact duplicate of line 3",
    ]
    assert (report["exact duplicates"], report["invalid rows discarded"]) == (1, 1)


def test_impossible_rows_are_rejected_with_every_reason(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(
        tmp_path,
        row(),
        row(date="2026-09-05", conversions="-1"),
        row(date="2026-09-06", clicks="2000"),
        row(date="2026-09-07", impressions="-5"),  # negative and, therefore, fewer than the clicks
    )
    assert len(valid) == 1
    assert rejected["reason"].tolist() == [
        "negative value",
        "more clicks than impressions",
        "negative value; more clicks than impressions",
    ]
    assert rejected.loc[0, "conversions"] == "-1"  # the rejected row is kept as it came


def test_as_many_clicks_as_impressions_is_valid(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(tmp_path, row(impressions="100", clicks="100"))
    assert len(valid) == 1 and rejected.empty


@pytest.mark.parametrize("column", p.NUMERIC_COLS)
def test_row_missing_any_number_is_rejected_naming_the_column(tmp_path: Path, column: str) -> None:
    valid, rejected, report = run_clean(tmp_path, row(), row(date="2026-09-05", **{column: ""}))
    assert len(valid) == 1
    assert rejected["reason"].tolist() == [f"missing {column}"]
    assert report[f"invalid: missing {column}"] == 1


def test_every_missing_column_is_named_and_the_raw_value_is_kept(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(
        tmp_path,
        row(),
        row(date="2026-09-05", conversions="", revenue=""),
        row(date="2026-09-06", spend="n/a"),
    )
    assert len(valid) == 1
    assert rejected["reason"].tolist() == ["missing conversions; missing revenue", "missing spend"]
    assert rejected.loc[1, "spend"] == "n/a"  # shows what came instead of the number


def test_fractional_count_is_not_rounded_and_the_row_is_rejected(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(tmp_path, row(conversions='"2,5"'))  # quoted: comma is decimal
    assert valid.empty and rejected.loc[0, "reason"] == "missing conversions"


def test_unreadable_date_is_rejected(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(tmp_path, row(), row(date="09/17/2026"))
    assert len(valid) == 1 and rejected.loc[0, "reason"] == "unreadable date"


def test_today_is_valid_and_tomorrow_is_future(tmp_path: Path) -> None:
    today = pd.Timestamp.today().normalize()
    tomorrow = today + pd.Timedelta(days=1)
    valid, rejected, _ = run_clean(
        tmp_path, row(date=f"{today:%Y-%m-%d}"), row(date=f"{tomorrow:%d/%m/%Y}")
    )
    assert valid["date"].tolist() == [today]
    assert rejected["reason"].tolist() == ["future date"]


def test_typo_year_is_a_future_date(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(tmp_path, row(), row(date="2062-09-17"))
    assert len(valid) == 1 and rejected.loc[0, "reason"] == "future date"


def test_negative_spend_is_made_positive_and_recorded(tmp_path: Path) -> None:
    rows = [
        row(spend="-328.33"),
        row(spend="-328.33"),
        row(date="2026-09-05", spend="-50", clicks="2000"),
    ]
    valid, rejected, corrected, report = p.clean(p.load_raw(write_csv(tmp_path, *rows)))

    assert valid["spend"].tolist() == [328.33]  # the corrected copy is detected as a duplicate
    assert corrected["source_line"].tolist() == [2]
    assert corrected.loc[0, "spend"] == "-328.33"  # kept as it came
    assert corrected.loc[0, "correction"] == "spend -328.33 made positive"
    assert report["negative spend made positive"] == 1
    # The one that also has more clicks than impressions is discarded: in rejected, not corrected.
    assert rejected["source_line"].tolist() == [3, 4]


def test_accounting_negative_spend_is_corrected_too(tmp_path: Path) -> None:
    valid, rejected, _ = run_clean(tmp_path, row(spend='"(182.41)"'))
    assert rejected.empty and valid["spend"].iloc[0] == 182.41
