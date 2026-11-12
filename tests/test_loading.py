"""load_raw: the shape of the file is checked before anything else."""

from pathlib import Path

import pytest

import pipeline as p
from helpers import HEADER, row, write_csv


def test_missing_column_stops_with_a_clear_message(tmp_path: Path) -> None:
    path = write_csv(tmp_path, header=HEADER.replace(",spend", ""))
    with pytest.raises(SystemExit, match=r"is missing columns: \['spend'\]"):
        p.load_raw(path)


@pytest.mark.parametrize(
    "content, message",
    [("", "is empty"), (HEADER + "\n", "has no rows"), (HEADER, "has no rows")],
    ids=["empty file", "only the header", "only the header, no newline"],
)
def test_empty_file_stops_with_a_clear_message(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "campaigns.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        p.load_raw(path)


@pytest.mark.parametrize(
    "header",
    [
        HEADER.replace("spend", " Spend "),
        HEADER.upper(),
        ",".join(f" {col.title()} " for col in p.RAW_COLS),
    ],
    ids=["one column padded", "all upper case", "title case with spaces"],
)
def test_header_case_and_spaces_are_tolerated(tmp_path: Path, header: str) -> None:
    raw = p.load_raw(write_csv(tmp_path, row(), header=header))
    assert list(raw.columns) == p.RAW_COLS


def test_extra_columns_are_ignored(tmp_path: Path) -> None:
    raw = p.load_raw(write_csv(tmp_path, row() + ",hello", header=HEADER + ",notes"))
    assert list(raw.columns) == p.RAW_COLS


def test_columns_in_another_order_are_reordered(tmp_path: Path) -> None:
    reversed_header = ",".join(reversed(p.RAW_COLS))
    reversed_row = ",".join(reversed(row().split(",")))
    raw = p.load_raw(write_csv(tmp_path, reversed_row, header=reversed_header))
    assert list(raw.columns) == p.RAW_COLS
    assert raw.loc[2].tolist() == row().split(",")


def test_utf8_bom_is_not_part_of_the_first_column(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.csv"
    path.write_bytes(("﻿" + HEADER + "\n" + row() + "\n").encode("utf-8"))
    raw = p.load_raw(path)
    assert list(raw.columns) == p.RAW_COLS
    assert raw.loc[2, "date"] == "2026-09-04"


def test_windows_line_endings_are_read(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.csv"
    path.write_bytes(("\r\n".join([HEADER, row(), row(date="2026-09-05")]) + "\r\n").encode())
    raw = p.load_raw(path)
    assert raw["currency"].tolist() == ["USD", "USD"]


def test_excel_export_with_semicolons_and_latin1_is_read(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.csv"
    data_row = row(name="AR_CONV_Ñandú_Meta_Q4", spend="SPEND").replace(",", ";")
    data_row = data_row.replace("SPEND", "182,41")
    path.write_bytes((HEADER.replace(",", ";") + "\n" + data_row + "\n").encode("latin-1"))
    raw = p.load_raw(path)
    assert list(raw.columns) == p.RAW_COLS
    assert raw.loc[2, "campaign_name"] == "AR_CONV_Ñandú_Meta_Q4"
    assert p.to_number(raw.loc[2, "spend"]) == 182.41


def test_index_is_the_line_in_the_file(tmp_path: Path) -> None:
    raw = p.load_raw(write_csv(tmp_path, row(), row(date="2026-09-05")))
    assert raw.index.tolist() == [2, 3]
