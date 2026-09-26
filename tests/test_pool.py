"""Invariants that hold for any catalog, checked when it is loaded."""

from __future__ import annotations

from capability_router.config import load_all
from capability_router.normalize import item_cost_per_task, item_scores, item_time_per_task

from conftest import sync_pool


def test_item_cost_and_time_are_defined_for_every_config_item(root):
    caps, models = load_all()
    for m in models:
        costs, times, scores = item_cost_per_task(caps, m), item_time_per_task(caps, m), item_scores(caps, m)
        assert set(costs) == set(times) == set(scores) == set(caps.items)
        for item in m.items:
            assert costs[item] is not None and times[item] is not None


def test_scores_do_not_move_when_a_config_is_added(root):
    caps, models = load_all()
    before = {m.id: item_scores(caps, m) for m in models}
    (root / "models" / "extra.yaml").write_text(
        "id: extra\nmodel: X\neffort: max\n"
        "items:\n"
        "  alpha: {score: 0.99, cost_per_task: 1.0, time_per_task_s: 1.0}\n"
        "  beta: {score: 0.99, cost_per_task: 1.0, time_per_task_s: 1.0}\n"
        "  gamma: {level: H, cost_per_task: 1.0, time_per_task_s: 1.0}\n"
        "  delta: {score: null, cost_per_task: 1.0, time_per_task_s: 1.0}\n",
        encoding="utf-8",
    )
    sync_pool(root)
    caps2, models2 = load_all()
    after = {m.id: item_scores(caps2, m) for m in models2}
    for cfg_id, scores in before.items():
        assert after[cfg_id] == scores


def test_a_config_may_omit_an_item(root):
    # Dropping beta from one config leaves every other item value intact.
    text = (root / "models" / "cheap-low.yaml").read_text(encoding="utf-8")
    (root / "models" / "cheap-low.yaml").write_text(
        text.replace("  beta: {score: 0.30, cost_per_task: 2.0, time_per_task_s: 40.0}\n", ""),
        encoding="utf-8",
    )
    caps, models = load_all()
    cheap = next(m for m in models if m.id == "cheap-low")
    assert "beta" not in cheap.items
    assert item_scores(caps, cheap)["alpha"] == 0.30
    assert item_scores(caps, cheap)["beta"] is None
