"""Peer benchmark service and API (peer-benchmark spec)."""

import json

import pytest
import respx
from fastapi.testclient import TestClient

from stock_analyzer.errors import LiveModeRequired, NotCached
from stock_analyzer.services import peer_benchmark as pb
from stock_analyzer.services.context import Ctx
from tests.conftest import FIXTURES, seed_fr_cache, seed_malam

TARGET = 6901
CLASS = "6220"
EU = "GB,FR,DE,NL,ES,IT,IE"


def issuer(company_id, country="IL", code=CLASS):
    return {
        "id": company_id,
        "name": f"Company {company_id}",
        "ticker": f"T{company_id}",
        "country_code": country,
        "listing_status": "LISTED",
        "sub_industry": {"code": code, "name": "Computer facilities management"} if code else None,
    }


def directory(countries):
    return {
        "countries": countries,
        "sub_industry": CLASS,
        "listing_status": "LISTED",
        "view": "full",
        "page_size": 100,
        "page": 1,
    }


def seed_fin(settings, company_id, fixture):
    body = json.loads((FIXTURES / fixture).read_text())
    seed_fr_cache(settings, f"/companies/{company_id}/financials/", {"fiscal_period": "FY"}, body)


def seed_directory(settings, il, us, eu, code=CLASS):
    seed_fr_cache(settings, f"/companies/{TARGET}/", {}, issuer(TARGET, code=code))
    for countries, rows in (("IL", il), ("US", us), (EU, eu)):
        seed_fr_cache(settings, "/companies/", directory(countries), {"results": rows, "next": None})


@pytest.fixture
def plain(settings, tmp_path):
    """A registry where MLTM has no curated peers, so the sub-industry fallback applies."""
    path = tmp_path / "plain.yaml"
    path.write_text(
        "companies:\n  - ticker: MLTM\n    name_he: מלם תים\n    fr_company_id: 6901\n", encoding="utf-8"
    )
    return settings.model_copy(update={"companies_file": path})


@pytest.fixture
def curated(settings, tmp_path):
    """A registry where MLTM has curated peers: one US, one GB (EU cohort), one IL."""
    path = tmp_path / "companies.yaml"
    path.write_text(
        "companies:\n"
        "  - ticker: MLTM\n    name_he: מלם תים\n    name_en: Malam-Team Ltd.\n    fr_company_id: 6901\n"
        "    peers:\n"
        "      - {fr_company_id: 800001, name: US Peer, country: US}\n"
        "      - {fr_company_id: 800002, name: UK Peer, country: GB}\n"
        "      - {fr_company_id: 800003, name: IL Bank, country: IL}\n",
        encoding="utf-8",
    )
    return settings.model_copy(update={"companies_file": path})


def test_curated_peers_grouped_by_market(curated):
    seed_malam(curated)
    seed_fin(curated, 800001, "mltm_financials.json")  # industrial, same values as the target
    seed_fin(curated, 800003, "lumi_financials.json")  # bank template
    out = pb.benchmark(Ctx(curated), "MLTM")
    assert out.match_parameter == "curated" and out.sub_industry is None
    assert [c.market for c in out.cohorts] == ["IL", "US", "EU"]
    il, us, eu = out.cohorts
    assert all(c.source == "curated" for c in out.cohorts)
    assert us.peers[0].status == "ok" and us.peers[0].in_median
    assert eu.peers[0].status == "financials_not_cached" and not eu.peers[0].in_median
    assert il.peers[0].status == "other_template" and il.peers[0].template == "bank"
    gross = out.company.values["gross_margin"]
    assert us.medians["gross_margin"].value == gross and us.medians["gross_margin"].n == 1
    assert eu.medians["gross_margin"] == pb.MedianOut(value=None, n=0)
    assert il.medians["gross_margin"].n == 0
    assert all(r.unit != "amount" for r in out.ratios)


