"""The capability definition and catalog loaders: shapes, validation and old-format errors."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from capability_router.config import (
    capabilities_path,
    criteria_path,
    load_all,
    load_capabilities,
    sanity_path,
)

from conftest import CAPS


def _write_caps(root: Path, text: str) -> None:
    (root / "capabilities.yaml").write_text(textwrap.dedent(text), encoding="utf-8")


def _write_model(root: Path, name: str, body: str) -> None:
    (root / "models" / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    from conftest import sync_pool

    sync_pool(root)


def _load_caps(root: Path):
    return load_capabilities(capabilities_path())


# --- paths ------------------------------------------------------------------------------------


def test_capability_and_sanity_paths_prefer_env_then_xdg_then_home():
    assert capabilities_path(
        {"CAPABILITY_ROUTER_CAPABILITIES": "/c.yaml", "XDG_CONFIG_HOME": "/cfg", "HOME": "/h"}
    ) == Path("/c.yaml")
    assert capabilities_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"}) == Path("/cfg/capability-router/capabilities.yaml")
    assert capabilities_path({"HOME": "/h"}) == Path("/h/.config/capability-router/capabilities.yaml")
    assert sanity_path({"CAPABILITY_ROUTER_SANITY": "/s.yaml"}) == Path("/s.yaml")
    assert sanity_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"}) == Path("/cfg/capability-router/sanity.yaml")
    assert criteria_path(Path("/cfg/capability-router/capabilities.yaml")) == Path("/cfg/capability-router/criteria.md")


# --- capability definition --------------------------------------------------------------------


def test_items_can_have_any_name_and_count(root):
    _write_caps(root, """
        version: 3
        items:
          only_item:
            measures: m
            excludes: e
            levels: {none: n, low: l, mid: m, high: h}
    """)
    caps = _load_caps(root)
    assert list(caps.items) == ["only_item"]


def test_levels_may_be_omitted_and_the_default_is_fixed(root):
    caps = _load_caps(root)
    assert caps.levels == ("none", "low", "mid", "high")


def test_levels_must_be_exactly_the_ladder(root):
    _write_caps(root, """
        version: 3
        levels: [none, low, high]
        items:
          i:
            measures: m
            excludes: e
            levels: {none: n, low: l, mid: m, high: h}
    """)
    with pytest.raises(ValueError, match=r"`levels` must be exactly"):
        load_all()


def test_question_default_comes_from_measures(root):
    caps = _load_caps(root)
    assert caps.items["alpha"].question_text() == (
        "How much does this task require the following capability: alpha measure "
        "Choose the lowest level that is sufficient."
    )
    assert caps.items["alpha"].question is None


def test_explicit_question_wins(root):
    _write_caps(root, """
        version: 3
        items:
          i:
            measures: m
            excludes: e
            question: exactly this
            levels: {none: n, low: l, mid: m, high: h}
    """)
    assert _load_caps(root).items["i"].question_text() == "exactly this"


def test_examples_append_to_the_level_text(root):
    caps = _load_caps(root)
    assert caps.items["beta"].criteria_for("mid") == "m Examples: beta mid."


@pytest.mark.parametrize(
    "examples, match",
    [
        ("{none: [x]}", "may only key"),
        ("{nope: [x]}", "may only key"),
        ("{low: []}", "non-empty list"),
        ("{low: [1, 2]}", "non-empty strings"),
        ("{low: 'x'}", "non-empty list"),
    ],
)
def test_bad_examples_name_the_item(root, examples, match):
    _write_caps(root, f"""
        version: 3
        items:
          my_item:
            measures: m
            excludes: e
            levels: {{none: n, low: l, mid: m, high: h}}
            examples: {examples}
    """)
    with pytest.raises(ValueError, match=rf"my_item.*{match}"):
        load_all()


@pytest.mark.parametrize(
    "thresholds, match",
    [
        ("{low: 0.6, mid: 0.5, high: 0.7}", "low <= mid <= high"),
        ("{low: 0.3, mid: 0.5}", "exactly"),
        ("{low: 0.3, mid: 0.5, high: 1.5}", "between 0 and 1"),
        ("{low: -1, mid: 0.5, high: 0.7}", "between 0 and 1"),
    ],
)
def test_bad_thresholds_name_the_item(root, thresholds, match):
    _write_caps(root, f"""
        version: 3
        items:
          my_item:
            measures: m
            excludes: e
            levels: {{none: n, low: l, mid: m, high: h}}
            thresholds: {thresholds}
    """)
    with pytest.raises(ValueError, match=rf"my_item.*{match}"):
        load_all()


def test_item_missing_a_level_is_an_error(root):
    _write_caps(root, """
        version: 3
        items:
          my_item:
            measures: m
            excludes: e
            levels: {none: n, low: l, mid: m}
    """)
    with pytest.raises(ValueError, match=r"my_item.*missing \['high'\]"):
        load_all()


@pytest.mark.parametrize("old_key", ["axes", "benchmarks", "thresholds", "level_weight"])
def test_old_capability_keys_are_named_in_the_error(root, old_key):
    _write_caps(root, f"""
        version: 3
        {old_key}: {{}}
        items:
          i:
            measures: m
            excludes: e
            levels: {{none: n, low: l, mid: m, high: h}}
    """)
    with pytest.raises(ValueError, match=old_key):
        load_all()


def test_old_capability_version_is_rejected(root):
    _write_caps(root, """
        version: 2
        items:
          i:
            measures: m
            excludes: e
            levels: {none: n, low: l, mid: m, high: h}
    """)
    with pytest.raises(ValueError, match="version 2"):
        load_all()


# --- catalog ----------------------------------------------------------------------------------


def test_catalog_item_may_be_score_or_level(root):
    caps, models = load_all()
    by_id = {m.id: m for m in models}
    assert by_id["cheap-low"].items["alpha"].score == pytest.approx(0.30)
    assert by_id["cheap-low"].items["gamma"].level == "L"
    assert by_id["cheap-low"].items["gamma"].by_level


@pytest.mark.parametrize(
    "body, match",
    [
        ("{score: 0.5, level: H, cost_per_task: 1, time_per_task_s: 1}", "exactly one"),
        ("{cost_per_task: 1, time_per_task_s: 1}", "exactly one"),
        ("{score: 1.5, cost_per_task: 1, time_per_task_s: 1}", "between 0 and 1"),
        ("{level: Z, cost_per_task: 1, time_per_task_s: 1}", "unknown level"),
        ("{score: 0.5, time_per_task_s: 1}", "missing cost_per_task"),
        ("{score: 0.5, cost_per_task: 1}", "missing time_per_task_s"),
        ("{score: 0.5, cost_per_task: -1, time_per_task_s: 1}", "must be 0 or more"),
    ],
)
def test_bad_catalog_item_names_the_config_and_item(root, body, match):
    _write_model(root, "broken", f"""
        id: broken
        model: Broken
        items:
          beta: {body}
    """)
    with pytest.raises(ValueError, match=rf"broken.*beta.*{match}"):
        load_all()


def test_catalog_item_not_in_the_definition_is_an_error(root):
    _write_model(root, "broken", """
        id: broken
        model: Broken
        items:
          nope: {score: 0.5, cost_per_task: 1, time_per_task_s: 1}
    """)
    with pytest.raises(ValueError, match=r"broken.*'nope'.*not in the capability definition"):
        load_all()


def test_scored_item_without_thresholds_is_an_error(root):
    text = (root / "capabilities.yaml").read_text(encoding="utf-8")
    assert "    thresholds: {low: 0.3, mid: 0.5, high: 0.7}\n" in text
    (root / "capabilities.yaml").write_text(
        text.replace("    thresholds: {low: 0.3, mid: 0.5, high: 0.7}\n", "", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"alpha: .*no `thresholds`"):
        load_all()


def test_quoted_dash_level_loads(root):
    # In block style the lowest level must be quoted, or YAML reads the dash as a sequence start.
    _write_model(root, "quoted", """
        id: quoted
        model: Quoted
        items:
          alpha: {score: 0.5, cost_per_task: 1.0, time_per_task_s: 1.0}
          gamma:
            level: '-'
            cost_per_task: 1.0
            time_per_task_s: 1.0
    """)
    _, models = load_all()
    quoted = next(m for m in models if m.id == "quoted")
    assert quoted.items["gamma"].level == "-"


@pytest.mark.parametrize("old_key", ["benchmarks", "evaluations", "cost", "performance", "source"])
def test_old_catalog_keys_are_named_in_the_error(root, old_key):
    _write_model(root, "old", f"""
        id: old
        model: Old
        {old_key}: {{}}
        items:
          alpha: {{score: 0.5, cost_per_task: 1, time_per_task_s: 1}}
    """)
    with pytest.raises(ValueError, match=old_key):
        load_all()
