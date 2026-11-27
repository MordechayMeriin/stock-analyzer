"""The server's report models accept the web contract's fixtures (company-report spec)."""

from __future__ import annotations

import json
from pathlib import Path

from stock_analyzer.report.models import AXES, MAX_AXIS_LABEL, AxisDetail, CompanyReport

FIXTURES = Path(__file__).resolve().parents[3] / "web" / "src" / "features" / "report" / "fixtures"


def test_full_fixture_validates():
    data = json.loads((FIXTURES / "mltm.full.json").read_text(encoding="utf-8"))
    report = CompanyReport.model_validate(data)
    assert report.company.ticker == "MLTM"
    assert report.years == [2023, 2024, 2025]


def test_sparse_fixture_validates():
    data = json.loads((FIXTURES / "mltm.sparse.json").read_text(encoding="utf-8"))
    CompanyReport.model_validate(data)


def test_axis_details_fixture_validates():
    data = json.loads((FIXTURES / "mltm.axis-details.json").read_text(encoding="utf-8"))
    details = data if isinstance(data, list) else list(data.values())
    for d in details:
        AxisDetail.model_validate(d)


def test_axis_labels_fit():
    assert [a for a, _ in AXES] == ["stability", "safety", "revenue_quality", "growth", "profitability"]
    assert all(len(label) <= MAX_AXIS_LABEL for _, label in AXES)
