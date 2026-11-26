"""The story's fact registry, derive and quote_number (company-story spec, design D3-D5)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from stock_analyzer.config import Settings
from stock_analyzer.fin.normalize import as_of, normalize_financials
from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.story.facts import Fact, FactError, FactRegistry, registry_from_values
from tests.conftest import FIXTURES, fixture_text

TOL = Settings().check_tolerances
YEARS = [2023, 2024, 2025]


@pytest.fixture(scope="module")
def values():
    return normalize_financials(json.loads((FIXTURES / "mltm_financials.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def paragraphs():
    parsed = parse_report(
        fixture_text("mltm_2025_style_b.md"),
        ticker="MLTM",
        fiscal_year=2025,
        filing_id=32935334,
        settings=Settings(repeated_line_min_pages=999),
    )
    return {p.pid: p for p in parsed.paragraphs}


@pytest.fixture
def registry(values, paragraphs) -> FactRegistry:
    reg, _ = registry_from_values(values, YEARS, TOL, paragraphs)
    return reg


# ---------------------------------------------------------------- 5.1 registry


def test_registry_holds_the_revenue_change_with_its_inputs(registry):
    chg = registry.get("CHG:revenue:2024-2025")
    assert chg.kind == "CHG" and chg.unit == "percent" and chg.years == [2024, 2025]
    assert chg.inputs == ["FIN:revenue:2024", "FIN:revenue:2025"]
    assert round(chg.decimal * 100, 2) == Decimal("9.43")
    assert registry.get("FIN:revenue:2025").value == "4138004000"
    assert registry.get("FIN:revenue:2025").currency == "ILS"


def test_registry_covers_only_the_story_years(registry):
    assert "FIN:revenue:2023" in registry
    assert "FIN:revenue:2022" not in registry
    assert "CHG:revenue:2023-2024" in registry
    assert "CHG:revenue:2022-2023" not in registry  # 2022 is outside the covered years


def test_ratio_facts_point_to_their_inputs_and_confidence(registry):
    gm = registry.get("RATIO:gross_margin:2025")
    assert gm.inputs == ["FIN:gross_profit:2025", "FIN:revenue:2025"]
    assert gm.confidence == "high" and gm.operation == "רווח גולמי חלקי הכנסות"
    fcf = registry.get("RATIO:free_cash_flow:2025")
    assert fcf.confidence == "low" and "CF1" in fcf.failed_checks and fcf.currency == "ILS"
    assert registry.get("FIN:cash_from_operations:2025").confidence == "low"  # input of failed CF1


def test_registry_respects_as_of(values):
    early = as_of(values, date(2024, 4, 1))  # FY2023 values became available only in June 2024
    reg, _ = registry_from_values(early, YEARS, TOL)
    assert "FIN:revenue:2023" not in reg and "FIN:revenue:2025" not in reg


# ---------------------------------------------------------------- 5.2 derive


def test_derive_share_registers_a_fact(registry):
    a = registry.add(
        Fact(
            fact_id="TXT:1",
            kind="TXT",
            name_he="הכנסות מהמדינה",
            unit="money",
            years=[2025],
            value="1635000000",
            currency="ILS",
        )
    )
    share = registry.derive("share", [a.fact_id, "FIN:revenue:2025"])
    assert share.fact_id.startswith("DER:") and share.unit == "percent" and share.operation == "share"
    assert share.inputs == ["TXT:1", "FIN:revenue:2025"]
    assert round(share.decimal * 100, 1) == Decimal("39.5")
    assert registry.get(share.fact_id) == share


def test_fact_ids_come_from_content_not_order(values, paragraphs):
    """Parallel agents must get the same ids on every run, so cached turns replay (design D8)."""
    first, _ = registry_from_values(values, YEARS, TOL, paragraphs)
    second, _ = registry_from_values(values, YEARS, TOL, paragraphs)
    a1 = first.quote_number("MLTM-2025-p0010-005", "1,635 מיליון", "money")
    second.quote_number("MLTM-2025-p0005-008", "65.46%", "number")  # a different quote first
    a2 = second.quote_number("MLTM-2025-p0010-005", "1,635 מיליון", "money")
    assert a1.fact_id == a2.fact_id
    assert first.quote_number("MLTM-2025-p0010-005", "1,635 מיליון", "money") is a1  # no duplicate fact
    d1 = first.derive("ratio", ["FIN:revenue:2025", "FIN:revenue:2024"])
    d2 = second.derive("ratio", ["FIN:revenue:2025", "FIN:revenue:2024"])
    assert d1.fact_id == d2.fact_id and d1 == d2


def test_derive_zero_divisor_registers_nothing(registry):
    registry.add(Fact(fact_id="TXT:9", kind="TXT", name_he="אפס", unit="money", years=[2025], value="0"))
    before = len(registry)
    with pytest.raises(FactError, match="zero"):
        registry.derive("ratio", ["FIN:revenue:2025", "TXT:9"])
    assert len(registry) == before


def test_derive_errors(registry):
    with pytest.raises(FactError, match="unknown fact id"):
        registry.derive("sum", ["FIN:revenue:2025", "FIN:nope:2025"])
    with pytest.raises(FactError, match="same unit"):
        registry.derive("diff", ["FIN:revenue:2025", "RATIO:gross_margin:2025"])
    with pytest.raises(FactError, match="unknown operation"):
        registry.derive("multiply", ["FIN:revenue:2025", "FIN:revenue:2024"])
    with pytest.raises(FactError, match="exactly 2"):
        registry.derive("ratio", ["FIN:revenue:2025"])


def test_derive_inherits_the_lowest_confidence(registry):
    der = registry.derive("ratio", ["RATIO:free_cash_flow:2025", "FIN:revenue:2025"])
    assert der.confidence == "low" and "CF1" in der.failed_checks and der.unit == "multiple"


def test_derive_pct_change_refuses_a_sign_change(registry):
    registry.add(Fact(fact_id="TXT:5", kind="TXT", name_he="הפסד", unit="money", years=[2024], value="-10"))
    registry.add(Fact(fact_id="TXT:6", kind="TXT", name_he="רווח", unit="money", years=[2025], value="20"))
    with pytest.raises(FactError, match="sign changed"):
        registry.derive("pct_change", ["TXT:5", "TXT:6"])


# ---------------------------------------------------------------- 5.3 quote_number


def test_quote_with_a_scale_word(registry):
    f = registry.quote_number("MLTM-2025-p0010-005", '1,635 מיליון ש"ח', "money")
    assert f.kind == "TXT" and f.value == "1635000000" and f.currency == "ILS"
    assert f.paragraph_id == "MLTM-2025-p0010-005" and f.years == [2025] and f.source_filing_id == 32935334


def test_quote_scale_word_right_after_the_quote(registry):
    assert registry.quote_number("MLTM-2025-p0010-005", "1,589", "money").value == "1589000000"


def test_quote_table_cell_in_thousands(registry):
    f = registry.quote_number("MLTM-2025-p0030-005", "4,138,004", "money")
    assert f.value == "4138004000"  # the table header says באלפי ש"ח


def test_quote_percent(registry):
    f = registry.quote_number("MLTM-2025-p0005-008", "65.46%", "number")
    assert f.unit == "percent" and f.value == "0.6546"


def test_quote_not_in_paragraph_is_refused(registry):
    before = len(registry)
    with pytest.raises(FactError, match="does not appear"):
        registry.quote_number("MLTM-2025-p0010-005", "1,700 מיליון", "money")
    with pytest.raises(FactError, match="unknown paragraph"):
        registry.quote_number("MLTM-2025-p9999-001", "1,635", "money")
    assert len(registry) == before
