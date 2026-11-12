"""Reading values written as text: numbers, dates and channels."""

import pandas as pd
import pytest

import pipeline as p


def raw_rows(**columns: str | list[str]) -> pd.DataFrame:
    """Builds raw rows (all text) where every column is '1' unless overridden.

    Args:
        **columns: Values for some columns; a list gives one row per item.

    Returns:
        The rows, as load_raw would return them.
    """
    size = max((len(v) for v in columns.values() if isinstance(v, list)), default=1)
    raw = pd.DataFrame([dict.fromkeys(p.RAW_COLS, "1")] * size)
    return raw.assign(**columns)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$ 182,41", 182.41),
        ("182.41", 182.41),
        ("1.234,5", 1234.5),
        ("1,234.50", 1234.5),
        ("114.055", 114055),
        ("1.234", 1234),  # three digits after the only separator: thousands
        ("1,234", 1234),
        ("1.234.567,89", 1234567.89),
        ("USD 2.493,41", 2493.41),
        ("US$ 10", 10),
        ("US$ 10,5", 10.5),
        ("10 USD", 10),
        ("€ 3,5", 3.5),
        ("-1325.39", -1325.39),
        ("(182.41)", -182.41),  # accounting negative
        ("$ (1.234,50)", -1234.5),
        ("0.0", 0),
        ("0,00", 0),
        ("-0", 0),
        ("(0)", 0),
        ("", None),
        ("  ", None),
        ("$", None),  # a symbol with no number
        ("12-3", None),
        ("--5", None),
        ("1e3", None),  # never guessed
        ("n/a", None),
    ],
)
def test_to_number(text: str, expected: float | None) -> None:
    assert p.to_number(text) == expected


@pytest.mark.xfail(
    strict=True,
    reason="Known bug, not fixed yet: thousands groups shorter than 3 digits are accepted, so "
    "'1,2,3' reads as 12.3 instead of being left blank.",
)
@pytest.mark.parametrize("text", ["1,2,3", "1.2.3"])
def test_to_number_rejects_malformed_thousands_groups(text: str) -> None:
    assert p.to_number(text) is None


@pytest.mark.xfail(
    strict=True,
    reason="Known bug, not fixed yet: a minus sign inside accounting parentheses cancels out, so "
    "'(-5)' reads as +5 instead of being left blank.",
)
def test_to_number_rejects_minus_inside_parentheses() -> None:
    assert p.to_number("(-5)") is None


def test_parse_numbers_blanks_what_is_not_a_number() -> None:
    parsed = p.parse_numbers(pd.Series(["10", "n/a", ""], name="spend"))
    assert parsed.iloc[0] == 10 and parsed.iloc[1:].isna().all()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-09-17", "2026-09-17"),
        ("17/09/2026", "2026-09-17"),
        ("29/02/2028", "2028-02-29"),  # leap year
        ("29/02/2027", None),  # not a leap year
        ("2027-02-29", None),
        ("31/04/2026", None),  # April has 30 days
        ("09/17/2026", None),  # MM/DD is not accepted, even when it is unambiguous
        ("2026/09/17", None),
        ("", None),
    ],
)
def test_parse_dates(text: str, expected: str | None) -> None:
    parsed = p.parse_dates(pd.Series([text])).iloc[0]
    if expected is None:
        assert pd.isna(parsed)
    else:
        assert parsed == pd.Timestamp(expected)


def test_spaces_around_a_date_are_trimmed_before_parsing() -> None:
    raw = raw_rows(date="  17/09/2026 ", channel="Meta Ads", campaign_name="AR_CONV_Meta_Q4")
    assert p.normalize(raw).loc[0, "date"] == pd.Timestamp("2026-09-17")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Google Ads", "Google Ads"),
        ("GOOGLE ADS", "Google Ads"),
        ("gOoGlE aDs", "Google Ads"),
        ("Google Ads Search", "Google Ads"),
        ("YouTube", "Google Ads"),
        ("meta", "Meta Ads"),
        ("Facebook Ads", "Meta Ads"),
        ("Instagram Ads", "Meta Ads"),
        ("Linkedin", "LinkedIn Ads"),
        ("TikTok Ads", None),
        ("", None),
    ],
)
def test_classify_channel(text: str, expected: str | None) -> None:
    assert p.classify_channel(text) == expected


@pytest.mark.parametrize(
    "name, expected",
    [("AR_CONV_Meta_Q4", "Meta Ads"), ("CO_AWAR_Google_Q4", "Google Ads"), ("Promo", None)],
)
def test_name_platform(name: str, expected: str | None) -> None:
    assert p.name_platform(name) == expected


def test_unknown_and_blank_channels_are_kept_as_they_come(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = raw_rows(date="2026-09-17", campaign_name="Promo", channel=["  TikTok Ads ", "", "META"])
    assert p.normalize(raw)["channel"].tolist() == ["TikTok Ads", "", "Meta Ads"]
    assert "Unrecognized channels" in caplog.text


def test_channel_that_contradicts_the_campaign_name_is_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = raw_rows(date="2026-09-17", campaign_name="AR_CONV_Meta_Q4", channel="Google Ads")
    p.normalize(raw)
    assert "Channel differs from the one in the campaign name on lines [0]" in caplog.text


def test_count_with_decimals_is_left_blank_not_rounded() -> None:
    raw = raw_rows(date="2026-09-17", campaign_name="Promo", channel="Meta Ads", clicks="2,5")
    assert pd.isna(p.normalize(raw).loc[0, "clicks"])
