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


def write_to_fake_sheet(df: pd.DataFrame) -> FakeSheet:
    """Runs write_tab against a FakeSheet.

    Args:
        df: The table to write.

    Returns:
        The fake tab, with the calls it received.
    """
    sheet = FakeSheet()
    book = type("Book", (), {"worksheet": lambda self, title: sheet})()
    p.write_tab(book, "clean_data", df)
    return sheet


def call(sheet: FakeSheet, method: str) -> tuple[tuple[object, ...], dict[str, object]]:
    """Returns the arguments of the first call to a method of the fake tab.

    Args:
        sheet: The fake tab.
        method: The method name.

    Returns:
        The positional and keyword arguments.
    """
    _, args, kwargs = next(c for c in sheet.calls if c[0] == method)
    return args, kwargs


def test_write_tab_never_clears_and_resizes_before_writing_literal_values() -> None:
    df = pd.DataFrame({"date": pd.to_datetime(["2026-09-17", "2026-09-18"]), "spend": [10.5, 3.0]})
    sheet = write_to_fake_sheet(df)

    methods = [method for method, _, _ in sheet.calls]
    assert "clear" not in methods  # the tab is never left empty
    assert methods.index("resize") < methods.index("update")
    assert call(sheet, "resize")[1] == {"rows": 3, "cols": 2}  # exactly the table
    args, kwargs = call(sheet, "update")
    assert kwargs["value_input_option"] == "RAW"
    assert args[0] == [["date", "spend"], [46282, 10.5], [46283, 3.0]]


def test_write_tab_writes_every_cell_so_old_values_do_not_survive() -> None:
    """A cell that is now blank is sent as "" (which clears it), never skipped as None."""
    df = pd.DataFrame({"campaign_id": ["C1", "C2"], "cpa": pd.array([1.5, None], dtype="Float64")})
    values = call(write_to_fake_sheet(df), "update")[0][0]
    assert len(values) == 3 and all(len(line) == 2 for line in values)  # the whole rectangle
    assert values[2] == ["C2", ""]
    assert all(cell is not None for line in values for cell in line)


def test_write_tab_keeps_a_blank_row_when_the_table_is_empty() -> None:
    """Sheets refuses to delete every row but the frozen header."""
    sheet = write_to_fake_sheet(pd.DataFrame({"source_line": pd.Series([], dtype=int)}))
    assert call(sheet, "resize")[1] == {"rows": 2, "cols": 1}
    assert call(sheet, "update")[0][0] == [["source_line"], [""]]
