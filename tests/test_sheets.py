"""Publishing: values written literally, real dates, and an explicit format per column."""

import pandas as pd

import pipeline as p
from helpers import CaseRun


def test_sheet_values_are_literal_with_real_dates_and_blanks() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-17"]),
            "campaign_name": ['=HYPERLINK("http://x")'],
            "conversions": pd.array([None], dtype="Int64"),
            "cpa": pd.array([None], dtype="Float64"),
        }
    )
    header, *values = p.to_sheet_values(df)
    assert header == ["date", "campaign_name", "conversions", "cpa"]
    assert values[0][0] == 46282  # 2026-09-17 as a Sheets day number
    assert values[0][1] == '=HYPERLINK("http://x")'  # text: with RAW it does not run
    assert values[0][2:] == ["", ""]


def test_every_published_numeric_column_has_an_explicit_format(case_run: CaseRun) -> None:
    """Without its own format, a column would inherit the one that held its place before."""
    tables = {
        "daily": case_run.daily,
        "summary": case_run.summary,
        "rejected": case_run.rejected,
        "corrected": case_run.corrected,
    }
    for name, table in tables.items():
        numeric = table.select_dtypes(include=["number", "datetime"]).columns
        assert set(numeric) <= set(p.SHEET_FORMATS), (name, set(numeric) - set(p.SHEET_FORMATS))


def test_column_letter() -> None:
    df = pd.DataFrame(columns=[f"c{i}" for i in range(28)])
    assert [p.column_letter(df, col) for col in ["c0", "c25", "c26", "c27"]] == [
        "A",
        "Z",
        "AA",
        "AB",
    ]


class FakeSheet:
    """A fake tab that records what the pipeline asks of it, without talking to Google."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def __getattr__(self, method: str) -> object:
        return lambda *args, **kwargs: self.calls.append((method, args, kwargs))


def test_write_tab_clears_then_writes_literal_values() -> None:
    sheet = FakeSheet()
    book = type("Book", (), {"worksheet": lambda self, title: sheet})()
    df = pd.DataFrame({"date": pd.to_datetime(["2026-09-17"]), "spend": [10.5]})
    p.write_tab(book, "clean_data", df)

    methods = [method for method, _, _ in sheet.calls]
    assert methods.index("clear") < methods.index("update")  # replaces, does not append below
    _, args, kwargs = sheet.calls[methods.index("update")]
    assert kwargs["value_input_option"] == "RAW"
    assert args[0] == [["date", "spend"], [46282, 10.5]]
