import json

import pytest

from stock_analyzer.companies import load_companies, resolve_ticker
from stock_analyzer.errors import CompanyNotFound, ReportSelectionError
from stock_analyzer.ingest.fr_client import Filing
from stock_analyzer.ingest.select import filing_fiscal_year, select_report, selected_by_year


@pytest.fixture
def filings(fixtures_dir):
    data = json.loads((fixtures_dir / "malam_filings.json").read_text())
    return [Filing.model_validate(r) for r in data["results"]]


def test_malam_fy2025(filings):
    assert select_report(filings, 2025, ticker="MLTM").id == 32935334  # not the HTM cover 32935333


def test_malam_fy2024_with_ixbrl_wrapper(filings):
    chosen = select_report(filings, 2024, ticker="MLTM")
    assert chosen.id == 63741657  # not 63728804 (HTM) or the iXBRL wrapper 63741654


def test_no_candidate_fails_loudly(filings):
    only_htm = [f for f in filings if f.fiscal_year == 2024 and f.file_extension != "PDF"]
    with pytest.raises(ReportSelectionError, match=r"MLTM FY2024"):
        select_report(only_htm, 2024, ticker="MLTM")
    with pytest.raises(ReportSelectionError, match="MLTM FY2019"):
        select_report(filings, 2019, ticker="MLTM")


def test_year_from_title_when_field_missing():
    f = Filing(id=1, title="דוח תקופתי ושנתי לשנת 2022", fiscal_year=None, file_extension="PDF", file_size=10)
    assert filing_fiscal_year(f) == 2022
    assert select_report([f], 2022).id == 1


def test_ixbrl_pdf_excluded_and_largest_wins():
    fs = [
        Filing(
            id=1,
            title="Periodic report 2025 iXBRL",
            fiscal_year=2025,
            file_extension="PDF",
            file_size=999_999,
        ),
        Filing(id=2, title="Periodic report 2025", fiscal_year=2025, file_extension="pdf", file_size=100),
        Filing(id=3, title="Periodic report 2025", fiscal_year=2025, file_extension="PDF", file_size=200),
    ]
    assert select_report(fs, 2025).id == 3


def test_selected_by_year(filings):
    assert {y: f.id for y, f in selected_by_year(filings).items()} == {
        2025: 32935334,
        2024: 63741657,
        2023: 63741686,
    }


def test_registry_resolves_mltm(settings):
    c = resolve_ticker(settings.companies_file, "mltm")
    assert (c.fr_company_id, c.name_he, c.isin) == (6901, "מלם תים", "IL0001560189")
    assert [x.ticker for x in load_companies(settings.companies_file)] == ["MLTM"]
    with pytest.raises(CompanyNotFound, match="NOPE"):
        resolve_ticker(settings.companies_file, "NOPE")


def test_trustee_report_is_not_an_annual_report():
    """Delek Group's only PDF for FY2026 is a bond trustee's annual report (Hermetic, series 37)."""
    trustee = Filing(
        id=61844613,
        title="דו\"ח שנתי – נאמנות למחזיקי אגרות החוב (סדרה לז'), הרמטיק",
        fiscal_year=2026,
        file_extension="PDF",
        file_size=132_318,
    )
    with pytest.raises(ReportSelectionError, match=r"DLEKG FY2026.*61844613") as exc:
        select_report([trustee], 2026, ticker="DLEKG")
    assert "periodic report" in exc.value.message
    assert selected_by_year([trustee], ticker="DLEKG") == {}


@pytest.mark.parametrize("title", ["Periodic and annual report for 2025", "דוח תקופתי ושנתי לשנת 2025"])
def test_english_and_hebrew_periodic_titles(title):
    f = Filing(id=7, title=title, fiscal_year=2025, file_extension="PDF", file_size=1)
    assert select_report([f], 2025).id == 7


def test_periodic_report_wins_over_a_larger_other_pdf():
    fs = [
        Filing(
            id=1, title="דוח תקופתי ושנתי לשנת 2025", fiscal_year=2025, file_extension="PDF", file_size=100
        ),
        Filing(id=2, title="מצגת משקיעים 2025", fiscal_year=2025, file_extension="PDF", file_size=10_000),
    ]
    assert select_report(fs, 2025).id == 1