def test_sub_industry_fallback_per_market(plain):
    seed_malam(plain)
    seed_directory(plain, il=[issuer(TARGET), issuer(12), issuer(11)], us=[issuer(30, "US")], eu=[])
    seed_fin(plain, 11, "mltm_financials.json")
    out = pb.benchmark(Ctx(plain), "MLTM")
    assert out.match_parameter == "sub_industry" and out.sub_industry == CLASS
    assert out.sub_industry_label == "Computer facilities management"
    il, us, eu = out.cohorts
    assert [p.id for p in il.peers] == [11, 12] and il.medians["gross_margin"].n == 1
    assert [p.id for p in us.peers] == [30] and us.peers[0].status == "financials_not_cached"
    assert eu.peers == [] and eu.reason == "no_matches"


def test_missing_sub_industry(plain):
    seed_malam(plain)
    seed_directory(plain, [], [], [], code=None)
    out = pb.benchmark(Ctx(plain), "MLTM")
    assert out.reason == "missing_sub_industry" and out.cohorts == []


def test_cached_read_needs_stored_directory(plain):
    seed_malam(plain)
    with pytest.raises(NotCached):
        pb.benchmark(Ctx(plain), "MLTM")


def test_medians_of_odd_and_even_counts():
    rows = [pb.BenchCompanyOut(id=i, name="x", values={"r": v}, in_median=True) for i, v in enumerate("13")]
    rows.append(pb.BenchCompanyOut(id=9, name="y", values={"r": "100"}, in_median=False))
    assert pb.medians(rows, ["r"])["r"] == pb.MedianOut(value="2", n=2)


def test_live_run_estimates_before_fetching(plain):
    seed_malam(plain)
    seed_directory(plain, il=[issuer(12), issuer(11)], us=[issuer(30, "US")], eu=[issuer(40, "GB")])
    seed_fin(plain, 11, "mltm_financials.json")
    ctx = Ctx(plain, mode="live")
    with respx.mock(assert_all_called=False) as router:
        out = pb.live_run(ctx, "MLTM", pb.PeerBenchmarkRunIn())
        assert len(router.calls) == 0
    assert (out.financials_requests, out.metadata_requests, out.estimated_credits) == (3, 0, 120)
    assert out.benchmark is None and out.fetched == []
    capped = pb.live_run(ctx, "MLTM", pb.PeerBenchmarkRunIn(max_fetch=2))
    assert capped.estimated_credits == 80


def test_live_run_confirmed_fetches_up_to_cap(plain):
    seed_malam(plain)
    seed_directory(plain, il=[issuer(12)], us=[issuer(30, "US")], eu=[])
    body = json.loads((FIXTURES / "mltm_financials.json").read_text())
    with respx.mock(assert_all_called=True) as router:
        route = router.get(url__regex=r".*/companies/12/financials/.*").respond(json=body)
        out = pb.live_run(Ctx(plain, mode="live"), "MLTM", pb.PeerBenchmarkRunIn(confirm=True, max_fetch=1))
        assert route.call_count == 1
    assert out.fetched == [12]
    assert out.benchmark.cohorts[0].peers[0].status == "ok"
    assert out.benchmark.cohorts[1].peers[0].status == "financials_not_cached"


def test_live_run_refused_in_cached_mode(settings):
    seed_malam(settings)
    with pytest.raises(LiveModeRequired):
        pb.live_run(Ctx(settings), "MLTM", pb.PeerBenchmarkRunIn())


def test_api_get_and_post(plain):
    from stock_analyzer.api.main import create_app

    seed_malam(plain)
    seed_directory(plain, il=[issuer(11)], us=[], eu=[])
    seed_fin(plain, 11, "mltm_financials.json")
    client = TestClient(create_app(plain))
    data = client.get("/api/companies/MLTM/peer-benchmark").json()
    assert data["match_parameter"] == "sub_industry" and data["cohorts"][0]["peers"][0]["id"] == 11
    refused = client.post("/api/companies/MLTM/peer-benchmark")
    assert refused.status_code == 403 and refused.json()["code"] == "live_required"
    est = client.post("/api/companies/MLTM/peer-benchmark?mode=live", json={}).json()
    assert est["estimated_credits"] == 0 and est["benchmark"] is None
