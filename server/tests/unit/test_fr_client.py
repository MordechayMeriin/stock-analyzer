import json

import httpx
import pytest
import respx

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.errors import NotCached, ProviderError, ProviderNotFound, TruncatedContent
from stock_analyzer.ingest.fr_client import Filing, FRClient, load_report, read_fr_totals, save_report

BASE = "https://api.financialreports.eu"


class Sleeps(list):
    def __call__(self, seconds):
        self.append(seconds)


def log_records(settings):
    return [json.loads(line) for line in (settings.logs_dir / "fr.jsonl").read_text().splitlines()]


@pytest.fixture
def sleeps():
    return Sleeps()


@pytest.fixture
def client(settings, sleeps):
    s = settings.model_copy(update={"fr_backoff_base_s": 1.0, "fr_backoff_max_s": 30.0, "fr_max_attempts": 4})
    with FRClient(s, sleep=sleeps) as c:
        yield c


# ---------------------------------------------------------------- transport behavior


@respx.mock(base_url=BASE)
def test_sends_api_key_and_logs_without_it(respx_mock, client, settings):
    route = respx_mock.get("/usage/").mock(
        return_value=httpx.Response(200, json={"free_credits": {"used": 3}})
    )
    assert client.usage() == {"free_credits": {"used": 3}}
    assert route.calls[0].request.headers["x-api-key"] == "test-fr-key-DO-NOT-LOG"
    (rec,) = log_records(settings)
    assert rec["endpoint"] == "/usage/" and rec["credits"] == 0 and rec["cache"] == "refresh"
    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            assert b"DO-NOT-LOG" not in path.read_bytes(), f"API key leaked into {path}"


@respx.mock(base_url=BASE)
def test_429_honors_retry_after(respx_mock, client, sleeps):
    respx_mock.get("/filings/1/").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "slow down"}),
            httpx.Response(200, json={"id": 1}),
        ]
    )
    assert client.request("/filings/1/").json_body() == {"id": 1}
    assert sleeps == [2.0]  # waited at least Retry-After (base backoff is 1s)


@respx.mock(base_url=BASE)
def test_5xx_exponential_backoff_then_success(respx_mock, client, sleeps):
    respx_mock.get("/filings/2/").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(502),
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert client.request("/filings/2/").json_body() == {"ok": True}
    assert sleeps == [1.0, 2.0, 4.0]


@respx.mock(base_url=BASE)
def test_5xx_gives_up_after_max_attempts(respx_mock, client, sleeps):
    route = respx_mock.get("/filings/3/").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ProviderError, match="after 4 attempts"):
        client.request("/filings/3/")
    assert route.call_count == 4 and len(sleeps) == 3


@respx.mock(base_url=BASE)
def test_transport_errors_are_retried(respx_mock, client, sleeps):
    respx_mock.get("/filings/4/").mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={})])
    client.request("/filings/4/")
    assert sleeps == [1.0]


@respx.mock(base_url=BASE)
def test_404_fails_at_once_naming_resource(respx_mock, client, sleeps):
    route = respx_mock.get("/filings/999/markdown/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    with pytest.raises(ProviderNotFound, match="/filings/999/markdown/"):
        client.get_markdown(999)
    assert route.call_count == 1 and sleeps == []


@respx.mock(base_url=BASE)
def test_other_4xx_fail_immediately(respx_mock, client, sleeps):
    route = respx_mock.get("/filings/").mock(
        return_value=httpx.Response(400, json={"detail": "unknown type"})
    )
    with pytest.raises(ProviderError, match="400 unknown type"):
        client.request("/filings/", {"type": "XX"})
    assert route.call_count == 1 and sleeps == []


@respx.mock(base_url=BASE)
def test_permanent_cache_and_refresh(respx_mock, settings, client):
    route = respx_mock.get("/companies/6901/financials/").mock(
        side_effect=[
            httpx.Response(200, json={"v": 1}, headers={"X-Credits-Charged": "40"}),
            httpx.Response(200, json={"v": 2}),
        ]
    )
    assert client.get_financials(6901) == {"v": 1}
    assert FRClient(settings).get_financials(6901) == {"v": 1}  # new client, same disk cache
    assert route.call_count == 1
    assert FRClient(settings, refresh=True).get_financials(6901) == {"v": 2}
    assert FRClient(settings).get_financials(6901) == {"v": 2}  # entry replaced
    assert route.call_count == 2
    recs = log_records(settings)
    assert [r["cache"] for r in recs] == ["miss", "hit", "refresh", "hit"]
    assert recs[0]["credits"] == 40 and recs[0]["credits_source"] == "header"
    assert recs[2]["credits"] == 40 and recs[2]["credits_source"] == "estimate"
    assert read_fr_totals(settings.logs_dir / "fr.jsonl") == {
        "calls": 4,
        "cache_hits": 2,
        "network_calls": 2,
        "credits_logged": 80,
    }


@respx.mock(base_url=BASE, assert_all_called=False)
def test_cached_mode_never_calls_network(respx_mock, settings):
    route = respx_mock.get("/companies/6901/financials/").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(NotCached, match="financials"):
        FRClient(settings, mode="cached").get_financials(6901)
    assert route.call_count == 0
    FRClient(settings).get_financials(6901)
    assert FRClient(settings, mode="cached").get_financials(6901) == {}
    assert route.call_count == 1
    with pytest.raises(ValueError):
        FRClient(settings, mode="cached", refresh=True)


def test_missing_key_explains_variable(tmp_path):
    with pytest.raises(MissingCredential, match="FR_API_KEY"):
        FRClient(Settings(data_dir=tmp_path)).usage()


# ---------------------------------------------------------------- endpoints


@respx.mock(base_url=BASE)
def test_search_companies(respx_mock, client):
    route = respx_mock.get("/companies/").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": 6901,
                            "name": "Malam-Team Ltd.",
                            "ticker": "MLTM",
                            "isins": ["IL0001560189"],
                            "country_code": "IL",
                            "unknown_field": 1,
                        }
                    ],
                },
            ),
            httpx.Response(200, json={"count": 0, "next": None, "results": []}),
        ]
    )
    (m,) = client.search_companies("מלם")
    assert (m.id, m.ticker, m.isin) == (6901, "MLTM", "IL0001560189")
    params = route.calls[0].request.url.params
    assert params["search"] == "מלם" and params["countries"] == "IL" and params["view"] == "full"
    assert client.search_companies("nothing-matches") == []


