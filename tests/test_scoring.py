import textwrap

import pytest

from capability_router.config import load_all
from capability_router.jev import FixedLevels
from capability_router.scoring import (
    MODES,
    TaskMeta,
    evaluate,
    ranking_weights,
    route,
    task_cost,
    thresholds,
)

from conftest import sync_pool


def _route(root, levels, mode="balanced", meta=None):
    caps, models = load_all()
    est = FixedLevels(caps, levels).estimate("task")
    return route(caps, models, est, meta or TaskMeta(), mode=mode)


def _add_config(root, name: str, body: str) -> None:
    (root / "models" / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    sync_pool(root)


def _keep_only(root, *names: str) -> None:
    for p in (root / "models").glob("*.yaml"):
        if p.stem not in names:
            p.unlink()
    sync_pool(root)


# --- (a) cheap = the cheapest config that satisfies every requirement -------------------------


def test_cheap_takes_the_cheapest_passing_config(root):
    # alpha=mid needs 0.5: cheap-low (0.30) drops; near-cheap (0.62) is the cheapest left.
    d = _route(root, {"alpha": "mid"}, mode="cheap")
    assert d.chosen.id == "near-cheap"
    assert not d.fallback
    passing = [c.config.id for c in d.candidates if c.passed]
    assert set(passing) == {"near-cheap", "mid-high", "strong-max"}
    assert d.selection["chosen"]["config"] == "near-cheap"


def test_cheap_is_not_the_cheapest_overall_when_it_fails(root):
    d = _route(root, {"alpha": "high"}, mode="cheap")
    assert d.chosen.id == "mid-high"  # 0.75 clears 0.7; cheaper configs do not
    reasons = {c.config.id: c.reasons for c in d.candidates}
    assert reasons["near-cheap"] == ["alpha: 0.620 < 0.700 required for level high"]


def test_best_takes_the_top_score_regardless_of_cost(root):
    d = _route(root, {"alpha": "mid"}, mode="best")
    assert d.chosen.id == "strong-max"


# --- (b) level-written items pass by step, and rank on the threshold value --------------------


def test_catalog_level_passes_by_step(root):
    # gamma is written as a level: L reaches low, M reaches mid, H reaches high, and never less.
    assert _route(root, {"gamma": "low"}, mode="cheap").chosen.id == "cheap-low"
    assert _route(root, {"gamma": "mid"}, mode="cheap").chosen.id == "near-cheap"
    assert _route(root, {"gamma": "high"}, mode="cheap").chosen.id == "mid-high"


def test_catalog_level_ranks_as_its_score(root):
    # No thresholds on gamma, so L/M/H stand for 1/3, 2/3, 1.0. With only gamma requested,
    # `best` picks the highest level even though every config passes gamma=low.
    d = _route(root, {"gamma": "low"}, mode="best")
    assert d.chosen.id in {"mid-high", "strong-max"}
    scores = {c.config.id: c.score for c in d.candidates}
    assert scores["cheap-low"] == pytest.approx(1 / 3)
    assert scores["near-cheap"] == pytest.approx(2 / 3)
    assert scores["mid-high"] == pytest.approx(1.0)


def test_level_with_thresholds_uses_the_threshold_value(root):
    # alpha is scored and has thresholds, so a config's value is its score; thresholds() reports
    # them and the item without them reports None.
    caps, _ = load_all()
    assert thresholds(caps)["alpha"] == {"low": 0.3, "mid": 0.5, "high": 0.7}
    assert thresholds(caps)["gamma"] is None


def test_level_uses_threshold_values_when_the_item_has_them(root):
    text = (root / "capabilities.yaml").read_text(encoding="utf-8")
    (root / "capabilities.yaml").write_text(
        text.replace(
            "    levels: {none: n, low: l, mid: m, high: h}\n  delta:",
            "    levels: {none: n, low: l, mid: m, high: h}\n"
            "    thresholds: {low: 0.4, mid: 0.6, high: 0.8}\n  delta:",
        ),
        encoding="utf-8",
    )
    caps, _ = load_all()
    assert caps.items["gamma"].score_for_level("L") == 0.4
    assert caps.items["gamma"].score_for_level("M") == 0.6
    assert caps.items["gamma"].score_for_level("H") == 0.8
    assert caps.items["gamma"].score_for_level("-") == 0.0
    assert caps.items["alpha"].score_for_level("L") == 0.3


@pytest.mark.parametrize("catalog_level", ["H", "M", "L", "-"])
@pytest.mark.parametrize(
    "required, expected",
    [
        ("none", {"H": True, "M": True, "L": True, "-": True}),
        ("low", {"H": True, "M": True, "L": True, "-": False}),
        ("mid", {"H": True, "M": True, "L": False, "-": False}),
        ("high", {"H": True, "M": False, "L": False, "-": False}),
    ],
)
def test_catalog_level_reaches_each_required_level(root, catalog_level, required, expected):
    from capability_router.config import levels_satisfied

    assert levels_satisfied(catalog_level, required) is expected[catalog_level]


# --- (c) balanced = cheapest passing, unless a band-and-margin config beats it -----------------


def test_balanced_starts_from_the_cheapest_passing_config(root):
    # Nothing required, so everything passes priced on all items: cheap-low 10.5, its budget
    # 13.125, and near-cheap 12.6 is inside it and more than score_margin better.
    d = _route(root, {})
    assert d.selection["cheapest_passing"]["config"] == "cheap-low"
    assert d.chosen.id == "near-cheap"
    assert d.selection["traded_up"] is True
    assert d.selection["score_delta"] >= d.selection["score_margin"]
    assert d.selection["budget"] == pytest.approx(10.5 * 1.25)


def test_balanced_ignores_a_better_score_outside_the_band(root):
    d = _route(root, {})
    scores = {c.config.id: c.score for c in d.candidates}
    assert scores["strong-max"] > scores["near-cheap"]  # better, but 105 is far past 13.125
    assert d.chosen.id != "strong-max"


def test_balanced_keeps_the_cheapest_when_the_gain_is_under_the_margin(root):
    _keep_only(root, "cheap-low")
    _add_config(root, "twin-low", """
        id: twin-low
        model: Twin
        effort: low
        context_window_tokens: 1000000
        vision: true
        items:
          alpha: {score: 0.32, cost_per_task: 1.1, time_per_task_s: 22.0}
          beta: {score: 0.32, cost_per_task: 2.2, time_per_task_s: 44.0}
          gamma: {level: L, cost_per_task: 5.5, time_per_task_s: 110.0}
          delta: {score: null, cost_per_task: 2.75, time_per_task_s: 55.0}
    """)
    d = _route(root, {})
    assert d.selection["cheapest_passing"]["config"] == "cheap-low"
    assert d.chosen.id == "cheap-low"
    assert d.selection["traded_up"] is False
    twin = [c for c in d.candidates if c.config.id == "twin-low"][0]
    assert twin.cost <= d.selection["budget"]  # inside the band
    assert 0 < twin.score - d.selection["cheapest_passing"]["score"] < d.selection["score_margin"]


def test_balanced_excludes_a_config_without_cost(root):
    # nocost-max omits beta, so an all-`none` request cannot total its items: no comparable cost.
    _add_config(root, "nocost-max", """
        id: nocost-max
        model: NoCost
        effort: max
        context_window_tokens: 1000000
        vision: true
        items:
          alpha: {score: 0.95, cost_per_task: 1.0, time_per_task_s: 1.0}
          gamma: {level: H, cost_per_task: 1.0, time_per_task_s: 1.0}
          delta: {score: null, cost_per_task: 1.0, time_per_task_s: 1.0}
    """)
    d = _route(root, {})
    assert d.chosen.id == "near-cheap"
    assert any("nocost-max" in w and "no cost data" in w for w in d.warnings)


# --- (d) fallback: relax the item that rejects the most configs, one level at a time -----------


def test_fallback_relaxes_the_worst_offender_first(root):
    # delta has no score anywhere, so it rejects all 4 configs; alpha=high rejects only 2.
    d = _route(root, {"delta": "low", "alpha": "high"}, mode="cheap")
    assert d.fallback
    assert [(r.item, r.from_level, r.to_level, r.rejected) for r in d.relaxations] == [
        ("delta", "low", "none", 4)
    ]
    assert d.required == {"alpha": "high", "beta": "none", "gamma": "none", "delta": "none"}
    assert d.chosen.id == "mid-high"  # alpha=high is still applied after the relaxation


def test_fallback_relaxes_one_level_per_step(root):
    d = _route(root, {"delta": "high", "alpha": "high"}, mode="cheap")
    assert [(r.item, r.from_level, r.to_level) for r in d.relaxations] == [
        ("delta", "high", "mid"),
        ("delta", "mid", "low"),
        ("delta", "low", "none"),
    ]
    assert d.chosen.id == "mid-high"
    assert any("relaxed delta high -> mid" in w for w in d.warnings)


def test_fallback_still_honours_the_mode(root):
    chosen = {mode: _route(root, {"delta": "low"}, mode=mode).chosen.id for mode in MODES}
    assert chosen["cheap"] == "cheap-low"
    assert chosen["best"] == "strong-max"
    assert chosen["balanced"] == "near-cheap"
    assert all(_route(root, {"delta": "low"}, mode=m).fallback for m in MODES)


def test_no_relaxation_when_something_passes(root):
    d = _route(root, {"alpha": "low"})
    assert not d.fallback and d.relaxations == []


# --- (e) a config with no value for an item fails whenever it is required ----------------------


def test_item_with_no_value_fails_when_required(root):
    caps, models = load_all()
    required = {"alpha": "none", "beta": "none", "gamma": "none", "delta": "low"}
    candidates = evaluate(
        caps, models, required, ranking_weights(caps, required), TaskMeta()
    )
    assert not any(c.passed for c in candidates)
    assert all(
        c.reasons == ["delta: no score but level low required"] for c in candidates
    )


def test_a_config_missing_an_item_says_so(root):
    _add_config(root, "partial", """
        id: partial
        model: Partial
        effort: low
        context_window_tokens: 1000000
        vision: true
        items:
          alpha: {score: 0.9, cost_per_task: 1.0, time_per_task_s: 1.0}
    """)
    caps, models = load_all()
    required = {"alpha": "none", "beta": "low", "gamma": "none", "delta": "none"}
    candidates = evaluate(caps, models, required, ranking_weights(caps, required), TaskMeta())
    partial = [c for c in candidates if c.config.id == "partial"][0]
    assert partial.reasons == ["beta: no value but level low required"]


def test_item_with_no_value_is_ignored_when_not_required(root):
    caps, models = load_all()
    required = {"alpha": "low", "beta": "none", "gamma": "none", "delta": "none"}
    candidates = evaluate(caps, models, required, ranking_weights(caps, required), TaskMeta())
    assert all(c.passed for c in candidates)


# --- ranking ----------------------------------------------------------------------------------


def test_geometric_mean_punishes_a_weak_item(root):
    _add_config(root, "lopsided-high", """
        id: lopsided-high
        model: Lopsided
        effort: high
        context_window_tokens: 1000000
        vision: true
        items:
          alpha: {score: 1.0, cost_per_task: 2.0, time_per_task_s: 40.0}
          beta: {score: 0.1, cost_per_task: 4.0, time_per_task_s: 80.0}
          gamma: {level: H, cost_per_task: 10.0, time_per_task_s: 200.0}
          delta: {score: null, cost_per_task: 5.0, time_per_task_s: 100.0}
    """)
    d = _route(root, {"alpha": "low", "beta": "low"}, mode="best")
    scores = {c.config.id: c.score for c in d.candidates}
    assert scores["lopsided-high"] < scores["mid-high"]  # arithmetic mean would say otherwise


def test_ranking_weights_come_from_the_requested_levels(root):
    caps, _ = load_all()
    assert ranking_weights(caps, {"alpha": "high", "beta": "low"}) == {
        "alpha": 3.0, "beta": 1.0, "gamma": 0.0, "delta": 0.0
    }
    # nothing requested: rank on every item equally so `best` still means something
    assert ranking_weights(caps, {}) == {"alpha": 1.0, "beta": 1.0, "gamma": 1.0, "delta": 1.0}


def test_metadata_filters_vision_and_context(root):
    d = _route(root, {"alpha": "low"}, mode="cheap", meta=TaskMeta(has_image=True))
    reasons = {c.config.id: c.reasons for c in d.candidates}
    assert any("vision" in r for r in reasons["mid-high"])
    assert d.chosen.id == "cheap-low"
    d = _route(root, {"alpha": "low"}, mode="cheap", meta=TaskMeta(input_tokens=150_000))
    reasons = {c.config.id: c.reasons for c in d.candidates}
    assert any("context window" in r for r in reasons["cheap-low"])
    assert d.chosen.id == "near-cheap"


def test_unknown_item_rejected(root):
    caps, _ = load_all()
    with pytest.raises(ValueError):
        FixedLevels(caps, {"nope": "high"})


def test_unknown_mode_rejected(root):
    with pytest.raises(ValueError):
        _route(root, {}, mode="fastest")


# --- cost is the sum of the items the request actually asks for --------------------------------


def test_cost_is_the_sum_of_the_requested_items(root):
    d = _route(root, {"alpha": "low", "beta": "mid"}, mode="cheap")
    costs = {c.config.id: c.cost for c in d.candidates}
    assert costs == {
        "cheap-low": pytest.approx(3.0),
        "near-cheap": pytest.approx(3.6),
        "mid-high": pytest.approx(6.0),
        "strong-max": pytest.approx(30.0),
    }
    cand = [c for c in d.candidates if c.config.id == "mid-high"][0]
    assert cand.cost_items == {"alpha": pytest.approx(2.0), "beta": pytest.approx(4.0)}
    assert cand.time_per_task_s == pytest.approx(120.0)
    assert d.cost_basis == "requested_items"


def test_cost_leaves_out_the_items_the_request_does_not_ask_for(root):
    cheap_alpha = _route(root, {"alpha": "low"}, mode="cheap")
    cheap_gamma = _route(root, {"gamma": "low"}, mode="cheap")
    by_id = lambda d, i: [c for c in d.candidates if c.config.id == i][0].cost
    assert by_id(cheap_alpha, "mid-high") == pytest.approx(2.0)
    assert by_id(cheap_gamma, "mid-high") == pytest.approx(10.0)


def test_cost_falls_back_to_every_item_when_nothing_is_required(root):
    d = _route(root, {})
    assert d.cost_basis == "all_items"
    assert {c.config.id: c.cost for c in d.candidates} == {
        "cheap-low": pytest.approx(10.5),
        "near-cheap": pytest.approx(12.6),
        "mid-high": pytest.approx(21.0),
        "strong-max": pytest.approx(105.0),
    }
    row = [c for c in d.candidates if c.config.id == "mid-high"][0]
    assert set(row.cost_items) == {"alpha", "beta", "gamma", "delta"}


def test_task_cost_is_priced_on_the_request_not_on_the_relaxed_requirement(root):
    caps, models = load_all()
    cfg = [m for m in models if m.id == "mid-high"][0]
    asked, items, seconds = task_cost(caps, cfg, {"alpha": "high", "beta": "low"})
    assert asked == pytest.approx(6.0) and set(items) == {"alpha", "beta"}
    assert seconds == pytest.approx(120.0)
    relaxed, every, _ = task_cost(caps, cfg, {"alpha": "none", "beta": "none"})
    assert relaxed == pytest.approx(21.0) and set(every) == {"alpha", "beta", "gamma", "delta"}


# --- fast-balanced = the cheapest passing config, traded up for time inside time_cost_band ------


def _add_quick(root, cost: float, time: float) -> None:
    # clears alpha=mid (0.70 >= 0.5) but not alpha=high (0.7 is reached exactly, so it does)
    _add_config(root, "quick", f"""
        id: quick
        model: Quick
        effort: low
        snapshot: 2026-09-23
        context_window_tokens: 1000000
        vision: true
        items:
          alpha: {{score: 0.70, cost_per_task: {cost}, time_per_task_s: {time}}}
          beta: {{score: 0.70, cost_per_task: 5.0, time_per_task_s: 5.0}}
          gamma: {{level: H, cost_per_task: 5.0, time_per_task_s: 5.0}}
          delta: {{score: null, cost_per_task: 5.0, time_per_task_s: 5.0}}
    """)


def test_fast_balanced_trades_up_to_a_quicker_config_inside_the_band(root):
    # base near-cheap: cost 1.2, 24 s. quick: 2.5 <= 1.2 * 2.5 and 5 s <= 24 * 0.5.
    _add_quick(root, cost=2.5, time=5.0)
    d = _route(root, {"alpha": "mid"}, mode="fast-balanced")
    assert d.chosen.id == "quick"
    assert d.selection["cheapest_passing"]["config"] == "near-cheap"
    assert d.selection["traded_up"]
    assert _route(root, {"alpha": "mid"}, mode="cheap").chosen.id == "near-cheap"
    assert _route(root, {"alpha": "mid"}, mode="balanced").chosen.id == "near-cheap"


def test_fast_balanced_keeps_the_base_when_the_quicker_config_is_too_dear(root):
    _add_quick(root, cost=3.5, time=5.0)  # 3.5 > 1.2 * 2.5
    d = _route(root, {"alpha": "mid"}, mode="fast-balanced")
    assert d.chosen.id == "near-cheap"
    assert not d.selection["traded_up"]


def test_fast_balanced_keeps_the_base_when_the_time_gain_is_small(root):
    _add_quick(root, cost=1.5, time=13.0)  # 13 > 24 * 0.5
    assert _route(root, {"alpha": "mid"}, mode="fast-balanced").chosen.id == "near-cheap"


def test_an_all_none_request_is_timed_on_every_item(root):
    d = _route(root, {}, mode="fast-balanced")
    assert d.chosen.id == "cheap-low"
    times = {c.config.id: c.time_per_task_s for c in d.candidates}
    assert times["cheap-low"] == pytest.approx(20.0 + 40.0 + 100.0 + 50.0)
