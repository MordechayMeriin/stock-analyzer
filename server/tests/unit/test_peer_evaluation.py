"""Run the peer CLI against the versioned directory and score it against separate business reviews."""

import json

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import reset_settings_cache
from tests.conftest import FIXTURES

DIRECTORY = yaml.safe_load((FIXTURES / "peer_directory_v1.yaml").read_text())
REVIEWS = yaml.safe_load((FIXTURES / "peer_reviews_v1.yaml").read_text())
BASE = "https://peer-evaluation.invalid"


def review_selection(selected, case, judgements):
    accepted, unsuitable, unreviewed = [], [], []
    for issuer_id in selected:
        if issuer_id not in judgements:
            unreviewed.append(issuer_id)
        elif judgements[issuer_id]["judgement"] == "accepted":
            accepted.append(issuer_id)
        else:
            assert judgements[issuer_id]["judgement"] == "unsuitable"
            unsuitable.append(issuer_id)
    missed = sorted(set(case["suitable_in_scope"]) - set(selected))
    reviewed = len(accepted) + len(unsuitable)
    return {
        "accepted": accepted,
        "unsuitable": unsuitable,
        "unreviewed": unreviewed,
        "missed": missed,
        "reviewed": reviewed,
        "acceptance": len(accepted) / reviewed if reviewed else None,
    }


def check_selection(selected, expected):
    assert selected == expected, f"selected IDs {selected} differ from expected IDs {expected}"


def run_benchmark(case, settings, monkeypatch):
    ticker = case["ticker"]
    dataset = DIRECTORY[ticker]
    target_id = dataset["target_id"]
    profiles = {
        issuer_id: {
            "id": issuer_id,
            "name": issuer["name"],
            "country_code": issuer["country"],
            "sub_industry": {"code": dataset["class"]},
            "listing_status": "LISTED",
        }
        for issuer_id, issuer in dataset["issuers"].items()
    }
    registry = settings.data_dir / "evaluation-companies.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "companies": [
                    {"ticker": ticker, "fr_company_id": target_id, "name_he": profiles[target_id]["name"]}
                ]
            }
        )
    )
    for key, value in {
        "FR_BASE_URL": BASE,
        "FR_API_KEY": "test",
        "COMPANIES_FILE": registry,
        "DATA_DIR": settings.data_dir,
        "ALLOW_LIVE": "true",
    }.items():
        monkeypatch.setenv(key, str(value))
    reset_settings_cache()
    args = ["peer-financials", ticker, "--limit", str(case["limit"]), "--mode", "live"]
    for country in case["countries"]:
        args.extend(["--peer-country", country])

    with respx.mock(assert_all_called=True, assert_all_mocked=True) as router:
        router.get(f"{BASE}/companies/{target_id}/").respond(json=profiles[target_id])
        for country in ["IL", *case["countries"]]:
            params = {
                "countries": country,
                "listing_status": "LISTED",
                "sub_industry": dataset["class"],
                "page_size": 100,
                "view": "full",
                "page": 1,
            }
            url = httpx.URL(f"{BASE}/companies/", params=params)
            rows = [profiles[i] for i in dataset["directory"][country]]
            router.get(url).respond(json={"results": rows, "next": None})
        for issuer_id in case["selected"]:
            url = httpx.URL(f"{BASE}/companies/{issuer_id}/financials/", params={"fiscal_period": "FY"})
            router.get(url).respond(json={"periods": []})
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, (result.output, result.exception)
    return json.loads(result.output)


@pytest.mark.parametrize("name", REVIEWS["cases"])
def test_benchmark(name, settings, monkeypatch):
    case = REVIEWS["cases"][name]
    actual = run_benchmark(case, settings, monkeypatch)
    selected = [peer["id"] for peer in actual["peers"]]
    check_selection(selected, case["selected"])
    assert (actual["domestic_count"], actual["reason"]) == (case["domestic_count"], case["reason"])
    for peer in actual["peers"]:
        country = DIRECTORY[case["ticker"]]["issuers"][peer["id"]]["country"]
        assert (peer["country"], peer["kind"]) == (
            country,
            "domestic" if country == "IL" else "international",
        )

    judgements = REVIEWS["targets"][case["ticker"]]["judgements"]
    report = review_selection(selected, case, judgements)
    print(f"\n{name} | domestic count {actual['domestic_count']} | selected {selected}")
    if actual["reason"] == "no_domestic_matches":
        print("Expected empty domestic cohort: only the target is listed in this fixture's Israeli class.")
    for category in ("accepted", "unsuitable", "unreviewed", "missed"):
        print(f"  {category}: {report[category]}")
        for issuer_id in report[category]:
            if issuer_id in judgements:
                print(f"    {issuer_id} {judgements[issuer_id]['reason']}")
    fraction = f"{len(report['accepted'])}/{report['reviewed']}"
    rate = "inapplicable" if report["acceptance"] is None else format(report["acceptance"], ".0%")
    print(f"  acceptance among reviewed selections: {fraction} ({rate})")

    if name == "sole-domestic-operator":
        assert report["reviewed"] == 0 and report["acceptance"] is None
    elif name == "sole-operator-with-foreign-analogues":
        assert report["accepted"] == [920001] and report["unsuitable"] == [920002]
        assert report["acceptance"] == 0.5
    elif name == "mltm-limited":
        assert report["accepted"] == [910001] and report["unreviewed"] == [910002]
        assert report["missed"] == [910003] and report["reviewed"] == 1


def test_evaluator_rejects_wrong_selection_order():
    case = REVIEWS["cases"]["mltm-limited"]
    with pytest.raises(AssertionError, match="differ from expected IDs"):
        check_selection(list(reversed(case["selected"])), case["selected"])
