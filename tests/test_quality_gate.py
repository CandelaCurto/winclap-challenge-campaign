"""quality_gate: a broken file is never published."""

from pathlib import Path

import pytest

import pipeline as p
from helpers import row, write_csv


@pytest.mark.parametrize(
    "read, valid, publishes",
    [
        (214, 198, True),
        (10, 8, True),  # exactly 20% discarded: the limit itself still publishes
        (214, 172, True),
        (214, 171, False),
        (1000, 799, False),  # just above 20%
        (214, 0, False),
    ],
)
def test_gate_on_discarded_rows(read: int, valid: int, publishes: bool) -> None:
    assert (p.quality_gate({"rows read": read, "valid rows": valid}) == []) is publishes


def test_no_valid_rows_says_so() -> None:
    assert p.quality_gate({"rows read": 5, "valid rows": 0}) == ["no valid row left out of 5 read"]


@pytest.mark.parametrize("corrected, publishes", [(4, True), (200, True), (201, False)])
def test_gate_on_corrected_rows(corrected: int, publishes: bool) -> None:
    report = {"rows read": 1000, "valid rows": 1000, "negative spend made positive": corrected}
    problems = p.quality_gate(report)
    assert (problems == []) is publishes
    if not publishes:
        assert "the way the platform exports may have changed" in problems[0]


def test_broken_file_stops_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_csv(tmp_path, row(clicks="2000"))
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    monkeypatch.setattr(p, "publish", lambda *_: pytest.fail("published a broken file"))
    with pytest.raises(SystemExit) as stopped:
        p.main()
    assert stopped.value.code == 1
