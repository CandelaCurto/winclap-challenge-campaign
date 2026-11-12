"""The case file from start to finish, and what a run reports in GitHub Actions."""

from pathlib import Path

import pytest

import pipeline as p
from helpers import CASE_CSV, HEADER, CaseRun, row, write_csv


def test_case_file_end_to_end(case_run: CaseRun) -> None:
    report, valid, daily, summary = (
        case_run.report,
        case_run.valid,
        case_run.daily,
        case_run.summary,
    )

    assert (report["rows read"], report["valid rows"], len(case_run.rejected)) == (
        214,
        191,
        23,
    )
    # 6 with more clicks, 7 without conversions, 6 without revenue (overlapping)
    assert report["invalid rows discarded"] == 17
    assert len(case_run.corrected) == 4  # negative spend made positive (a 5th is discarded)
    assert len(daily) == 141 and len(summary) == 12
    assert not daily[p.NUMERIC_COLS].isna().any().any()  # nothing published has a blank number
    assert not daily.duplicated(["date", "campaign_id"]).any()  # primary key
    assert not summary.duplicated("campaign_id").any()
    assert daily["spend"].sum() == pytest.approx(valid["spend"].sum())
    assert summary["spend"].sum() == pytest.approx(daily["spend"].sum())
    assert p.quality_gate(report) == []


def test_run_without_publishing_writes_every_local_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--no-publish", "--input", str(CASE_CSV)])
    p.main()
    written = sorted(path.name for path in (tmp_path / "output").iterdir())
    assert written == sorted(
        path.name for path in [p.DAILY_CSV, p.SUMMARY_CSV, p.REJECTED_CSV, p.CORRECTED_CSV]
    )


def test_step_summary_reports_why_a_broken_file_was_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, row(clicks="2000"))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    try:
        with pytest.raises(SystemExit):
            p.main()
    finally:
        p.log.handlers.clear()

    text = summary.read_text(encoding="utf-8")
    assert "Not published" in text and "| rows read | 1 |" in text
    assert "::error::Not published" in capsys.readouterr().out  # annotation on the run page


def test_step_summary_explains_a_file_with_the_wrong_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_csv(tmp_path, row(), header=HEADER.replace(",spend", ""))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    with pytest.raises(SystemExit) as stopped:
        p.main()
    assert stopped.value.code == 1
    assert "is missing columns: ['spend']" in summary.read_text(encoding="utf-8")
