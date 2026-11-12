"""safe_divide, add_metrics and summarize."""

from pathlib import Path

import pandas as pd
import pytest

import pipeline as p
from helpers import CaseRun, row, run_clean, write_csv


def test_safe_divide_blank_when_denominator_is_zero_or_missing() -> None:
    result = p.safe_divide(pd.Series([10, 0, 10, None]), pd.Series([0, 5, None, 5]))
    assert result.isna().tolist() == [True, False, True, True]
    assert result.iloc[1] == 0  # a 0 on top is a valid result


NAN = None  # a blank metric


@pytest.mark.parametrize(
    "impressions, clicks, spend, conversions, revenue, expected",
    [
        (1000, 100, 50.0, 5, 200.0, (0.1, 0.5, 10.0, 4.0)),
        (1000, 0, 50.0, 0, 0.0, (0.0, NAN, NAN, 0.0)),  # spend but no clicks: no CPC
        (1000, 10, 0.0, 1, 30.0, (0.01, 0.0, 0.0, NAN)),  # revenue with no spend: no ROAS
        (0, 0, 0.0, 0, 0.0, (NAN, NAN, NAN, NAN)),  # everything 0: nothing can be computed
        (100, 100, 10.0, 1, 10.0, (1.0, 0.1, 10.0, 1.0)),  # as many clicks as impressions
    ],
    ids=["normal", "zero clicks", "zero spend", "all zero", "clicks equal impressions"],
)
def test_metrics(
    impressions: int,
    clicks: int,
    spend: float,
    conversions: int,
    revenue: float,
    expected: tuple[float | None, ...],
) -> None:
    df = pd.DataFrame(
        {
            "impressions": [impressions],
            "clicks": [clicks],
            "spend": [spend],
            "conversions": [conversions],
            "revenue": [revenue],
        }
    )
    metrics = p.add_metrics(df).loc[0, p.METRIC_COLS].tolist()
    for value, wanted in zip(metrics, expected):
        if wanted is None:
            assert pd.isna(value)
        else:
            assert value == pytest.approx(wanted)


def test_summary_recalculates_metrics_over_totals(tmp_path: Path) -> None:
    valid, _, _ = run_clean(
        tmp_path,
        row(date="2026-09-04", spend="10", conversions="10"),
        row(date="2026-09-05", spend="1000", conversions="1"),
    )
    daily, _ = p.merge_same_day(valid)
    summary = p.summarize(p.add_metrics(daily), valid.iloc[0:0])
    assert summary.loc[0, "cpa"] == pytest.approx(1010 / 11)  # not the average of 1 and 1000


def test_every_metric_can_be_redone_from_visible_columns(case_run: CaseRun) -> None:
    """An analyst has to be able to redo each metric with the columns of the table."""
    for table in [case_run.daily, case_run.summary]:
        for metric, (top, below) in {
            "ctr": ("clicks", "impressions"),
            "cpc": ("spend", "clicks"),
            "cpa": ("spend", "conversions"),
            "roas": ("revenue", "spend"),
        }.items():
            pd.testing.assert_series_equal(
                table[metric], p.safe_divide(table[top], table[below]), check_names=False
            )


def test_summary_shows_the_spend_of_rows_discarded_by_a_rule(tmp_path: Path) -> None:
    rows = [
        row(spend="100"),
        row(spend="100"),  # a duplicate: losing it loses nothing, so it is not counted
        row(date="2026-09-05", spend="40", conversions=""),
        row(date="2026-09-06", spend="-2.5", clicks="5000"),  # corrected, then discarded
        row(date="2026-09-07", spend="n/a", revenue=""),  # unknown spend adds nothing
        row(campaign="C2", name="AR_CONV_Meta_Q1", spend="7"),
    ]
    result = p.clean(p.load_raw(write_csv(tmp_path, *rows)))
    daily, _ = p.merge_same_day(result.valid)
    summary = p.summarize(p.add_metrics(daily), result.excluded).set_index("campaign_id")
    assert summary.loc["C1004", "spend"] == 100
    assert summary.loc["C1004", "spend_excluded"] == 42.5
    assert summary.loc["C2", "spend_excluded"] == 0


def test_spend_excluded_is_kept_per_currency(tmp_path: Path) -> None:
    rows = [row(), row(currency="CLP"), row(date="2026-09-05", conversions="", currency="CLP")]
    result = p.clean(p.load_raw(write_csv(tmp_path, *rows)))
    daily, _ = p.merge_same_day(result.valid)
    summary = p.summarize(p.add_metrics(daily), result.excluded).set_index("currency")
    assert (summary.loc["USD", "spend_excluded"], summary.loc["CLP", "spend_excluded"]) == (0, 50)
