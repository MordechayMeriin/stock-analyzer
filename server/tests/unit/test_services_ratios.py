"""Ratios service (financial-ratios spec; task 5.1)."""

from datetime import date

from stock_analyzer.services import ratios as ratio_service
from stock_analyzer.services.context import Ctx
from tests.conftest import seed_bank_and_insurer, seed_malam


def by_code(out):
    return {r.code: r for g in out.groups for r in g.ratios}


def test_malam_ratios(settings):
    seed_malam(settings)
    out = ratio_service.ratios(Ctx(settings), "MLTM")
    assert out.template == "industrial" and out.currency == "ILS"
    assert out.years == [2025, 2024, 2023, 2022, 2021]
    assert [g.group for g in out.groups][:3] == ["profitability", "growth", "returns"]
    gross = by_code(out)["gross_margin"]
    assert gross.unit == "percent" and gross.threshold == "0.005"
    assert gross.values["2025"].value == "0.104733" and gross.values["2025"].status == "stable"
    assert set(gross.values) == {"2025", "2024", "2023", "2022", "2021"}
    assert {c.id: c.status for c in out.checks["2025"]}["CF1"] == "failed"


def test_values_are_strings_or_null(settings):
    seed_malam(settings)
    out = ratio_service.ratios(Ctx(settings), "MLTM")
    for r in by_code(out).values():
        for v in r.values.values():
            assert v.value is None or isinstance(v.value, str)
            assert all(isinstance(x, str) for x in v.inputs.values())


def test_leumi_window_drops_the_stray_year(settings):
    seed_bank_and_insurer(settings)
    out = ratio_service.ratios(Ctx(settings), "LUMI")
    assert out.template == "bank" and out.years == [2025, 2024, 2023]
    assert by_code(out)["loans_to_deposits"].values["2024"].value == "0.736727"
    assert by_code(out)["cet1_ratio"].values["2024"].value == "0.1198"


def test_harel_fy2021_averages_with_fy2020(settings):
    seed_bank_and_insurer(settings)
    out = ratio_service.ratios(Ctx(settings), "HARL")
    assert out.years == [2025, 2024, 2023, 2022, 2021]
    roe = by_code(out)["roe"].values["2021"]
    assert roe.avg_used and "opening:common_equity" in roe.inputs
    assert "gross_margin" not in by_code(out)


def test_as_of_date(settings):
    seed_malam(settings)
    out = ratio_service.ratios(Ctx(settings), "MLTM", as_of=date(2026, 3, 1))
    assert out.years[0] == 2024 and "2025" not in by_code(out)["gross_margin"].values
    assert out.as_of == "2026-03-01"
