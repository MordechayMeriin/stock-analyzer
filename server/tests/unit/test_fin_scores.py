"""Scoring anchors and 1-10 arithmetic (company report)."""

from decimal import Decimal as D

import pytest

from stock_analyzer.fin import scores
from stock_analyzer.fin.ratios import ratios_for


def test_component_hits_its_anchors_and_interpolates():
    assert scores.component_score(D("0"), D("0"), D("0.15")) == 1
    assert scores.component_score(D("0.15"), D("0"), D("0.15")) == 10
    assert scores.component_score(D("0.075"), D("0"), D("0.15")) == D("5.5")


def test_component_is_clamped():
    assert scores.component_score(D("-1"), D("0"), D("0.15")) == 1
    assert scores.component_score(D("5"), D("0"), D("0.15")) == 10


def test_inverted_anchors_mean_lower_is_better():
    assert scores.component_score(D("2.0"), D("2.0"), D("0.0")) == 1
    assert scores.component_score(D("0"), D("2.0"), D("0.0")) == 10
    assert scores.component_score(D("1.0"), D("2.0"), D("0.0")) == D("5.5")
    assert scores.component_score(D("3"), D("2.0"), D("0.0")) == 1
    assert scores.component_score(D("-1"), D("2.0"), D("0.0")) == 10


def test_missing_value_has_no_score():
    assert scores.component_score(None, D("0"), D("1")) is None


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        ([D("5"), D("6")], 6),  # 5.5 rounds half up
        ([D("5"), D("5")], 5),
        ([D("4.4"), D("4.5")], 4),  # 4.45
        ([D("1"), D("10")], 6),  # 5.5
        ([D("9.9")], 10),
        ([D("3"), None], 3),  # a missing component is left out of the mean
        ([None, None], None),
        ([], None),
    ],
)
def test_axis_score_is_the_rounded_mean_of_available_components(parts, expected):
    assert scores.axis_score(parts) == expected


@pytest.mark.parametrize("template", ["industrial", "bank", "insurer"])
def test_every_anchored_ratio_exists_for_its_template(template):
    codes = {r.code for r in ratios_for(template)}
    axes = scores.axes_for(template)
    assert len(axes) >= 3
    for axis in axes:
        for c in axis.components:
            assert c.code in codes, (template, axis.id, c.code)
            assert c.bad != c.good


def test_industrial_axes_order():
    assert [a.id for a in scores.axes_for("industrial")] == [
        "stability",
        "safety",
        "growth",
        "profitability",
        "cash_quality",
    ]
    assert scores.axes_for("unknown") == ()
