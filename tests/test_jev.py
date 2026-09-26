import json

from capability_router.config import load_all
from capability_router.jev import FixtureJev, JevClient, answer_to_estimate, build_questions


def test_questions_follow_level_order_and_have_no_model_names(root):
    caps, models = load_all()
    q = build_questions(caps)
    assert set(q) == {"alpha", "beta", "gamma", "delta"}
    assert q["alpha"]["type"] == "score"
    assert q["alpha"]["criteria"] == ["n", "l", "m", "h"]
    blob = json.dumps(q)
    for m in models:
        assert m.model not in blob


def test_question_default_is_built_from_measures(root):
    caps, _ = load_all()
    q = build_questions(caps)
    assert q["alpha"]["instructions"] == (
        "How much does this task require the following capability: alpha measure "
        "Choose the lowest level that is sufficient."
    )


def test_criteria_carry_level_examples(root):
    caps, _ = load_all()
    q = build_questions(caps)
    assert q["beta"]["criteria"][2] == "m Examples: beta mid."
    assert q["gamma"]["criteria"] == ["n", "l", "m", "h"]


def test_answer_argmax_level(root):
    caps, _ = load_all()
    est = answer_to_estimate(caps, {"type": "score", "score": 1.9, "confidence": 0.5, "probabilities": {"0": 0.0, "1": 0.3, "2": 0.6, "3": 0.1}})
    assert est.level == "mid"
    assert abs(sum(est.probabilities.values()) - 1) < 1e-9


def test_fixture_replay(root, tmp_path):
    caps, _ = load_all()
    body = {"answers": {a: {"type": "score", "probabilities": {"3": 1.0}} for a in caps.items}}
    p = tmp_path / "fix.json"
    p.write_text(json.dumps({"default": body}), encoding="utf-8")
    est = FixtureJev(caps, p).estimate("anything")
    assert all(e.level == "high" for e in est.values())


def test_client_requires_key(root, monkeypatch):
    caps, _ = load_all()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    try:
        JevClient(caps)
    except RuntimeError as e:
        assert "TYPESAFE_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_request_body_shape(root, monkeypatch):
    caps, _ = load_all()
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    body = JevClient(caps).request_body("タスク")
    assert body["state"] == "タスク" and body["model"] == "jev-latest"
    assert body["questions"]["beta"]["instructions"] == (
        "How much does this task require the following capability: beta measure "
        "Choose the lowest level that is sufficient."
    )
