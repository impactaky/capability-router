from capability_router.config import load_all
from capability_router.normalize import item_cost_per_task, item_scores, item_time_per_task


def _by_id(models):
    return {m.id: m for m in models}


def test_item_score_is_the_catalog_score(root):
    caps, models = load_all()
    cheap = item_scores(caps, _by_id(models)["cheap-low"])
    assert cheap["alpha"] == 0.30  # absolute: no pool anchor, no min-max
    assert cheap["delta"] is None  # a null score is no score


def test_level_maps_to_the_fixed_midpoints_without_thresholds(root):
    caps, models = load_all()
    by_id = _by_id(models)
    assert item_scores(caps, by_id["cheap-low"])["gamma"] == 1 / 3
    assert item_scores(caps, by_id["near-cheap"])["gamma"] == 2 / 3
    assert item_scores(caps, by_id["mid-high"])["gamma"] == 1.0


def test_a_missing_item_has_no_score(root):
    caps, models = load_all()
    models[0].items.pop("beta")
    assert item_scores(caps, models[0])["beta"] is None


def test_cost_and_time_are_read_per_item(root):
    caps, models = load_all()
    cheap = _by_id(models)["cheap-low"]
    assert item_cost_per_task(caps, cheap) == {
        "alpha": 1.0, "beta": 2.0, "gamma": 5.0, "delta": 2.5,
    }
    assert item_time_per_task(caps, cheap) == {
        "alpha": 20.0, "beta": 40.0, "gamma": 100.0, "delta": 50.0,
    }
