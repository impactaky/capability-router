"""The shipped examples/ run end to end, and the two helper scripts follow their rules."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from capability_router.cli import main

REPO = Path(__file__).resolve().parents[1]


def _load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "examples" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _use_examples(monkeypatch) -> None:
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(REPO / "examples" / "capabilities.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(REPO / "examples" / "models"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(REPO / "examples" / "pool.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_SANITY", str(REPO / "examples" / "sanity.yaml"))


def test_examples_run_every_command(monkeypatch, capsys):
    _use_examples(monkeypatch)

    assert main(["models"]) == 0
    assert "example-small" in capsys.readouterr().out
    assert main(["models", "--detail"]) == 0
    assert "example-large" in capsys.readouterr().out
    assert main(["models", "--costs"]) == 0
    assert "example-mid" in capsys.readouterr().out

    assert main(["sanity"]) == 0
    table = capsys.readouterr().out
    spec = yaml.safe_load((REPO / "examples" / "sanity.yaml").read_text(encoding="utf-8"))
    for case in spec["tasks"]:
        assert case["id"] in table

    assert main(["criteria", "--output", "-"]) == 0
    criteria = capsys.readouterr().out
    assert criteria.startswith("<!-- capability-router criteria: sha256=")
    assert "### coding" in criteria and "### long_context" in criteria and "### writing" in criteria

    assert main(["route", "--no-usage", "--no-log", "--levels", "coding=mid,long_context=low,writing=none", "x"]) == 0
    chosen, service = capsys.readouterr().out.strip().split()
    assert chosen.startswith("example-")
    assert service in {"codex", "cursor", "claude", "commandcode"}


def test_example_definition_loads_with_the_example_catalog(monkeypatch):
    _use_examples(monkeypatch)
    from capability_router.config import load_all

    caps, models = load_all()
    assert list(caps.items) == ["coding", "long_context", "writing"]
    assert {m.id for m in models} == {"example-small", "example-mid", "example-large"}
    assert any(m.items["coding"].by_level for m in models)  # at least one uses a level


def test_levels_from_anchors_rule():
    mod = _load_module("levels_from_anchors", "levels_from_anchors.py")
    # low clears, then mid, then high: the highest reached before the first miss.
    assert mod.propose_level({"low": 0.9, "mid": 0.8, "high": 0.6}, 0.5) == "H"
    assert mod.propose_level({"low": 1.0, "mid": 0.7, "high": 0.3}, 0.5) == "M"
    assert mod.propose_level({"low": 0.6, "mid": 0.2, "high": 0.0}, 0.5) == "L"
    # below low: nothing is reached
    assert mod.propose_level({"low": 0.4, "mid": 0.9, "high": 0.9}, 0.5) == "-"
    # a missing level ends the ladder
    assert mod.propose_level({"low": 0.9}, 0.5) == "L"
    # the pass rate is the threshold, inclusive
    assert mod.propose_level({"low": 0.5}, 0.5) == "L"


def test_levels_from_anchors_on_the_shipped_example():
    mod = _load_module("levels_from_anchors_examples", "levels_from_anchors.py")
    data = yaml.safe_load((REPO / "examples" / "anchor-results.yaml").read_text(encoding="utf-8"))
    assert mod.levels_from(data, 0.5) == {
        "example-large": {"coding": "H"},
        "example-mid": {"coding": "M"},
        "example-small": {"coding": "L"},
        "example-spare": {"coding": "L"},
    }
    text = mod.render(mod.levels_from(data, 0.5))
    assert "coding: {level: H}" in text


def test_levels_from_anchors_quotes_the_lowest_level():
    # An unquoted dash would start a YAML sequence, so the renderer quotes it.
    mod = _load_module("levels_from_anchors_quote", "levels_from_anchors.py")
    text = mod.render({"example": {"coding": "-"}})
    assert "coding: {level: '-'}" in text


def test_thresholds_rule():
    mod = _load_module("thresholds", "thresholds.py")
    # no task count: high = best * 0.9, low = best / 3, mid the midpoint
    proposal = mod.propose(0.9, None)
    assert proposal["low"] == pytest.approx(0.3)
    assert proposal["high"] == pytest.approx(0.81)
    assert proposal["mid"] == pytest.approx((0.3 + 0.81) / 2)
    # with a task count: high = best - 2 * SE
    proposal = mod.propose(0.8, 10)
    assert proposal["high"] == pytest.approx(0.8 - 2 * (0.8 * 0.2 / 10) ** 0.5)
    # high below low collapses to low
    assert mod.propose(0.3, 1) == {"low": pytest.approx(0.1), "mid": pytest.approx(0.1), "high": pytest.approx(0.1)}


def test_thresholds_parse_tasks():
    mod = _load_module("thresholds_parse", "thresholds.py")
    assert mod.parse_tasks("coding=10,long_context=4") == {"coding": 10, "long_context": 4}
    assert mod.parse_tasks(None) == {}
    with pytest.raises(ValueError):
        mod.parse_tasks("coding")
    with pytest.raises(ValueError):
        mod.parse_tasks("coding=0")


def test_thresholds_on_the_shipped_example():
    mod = _load_module("thresholds_examples", "thresholds.py")
    best = mod.best_scores(REPO / "examples" / "models")
    assert best["long_context"] == pytest.approx(0.8)
    assert best["writing"] == pytest.approx(0.7)
    assert "coding" not in best  # only a level, no numeric score
    text = mod.render(
        ["coding", "long_context", "writing"],
        {item: mod.propose(score, 10) for item, score in best.items()},
    )
    assert "thresholds:" in text
    assert "# coding: no numeric score in the catalog, skipped" in text
