"""Tracked companies: the merged registry and adding/removing at runtime (filings-client spec)."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from stock_analyzer.api.errors import STATUS_BY_CODE
from stock_analyzer.companies import TrackedCompany, load_registry
from stock_analyzer.errors import (
    CompanyAlreadyTracked,
    CompanyNotFound,
    CompanyNotRemovable,
    LiveModeDisabled,
    LiveModeRequired,
)
from stock_analyzer.services import companies, filings
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import AddCompanyIn
from stock_analyzer.store import FsStore
from tests.conftest import seed_malam


def _abc(**overrides) -> AddCompanyIn:
    data = {"fr_company_id": 1234, "ticker": "abc", "name_he": "חברה לדוגמה"} | overrides
    return AddCompanyIn(**data)


@pytest.fixture
def live(settings):
    settings = settings.model_copy(update={"allow_live": True})
    ctx = Ctx(settings, mode="live")
    yield ctx
    ctx.close()


@pytest.fixture
def cached(live):
    ctx = Ctx(live.settings)
    yield ctx
    ctx.close()


def test_add_then_list_and_resolve(live, cached):
    out = companies.add(live, _abc(name_en=" Example Ltd. ", isin="il0011234567"))
    assert (out.ticker, out.source, out.name_en, out.isin) == ("ABC", "added", "Example Ltd.", "IL0011234567")
    assert [(c.ticker, c.source) for c in companies.list_tracked(cached)] == [
        ("MLTM", "registry"),
        ("ABC", "added"),
    ]
    # resolvable case-insensitively, in cached mode too, and still there for a fresh context (restart)
    assert companies.get_company(cached, "abc").fr_company_id == 1234
    fresh = Ctx(live.settings)
    assert companies.resolve_company(fresh, "ABC").source == "added"
    fresh.close()


@pytest.mark.parametrize(
    ("company", "existing"),
    [(_abc(ticker="mltm"), "MLTM"), (_abc(fr_company_id=6901), "MLTM"), (_abc(ticker="xyz"), "ABC")],
    ids=["registry_ticker", "registry_provider_id", "added_provider_id"],
)
def test_duplicates_refused(live, company, existing):
    if existing == "ABC":
        companies.add(live, _abc())
    before = companies.list_tracked(live)
    with pytest.raises(CompanyAlreadyTracked, match=f"already tracked as {existing}"):
        companies.add(live, company)
    assert companies.list_tracked(live) == before


@pytest.mark.parametrize("ticker", ["A B/C", "", "ABCDEFGHIJKLMNOP", "אבג"])
def test_invalid_ticker_is_a_validation_error(ticker):
    with pytest.raises(ValidationError):
        _abc(ticker=ticker)


def test_blank_hebrew_name_and_bad_isin_are_validation_errors():
    with pytest.raises(ValidationError):
        _abc(name_he="   ")
    with pytest.raises(ValidationError):
        _abc(isin="IL123")
    assert _abc(name_en="  ", isin="").name_en is None


def test_add_and_remove_need_live_mode(live, cached):
    with pytest.raises(LiveModeRequired, match="live mode"):
        companies.add(cached, _abc())
    companies.add(live, _abc())
    with pytest.raises(LiveModeRequired):
        companies.remove(cached, "ABC")
    assert [c.ticker for c in companies.list_tracked(cached)] == ["MLTM", "ABC"]


def test_cached_only_server_refuses_live_context(settings):
    with pytest.raises(LiveModeDisabled):
        Ctx(settings.model_copy(update={"allow_live": False}), mode="live")


def test_remove_added_keeps_cached_data(live, settings):
    seed_malam(settings)  # FY2025 report cached under ticker MLTM
    companies.add(live, _abc())
    companies.remove(live, "abc")
    assert [c.ticker for c in companies.list_tracked(live)] == ["MLTM"]
    with pytest.raises(CompanyNotFound):
        companies.resolve_company(live, "ABC")
    assert live.store.load_report("MLTM", 2025) is not None


def test_remove_refusals(live):
    with pytest.raises(CompanyNotRemovable, match="MLTM"):
        companies.remove(live, "mltm")
    with pytest.raises(CompanyNotFound):
        companies.remove(live, "NOPE")
    assert [c.ticker for c in companies.list_tracked(live)] == ["MLTM"]


def test_registry_entry_wins_over_colliding_added_row(settings, caplog):
    store = FsStore(settings)
    store.add_tracked(TrackedCompany(ticker="mltm", fr_company_id=1, name_he="כפיל"))
    store.add_tracked(TrackedCompany(ticker="MALAM", fr_company_id=6901, name_he="כפיל"))
    store.add_tracked(TrackedCompany(ticker="ABC", fr_company_id=1234, name_he="חברה לדוגמה"))
    with caplog.at_level(logging.WARNING, logger="stock_analyzer.companies"):
        merged = load_registry(settings.companies_file, store)
    assert [(c.ticker, c.source) for c in merged] == [("MLTM", "registry"), ("ABC", "added")]
    assert "MALAM" in caplog.text
    assert len(store.list_tracked()) == 3  # skipped, not deleted
    store.close()


def test_added_company_works_through_filings(settings, tmp_path):
    """An added company resolves like a YAML one: Malam's cached filings, under another ticker."""
    empty = tmp_path / "companies.yaml"
    empty.write_text("companies: []\n", encoding="utf-8")
    settings = settings.model_copy(update={"allow_live": True, "companies_file": empty})
    seed_malam(settings)
    live = Ctx(settings, mode="live")
    companies.add(live, _abc(ticker="malam", fr_company_id=6901))
    live.close()
    ctx = Ctx(settings)
    out = filings.list_filings(ctx, "malam")
    assert [y.fiscal_year for y in out.years] == [2025, 2024, 2023]
    assert out.years[0].selected_filing_id == 32935334
    ctx.close()


@pytest.mark.parametrize(
    ("error", "status"),
    [(LiveModeRequired, 403), (CompanyAlreadyTracked, 409), (CompanyNotRemovable, 409)],
)
def test_new_error_codes_map_to_statuses(error, status):
    assert STATUS_BY_CODE[error.code] == status
