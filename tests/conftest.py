"""Fixtures shared by every test. Nothing is published: the tests run without Google."""

from pathlib import Path

import pytest

import pipeline as p
from helpers import CASE_CSV, CaseRun


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sends the local CSVs to a temporary folder and hides the GitHub Actions variables."""
    monkeypatch.setattr(p, "ROOT", tmp_path)
    for name in ["REJECTED_CSV", "CORRECTED_CSV", "DAILY_CSV", "SUMMARY_CSV"]:
        monkeypatch.setattr(p, name, tmp_path / "output" / getattr(p, name).name)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


@pytest.fixture(scope="session")
def case_run() -> CaseRun:
    """Runs the case file through every step once, for the tests that read its results."""
    valid, rejected, corrected, report, excluded = p.clean(p.load_raw(CASE_CSV))
    daily, merge_report = p.merge_same_day(valid)
    daily = p.count_discarded_rows(p.add_metrics(daily), excluded)
    return CaseRun(
        valid=valid,
        rejected=rejected,
        corrected=corrected,
        report={**report, **merge_report},
        excluded=excluded,
        daily=daily,
        summary=p.summarize(daily, excluded),
    )
