"""The delegation log: path resolution, record shape, the `log` commands, and isolation.

The autouse `_isolated_delegation_log` fixture (conftest) points every test at a tmp file, so
the real `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` is never touched.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from capability_router import delegation_log
from capability_router.cli import main
from rich.cells import cell_len


def _route_args(*extra: str) -> list[str]:
    """The args for a cheap alpha=high route."""
    return ["route", "--levels", "alpha=high", "--mode", "cheap", *extra, "solve this"]


def _log_file() -> Path:
    return Path(os.environ["CAPABILITY_ROUTER_LOG"])


def _records() -> list[dict]:
    return delegation_log.read_records(_log_file())[0]


# --- path resolution -----------------------------------------------------------------------


def test_log_path_env_wins_then_xdg_then_home_then_off():
    assert delegation_log.log_path({"CAPABILITY_ROUTER_LOG": "/x/log.jsonl"}) == Path("/x/log.jsonl")
    assert delegation_log.log_path({"CAPABILITY_ROUTER_LOG": "off"}) is None
    assert delegation_log.log_path({"XDG_STATE_HOME": "/state"}) == Path(
        "/state/capability-router/delegations.jsonl"
    )
    assert delegation_log.log_path({"HOME": "/home/u"}) == Path(
        "/home/u/.local/state/capability-router/delegations.jsonl"
    )


def test_parse_since_accepts_relative_and_date():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    assert delegation_log.parse_since("7d", now) == datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert delegation_log.parse_since("24h", now) == datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    assert delegation_log.parse_since("30m", now) == datetime(2026, 9, 24, 11, 30, tzinfo=timezone.utc)
    assert delegation_log.parse_since("2026-09-01") == datetime(2026, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        delegation_log.parse_since("yesterday")


# --- summarize -----------------------------------------------------------------------------


def _route(id: str, chosen, service, ts: str) -> dict:
    return {"type": "route", "version": 1, "id": id, "ts": ts, "chosen": chosen, "service": service}


def _outcome(id: str, status: str, ts: str, duration_s=None, rounds=None) -> dict:
    return {
        "type": "outcome",
        "version": 1,
        "id": id,
        "ts": ts,
        "status": status,
        "duration_s": duration_s,
        "rounds": rounds,
        "implementer": None,
        "note": None,
    }


def test_summarize_groups_by_config_and_service_using_the_last_outcome():
    records = [
        _route("a", "c1", "svc", "2026-09-20T00:00:00Z"),
        _route("b", "c1", "svc", "2026-09-21T00:00:00Z"),
        _route("c", "c2", "other", "2026-09-21T00:00:00Z"),
        _outcome("a", "fail", "2026-09-20T01:00:00Z", duration_s=10, rounds=2),
        _outcome("a", "pass", "2026-09-20T02:00:00Z", duration_s=20, rounds=1),
    ]
    summary = delegation_log.summarize(records)
    assert [(g["chosen"], g["service"]) for g in summary["groups"]] == [("c1", "svc"), ("c2", "other")]
    first = summary["groups"][0]
    assert first["routes"] == 2
    assert first["outcomes"] == 1  # only `a` has an outcome; the last one wins
    assert first["pass_rate"] == 100.0
    assert first["median_duration_s"] == 20.0
    assert first["median_rounds"] == 1.0
    second = summary["groups"][1]
    assert second["outcomes"] == 0 and second["pass_rate"] is None and second["median_rounds"] is None
    assert summary["total"] == {"routes": 3, "outcomes": 1, "pass_rate": 100.0, "median_duration_s": 20.0, "median_rounds": 1.0}


def test_summarize_since_filters_routes_by_ts():
    records = [
        _route("a", "c1", "svc", "2026-09-20T00:00:00Z"),
        _route("b", "c1", "svc", "2026-09-21T00:00:00Z"),
    ]
    cutoff = datetime(2026, 9, 21, tzinfo=timezone.utc)
    summary = delegation_log.summarize(records, cutoff)
    assert [g["routes"] for g in summary["groups"]] == [1]
    assert summary["total"]["routes"] == 1


def test_summarize_ignores_a_route_without_an_id():
    summary = delegation_log.summarize([_route("a", None, None, "2026-09-20T00:00:00Z")])
    assert summary["groups"][0]["chosen"] is None


# --- route record --------------------------------------------------------------------------

def test_route_default_stdout_is_two_words_and_writes_a_route_record(root, capsys):
    assert main(_route_args()) == 0
    assert capsys.readouterr().out.strip() == "mid-high claude"
    assert len(_records()) == 1
    r = _records()[0]
    assert r["type"] == "route" and r["version"] == 1
    assert len(r["id"]) == 12
    assert r["ts"].endswith("Z")
    assert r["label"] is None
    assert "task" not in r
    assert r["mode"] == "cheap"
    assert r["levels"] == {"alpha": "high"}  # only the items actually asked for
    assert r["chosen"] == "mid-high" and r["service"] == "claude"
    assert r["fallback"] is False
    assert r["cost"] == 2.0
    assert r["time_per_task_s"] == 40.0
    assert set(r) == {"type", "version", "id", "ts", "label", "mode", "levels", "chosen", "service",
                      "fallback", "cost", "time_per_task_s"}


def test_route_label_is_stored(root, capsys):
    assert main(_route_args("--label", "t")) == 0
    capsys.readouterr()
    assert _records()[0]["label"] == "t"


def test_route_print_log_id_prints_three_tokens(root, capsys):
    assert main(_route_args("--print-log-id")) == 0
    parts = capsys.readouterr().out.strip().split()
    assert parts[:2] == ["mid-high", "claude"]
    assert parts[2] == _records()[0]["id"]


def test_route_print_log_id_is_dash_when_not_logged(root, capsys, monkeypatch):
    assert main(_route_args("--no-log", "--print-log-id")) == 0
    assert capsys.readouterr().out.strip() == "mid-high claude -"
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", "off")
    assert main(_route_args("--print-log-id")) == 0
    assert capsys.readouterr().out.strip() == "mid-high claude -"


def test_route_no_log_and_off_do_not_create_the_file(root, capsys, monkeypatch):
    assert main(_route_args("--no-log")) == 0
    assert not _log_file().exists()
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", "off")
    assert main(_route_args()) == 0
    capsys.readouterr()


def test_route_task_is_stored_only_when_asked(root, capsys, monkeypatch):
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG_TASK", "1")
    assert main(_route_args()) == 0
    capsys.readouterr()
    assert _records()[0]["task"] == "solve this"


def test_route_log_write_failure_is_a_warning_not_a_failure(root, capsys, monkeypatch):
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", "/proc/nonexistent/x.jsonl")
    assert main(_route_args()) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "mid-high claude"
    assert out.err.startswith("warning: delegation log not written:")


def test_route_explain_carries_the_log_id(root, capsys):
    assert main(_route_args("--explain")) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["log_id"] == _records()[0]["id"]


def test_route_explain_log_id_is_null_when_not_logged(root, capsys):
    assert main(_route_args("--no-log", "--explain")) == 0
    assert json.loads(capsys.readouterr().out)["log_id"] is None


def test_route_writes_a_record_even_when_nothing_is_routable(root, capsys, tmp_path):
    snap = {
        "fetchedAt": "2026-09-23T07:48:00.000Z",
        "services": [
            {
                "id": sid,
                "name": sid,
                "status": "ok",
                "windows": [
                    {"label": "週", "remainingPercent": 0, "period": "week", "resetsAt": "2026-09-30T00:00:00Z"}
                ],
            }
            for sid in ("codex", "claude", "cursor", "commandcode")
        ],
    }
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(snap), encoding="utf-8")
    args = ["route", "--levels", "alpha=high", "--usage-file", str(usage_file), "t"]
    assert main(args) == 1
    assert "error: no routable config" in capsys.readouterr().err
    assert _records()[0]["chosen"] is None
    assert _records()[0]["service"] is None


# --- log outcome ---------------------------------------------------------------------------


def test_log_outcome_defaults_duration_from_the_route_ts(root, capsys):
    assert main(_route_args()) == 0
    capsys.readouterr()
    rid = _records()[0]["id"]
    assert main(["log", "outcome", rid, "--status", "pass", "--rounds", "1"]) == 0
    outcomes = [r for r in _records() if r["type"] == "outcome"]
    assert len(outcomes) == 1
    o = outcomes[0]
    assert o["id"] == rid and o["version"] == 1
    assert o["status"] == "pass" and o["rounds"] == 1
    assert isinstance(o["duration_s"], float) and o["duration_s"] >= 0
    assert o["implementer"] is None and o["note"] is None


def test_log_outcome_takes_the_explicit_values(root, capsys):
    assert main(_route_args()) == 0
    capsys.readouterr()
    rid = _records()[0]["id"]
    assert main(
        ["log", "outcome", rid, "--status", "abandoned", "--duration", "12.5",
         "--rounds", "3", "--implementer", "opencode:deepseek", "--note", "stopped"]
    ) == 0
    o = [r for r in _records() if r["type"] == "outcome"][0]
    assert o["duration_s"] == 12.5 and o["rounds"] == 3
    assert o["implementer"] == "opencode:deepseek" and o["note"] == "stopped"


def test_log_outcome_unknown_id_is_an_error(capsys):
    assert main(["log", "outcome", "nope", "--status", "pass"]) == 2
    assert "unknown delegation id: nope" in capsys.readouterr().err


def test_log_outcome_off_is_an_error(capsys, monkeypatch):
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", "off")
    assert main(["log", "outcome", "x", "--status", "pass"]) == 2
    assert "off" in capsys.readouterr().err


# --- log summary ---------------------------------------------------------------------------


def test_log_shows_counts_and_pass_rate(root, capsys):
    assert main(_route_args()) == 0
    rid = _records()[0]["id"]
    assert main(["log", "outcome", rid, "--status", "pass", "--duration", "30", "--rounds", "1"]) == 0
    capsys.readouterr()
    assert main(["log"]) == 0
    out = capsys.readouterr().out
    row = [ln for ln in out.splitlines() if ln.startswith("mid-high")][0].split()
    assert row == ["mid-high", "claude", "1", "1", "100%", "30", "1"]
    assert out.strip().splitlines()[-1].startswith("total")


def test_log_fits_an_80_column_terminal(root, capsys, monkeypatch):
    assert main(_route_args()) == 0
    rid = _records()[0]["id"]
    assert main(["log", "outcome", rid, "--status", "pass", "--duration", "30", "--rounds", "1"]) == 0
    capsys.readouterr()
    monkeypatch.setattr("capability_router.cli._is_terminal", lambda: True)
    monkeypatch.setenv("COLUMNS", "80")
    assert main(["log"]) == 0
    for line in capsys.readouterr().out.splitlines():
        assert cell_len(line) <= 80, f"{cell_len(line)} columns: {line!r}"


def test_log_uses_the_last_outcome(root, capsys):
    assert main(_route_args()) == 0
    rid = _records()[0]["id"]
    assert main(["log", "outcome", rid, "--status", "fail"]) == 0
    assert main(["log", "outcome", rid, "--status", "pass"]) == 0
    capsys.readouterr()
    assert main(["log"]) == 0
    assert "100%" in capsys.readouterr().out


def test_log_json_has_the_same_summary(root, capsys):
    assert main(_route_args()) == 0
    rid = _records()[0]["id"]
    assert main(["log", "outcome", rid, "--status", "pass", "--duration", "30", "--rounds", "1"]) == 0
    capsys.readouterr()
    assert main(["log", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    g = data["groups"][0]
    assert g["chosen"] == "mid-high" and g["service"] == "claude"
    assert g["routes"] == 1 and g["outcomes"] == 1
    assert g["pass_rate"] == 100.0 and g["median_duration_s"] == 30.0 and g["median_rounds"] == 1.0


def test_log_since_filters_by_route_ts(root, capsys):
    assert main(_route_args()) == 0
    capsys.readouterr()
    assert main(["log", "--since", "2999-01-01"]) == 0
    assert "mid-high" not in capsys.readouterr().out
    assert main(["log", "--since", "2000-01-01"]) == 0
    assert "mid-high" in capsys.readouterr().out


def test_log_bad_since_is_an_error(capsys):
    assert main(["log", "--since", "yesterday"]) == 2
    assert "bad --since" in capsys.readouterr().err


def test_log_skips_broken_lines_and_missing_file_is_zero(capsys):
    path = _log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('not json\n{"foo": 1}\n\n', encoding="utf-8")
    assert main(["log"]) == 0
    out = capsys.readouterr()
    assert "skipped 2 broken line(s)" in out.err
    assert out.out.strip().splitlines()[-1].startswith("total")

    path.unlink()
    assert main(["log"]) == 0
    assert "total" in capsys.readouterr().out


def test_log_off_is_an_error(capsys, monkeypatch):
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", "off")
    assert main(["log"]) == 2
    assert "off" in capsys.readouterr().err


# --- other commands ------------------------------------------------------------------------


def test_sanity_does_not_write_the_log(root, capsys):
    (root / "sanity.yaml").write_text(
        "tasks:\n  - id: s1\n    label: a\n    levels: {alpha: mid}\n", encoding="utf-8"
    )
    assert main(["sanity"]) == 0
    capsys.readouterr()
    assert not _log_file().exists()