@respx.mock(base_url=BASE)
def test_list_filings_pages(respx_mock, client, fixtures_dir):
    page = json.loads((fixtures_dir / "malam_filings.json").read_text())
    first = {**page, "results": page["results"][:5], "next": f"{BASE}/filings/?page=2"}
    second = {**page, "results": page["results"][5:], "next": None}
    route = respx_mock.get("/filings/").mock(
        side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
    )
    filings = client.list_filings(6901)
    assert len(filings) == 8 and filings[0].id == 32935334
    assert filings[0].url.endswith(".pdf")
    p = route.calls[0].request.url.params
    assert (p["company"], p["type"], p["ordering"], p["view"]) == (
        "6901",
        "10-K",
        "-release_datetime",
        "full",
    )
    assert route.calls[1].request.url.params["page"] == "2"


@respx.mock(base_url=BASE)
def test_markdown_single_call(respx_mock, client):
    text = "# דוח\n\nשורה\n" * 10
    route = respx_mock.get("/filings/5/markdown/").mock(
        return_value=httpx.Response(200, text=text, headers={"X-Total-Chars": str(len(text))})
    )
    assert client.get_markdown(5) == text
    assert route.call_count == 1 and "offset" not in route.calls[0].request.url.params


@respx.mock(base_url=BASE)
def test_markdown_multi_page_follows_next_offset(respx_mock, settings, client):
    text = "א" * 250 + "ב" * 250 + "ג" * 100
    total = {"X-Total-Chars": "600"}

    def handler(request):
        offset = int(request.url.params.get("offset", 0))
        end = 250 if offset == 0 else min(offset + 250, 600)
        headers = dict(total)
        if end < 600:
            headers["X-Next-Offset"] = str(end)
        return httpx.Response(200, text=text[offset:end], headers=headers)

    route = respx_mock.get("/filings/6/markdown/").mock(side_effect=handler)
    assert client.get_markdown(6) == text
    assert [c.request.url.params.get("offset") for c in route.calls] == [None, "250", "500"]
    assert route.calls[1].request.url.params["limit"] == str(settings.fr_markdown_page_chars)
    assert sum(r["credits"] for r in log_records(settings)) == 18  # 3 billed calls x 6


@respx.mock(base_url=BASE)
def test_markdown_truncation_fails_and_keeps_nothing(respx_mock, settings, client):
    respx_mock.get("/filings/7/markdown/").mock(
        return_value=httpx.Response(200, text="short", headers={"X-Total-Chars": "999"})
    )
    with pytest.raises(TruncatedContent, match="999"):
        client.get_markdown(7)
    assert not client.is_cached("/filings/7/markdown/")
    assert not (settings.raw_dir).exists()


def test_save_and_load_report(settings):
    filing = Filing(
        id=32935334, title="Periodic and annual report for 2025", fiscal_year=2025, document="https://x/r.pdf"
    )
    text = "עמוד\r\nשני\n"
    meta = save_report(settings, "mltm", 2025, filing, text)
    assert (settings.raw_dir / "MLTM" / "2025.md").exists() and (
        settings.raw_dir / "MLTM" / "2025.meta.json"
    ).exists()
    loaded_text, loaded_meta = load_report(settings, "MLTM", 2025)
    assert loaded_text == text and loaded_meta.total_chars == len(text) == meta.total_chars
    assert loaded_meta.document_url == "https://x/r.pdf"
    assert load_report(settings, "MLTM", 2024) is None


@respx.mock(base_url=BASE)
def test_financials_with_revisions(respx_mock, client):
    route = respx_mock.get("/companies/6901/financials/").mock(return_value=httpx.Response(200, json={}))
    client.get_financials(6901, revisions=True)
    p = route.calls[0].request.url.params
    assert p["fiscal_period"] == "FY" and p["include"] == "revisions"


@respx.mock(base_url=BASE)
def test_usage_cached_mode_returns_last_seen(respx_mock, settings, client):
    respx_mock.get("/usage/").mock(
        return_value=httpx.Response(200, json={"free_credits": {"remaining": 400}})
    )
    client.usage()
    assert FRClient(settings, mode="cached").usage() == {"free_credits": {"remaining": 400}}
