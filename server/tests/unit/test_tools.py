"""LLM tools over local data (analysis-tools spec)."""

import json
from datetime import date

import httpx
import respx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from stock_analyzer.api.main import create_app
from stock_analyzer.llm import OpenRouterLLM
from stock_analyzer.services.context import Ctx
from stock_analyzer.tools import AnalysisTools
from tests.conftest import seed_bank_and_insurer, seed_malam

URL = "https://openrouter.ai/api/v1/chat/completions"


def tools(settings, ticker="MLTM", **kw) -> AnalysisTools:
    seed_malam(settings)
    return AnalysisTools(Ctx(settings), ticker, **kw)


# -- task 6.1


def test_definitions_for_the_gateway(settings):
    defs = tools(settings).definitions
    assert [d["function"]["name"] for d in defs] == ["get_ratios", "get_financials"]
    for d in defs:
        assert d["type"] == "function" and d["function"]["description"]
        assert d["function"]["parameters"]["type"] == "object"


def test_ticker_and_date_are_not_arguments(settings):
    for d in tools(settings).definitions:
        props = set(d["function"]["parameters"]["properties"])
        assert not props & {"ticker", "as_of", "date", "company"}


def test_point_in_time(settings):
    out = tools(settings, as_of=date(2026, 3, 1)).call("get_ratios", {"codes": ["gross_margin"]})
    assert out["as_of"] == "2026-03-01" and 2025 not in out["fiscal_years"]
    assert all(v["fy"] != 2025 for v in out["ratios"][0]["values"])


def test_one_group(settings):
    out = tools(settings).call("get_ratios", {"group": "profitability"})
    assert {r["group"] for r in out["ratios"]} == {"profitability"}
    assert {r["code"] for r in out["ratios"]} == {
        "gross_margin",
        "operating_margin",
        "ebitda_margin",
        "net_margin",
    }
    assert len(out["ratios"][0]["values"]) == 5


def test_unknown_code_is_an_error_result(settings):
    t = tools(settings)
    assert "error" in t.call("get_ratios", {"codes": ["magic_ratio"]})
    out = t.call("get_ratios", {"codes": ["cet1_ratio"]})  # a bank ratio; Malam is industrial
    assert "does not apply to template industrial" in out["error"]
    assert "error" in t.call("get_ratios", {"group": "astrology"})
    assert "error" in t.call("get_financials", {"fields": ["loans_net"]})
    assert "error" in t.call("delete_everything", {})
    assert "error" in t.call("get_ratios", "{not json")


def test_selected_fields(settings):
    out = tools(settings).call("get_financials", json.dumps({"fields": ["revenue", "total_assets"]}))
    assert [f["field"] for f in out["fields"]] == ["revenue", "total_assets"]
    rev = out["fields"][0]["values"][0]
    assert rev == {"id": "FIN:revenue:2025", "fy": 2025, "value": "4138004000", "basis": "reported"}


def test_ratio_id(settings):
    out = tools(settings).call("get_ratios", {"codes": ["gross_margin"]})
    first = out["ratios"][0]["values"][0]
    assert first["id"] == "RATIO:gross_margin:2025" and first["value"] == "0.104733"


def test_bank_tool_set(settings):
    seed_bank_and_insurer(settings)
    out = AnalysisTools(Ctx(settings), "LUMI").call("get_ratios", {"group": "capital"})
    cet1 = next(r for r in out["ratios"] if r["code"] == "cet1_ratio")
    assert next(v for v in cet1["values"] if v["fy"] == 2024)["value"] == "0.1198"


def test_result_is_computed_once(settings, monkeypatch):
    from stock_analyzer import tools as tools_module

    calls = []
    real = tools_module.analyze
    monkeypatch.setattr(tools_module, "analyze", lambda *a, **k: calls.append(1) or real(*a, **k))
    t = tools(settings)
    t.call("get_ratios", {})
    t.call("get_financials", {})
    assert len(calls) == 1


# -- task 6.2


class Answer(BaseModel):
    text: str


@respx.mock
def test_definitions_pass_through_the_gateway(settings):
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "gen-1",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"text": "ok"}'},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0},
            },
        )
    )
    t = tools(settings)
    OpenRouterLLM(settings).complete_json("main", "sys", "user", Answer, tools=t.definitions, purpose="t")
    body = json.loads(route.calls[0].request.content)
    assert body["tools"] == t.definitions


def test_parity_with_the_api(settings):
    t = tools(settings, as_of=date(2026, 6, 1))
    via_tool = t.call("get_ratios", {})
    with TestClient(create_app(settings)) as c:
        api = c.get("/api/companies/MLTM/ratios", params={"as_of": "2026-06-01"}).json()
    api_values = {
        (r["code"], int(fy)): v for g in api["groups"] for r in g["ratios"] for fy, v in r["values"].items()
    }
    tool_values = {(r["code"], v["fy"]): v for r in via_tool["ratios"] for v in r["values"]}
    assert set(api_values) == set(tool_values)
    for key, tv in tool_values.items():
        av = api_values[key]
        assert (tv["value"], tv["confidence"], tv["status"], tv["failed_checks"]) == (
            av["value"], av["confidence"], av["status"], av["failed_checks"],
        ), key  # fmt: skip
