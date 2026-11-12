"""merge_same_day: one row per campaign, day and currency, with one set of attributes."""

from pathlib import Path

import pandas as pd

import pipeline as p
from helpers import row, run_clean


def test_rows_of_the_same_campaign_and_day_are_summed(tmp_path: Path) -> None:
    valid, _, _ = run_clean(tmp_path, row(spend="50"), row(spend="30", impressions="500"))
    daily, report = p.merge_same_day(valid)
    assert len(daily) == 1
    assert (daily.loc[0, "spend"], daily.loc[0, "impressions"]) == (80, 1500)
    assert report["of which merged from several rows"] == 1


def test_different_currencies_on_the_same_day_are_never_summed(tmp_path: Path) -> None:
    valid, _, _ = run_clean(tmp_path, row(spend="50"), row(spend="30", currency="CLP"))
    daily, _ = p.merge_same_day(valid)
    assert sorted(zip(daily["currency"], daily["spend"])) == [("CLP", 30), ("USD", 50)]


def test_summed_money_has_no_float_noise(tmp_path: Path) -> None:
    valid, _, _ = run_clean(tmp_path, row(spend="0.1"), row(spend="0.2"))
    daily, _ = p.merge_same_day(valid)
    assert daily.loc[0, "spend"] == 0.3  # without rounding it would be 0.30000000000000004


def test_blank_part_leaves_the_total_blank() -> None:
    """Safety net: clean leaves no blanks, but if one arrived the total would not add a part."""
    part = {
        "date": pd.Timestamp("2026-09-04"),
        "campaign_id": "C1",
        "campaign_name": "N",
        "channel": "Meta Ads",
        "country": "AR",
        "objective": "Conversion",
        "currency": "USD",
        "impressions": 10,
        "clicks": 1,
        "spend": 5.0,
        "revenue": 1.0,
    }
    df = pd.DataFrame([{**part, "conversions": 9}, {**part, "conversions": None}])
    df["conversions"] = df["conversions"].astype("Int64")
    daily, _ = p.merge_same_day(df)
    assert pd.isna(daily.loc[0, "conversions"])


def test_attribute_variants_do_not_split_the_primary_key(tmp_path: Path) -> None:
    valid, _, _ = run_clean(
        tmp_path,
        row(name="AR_CONV_Meta_Q4"),
        row(name="AR_CONV_Meta_Q4", spend="30"),
        row(name="AR_CONV_Meta_Q4_v2", spend="20", channel="meta"),
    )
    daily, report = p.merge_same_day(valid)
    assert len(daily) == 1
    assert daily.loc[0, "campaign_name"] == "AR_CONV_Meta_Q4"  # the most frequent
    assert report["campaigns with inconsistent attributes"] == 1


def test_attribute_tie_is_won_by_the_first_in_alphabetical_order(tmp_path: Path) -> None:
    rows = [
        row(date="2026-09-04", name="AR_CONV_Meta_Q4_b"),
        row(date="2026-09-05", name="AR_CONV_Meta_Q4_a"),
    ]
    valid, _, _ = run_clean(tmp_path, *rows)
    valid_reversed, _, _ = run_clean(tmp_path, *reversed(rows))
    for rows_in_some_order in [valid, valid_reversed]:
        daily, _ = p.merge_same_day(rows_in_some_order)
        assert set(daily["campaign_name"]) == {"AR_CONV_Meta_Q4_a"}
