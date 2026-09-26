import json
import textwrap

import pytest
import yaml
from rich.cells import cell_len

from capability_router.cli import main


def _force_terminal(monkeypatch, width: int = 80) -> None:
    """Take the table's terminal path at a fixed width without needing a real TTY."""
    monkeypatch.setattr("capability_router.cli._is_terminal", lambda: True)
    monkeypatch.setenv("COLUMNS", str(width))


def _assert_fits_terminal(out: str, width: int = 80) -> None:
    for line in out.splitlines():
        assert cell_len(line) <= width, f"{cell_len(line)} columns: {line!r}"


def _column_width(out: str, name: str) -> int:
    """The rendered width of a sanity column, read from the padded header row."""
    header = next(ln for ln in out.splitlines() if ln.startswith("id "))
    start = header.index(name)
    end = start + len(name)
    while end < len(header) and header[end] == " ":
        end += 1
    return end - start - 1 if end < len(header) else len(header) - start


def test_route_levels_prints_config_id(root, capsys):
    rc = main(["route", "--levels", "alpha=high", "--mode", "cheap", "solve this"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "mid-high claude"


def test_route_explain_json(root, capsys):
    rc = main(["route", "--levels", "alpha=mid", "--explain", "do it"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chosen"] == "near-cheap"
    assert out["estimator"] == "fixed"
    assert set(out) >= {
        "chosen",
        "ranking",
        "estimates",
        "warnings",
        "thresholds",
        "relaxations",
        "selection",
    }


def test_route_explain_reports_user_thresholds_and_selection(root, capsys):
    assert main(["route", "--levels", "alpha=mid", "--explain", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["thresholds"]["alpha"] == {"low": 0.3, "mid": 0.5, "high": 0.7}
    assert out["thresholds"]["gamma"] is None  # decided by level alone
    assert out["relaxations"] == []
    assert out["selection"]["mode"] == "balanced"
    assert out["selection"]["cheapest_passing"]["config"] == "near-cheap"
    assert out["selection"]["chosen"]["config"] == "near-cheap"
    reason = [r for r in out["ranking"] if r["config"] == "cheap-low"][0]["reasons"]
    assert reason == ["alpha: 0.300 < 0.500 required for level mid"]


def test_route_explain_records_relaxations(root, capsys):
    # delta has no score in any config, so the requirement has to be relaxed before anyone passes.
    assert main(["route", "--levels", "delta=mid", "--explain", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fallback"] is True
    assert [(r["item"], r["from"], r["to"]) for r in out["relaxations"]] == [
        ("delta", "mid", "low"),
        ("delta", "low", "none"),
    ]
    assert out["chosen"] is not None


def test_route_stdin(root, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("some task\n"))
    assert main(["route", "--levels", "alpha=high"]) == 0
    assert capsys.readouterr().out.strip() == "mid-high claude"


def test_models_detail_table_carries_scores_thresholds_and_kinds(root, capsys):
    assert main(["models", "--detail"]) == 0
    out = capsys.readouterr().out
    score_table = out.split("kind per item:", 1)[0]
    lines = score_table.strip().splitlines()
    assert lines[0].split() == ["config", "a", "b", "g", "d"]
    assert [ln.split()[:2] for ln in lines[-3:]] == [
        ["threshold", "low"],
        ["threshold", "mid"],
        ["threshold", "high"],
    ]
    # alpha/beta thresholds 0.3/0.5/0.7, delta 0.25/0.45/0.65, gamma "-" (decided by level).
    assert lines[-1].split()[2:] == ["0.700", "0.700", "-", "0.650"]
    assert "items: a=alpha, b=beta, g=gamma, d=delta" in out
    assert "score = a catalog score" in out
    assert "kind per item: score = read a `score`, level = read a `level`." in out


def test_models_summary_grades_each_item(root, capsys):
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    summary, pool = out.split("\npool:")
    lines = summary.splitlines()
    assert lines[0].split() == ["config", "a", "b", "g", "d"]
    ids = {"cheap-low", "near-cheap", "mid-high", "strong-max"}
    rows = {ln.split()[0]: ln.split()[1:] for ln in lines if ln.split() and ln.split()[0] in ids}
    assert rows == {
        "cheap-low": ["L", "L", "L", "?"],
        "near-cheap": ["M", "M", "M", "?"],
        "mid-high": ["H", "H", "H", "?"],
        "strong-max": ["H", "H", "H", "?"],
    }
    assert "items: a=alpha, b=beta, g=gamma, d=delta" in out
    assert "H/M/L = clears the high/mid/low level, - = below low, ? = no value" in out
    assert "pool: 4 of 4 configs in the catalog are enabled (pool.yaml)." in out
    assert "cheap-low" in pool and "codex" in pool


def test_models_detail_and_costs_cannot_be_combined(root, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["models", "--detail", "--costs"])
    assert excinfo.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_models_costs_table(root, capsys):
    assert main(["models", "--costs"]) == 0
    out = capsys.readouterr().out
    cost_table, time_table = out.split("time per task (seconds)")
    row = [ln for ln in cost_table.splitlines() if ln.startswith("mid-high")][0].split()
    assert row[1:] == ["2.0000", "4.0000", "10.0000", "5.0000"]
    trow = [ln for ln in time_table.splitlines() if ln.startswith("mid-high")][0].split()
    assert trow[1:] == ["40.0", "80.0", "200.0", "100.0"]
    assert "a=alpha" in out and "d=delta" in out


def test_models_and_costs_fit_an_80_column_terminal(root, capsys, monkeypatch):
    _force_terminal(monkeypatch)
    assert main(["models"]) == 0
    _assert_fits_terminal(capsys.readouterr().out)
    assert main(["models", "--detail"]) == 0
    _assert_fits_terminal(capsys.readouterr().out)
    assert main(["models", "--costs"]) == 0
    _assert_fits_terminal(capsys.readouterr().out)


def test_sanity_fits_an_80_column_terminal(root, capsys, monkeypatch):
    _force_terminal(monkeypatch)
    assert main(["sanity"]) == 0
    _assert_fits_terminal(capsys.readouterr().out)


NINE_ITEMS = [f"item_{i}" for i in range(1, 10)]
# 23 characters, the width of a real catalog id; the tables must still fit 80 columns.
LONG_ID = "example-large-config-v2"


@pytest.fixture
def long_root(tmp_path, monkeypatch):
    """A 9-item root whose only catalog config has a 23-character id, enough to fill 80 columns."""
    levels = ["none", "low", "mid", "high"]
    caps = {
        "version": 3,
        "levels": levels,
        "items": {
            i: {
                "measures": f"m{i}",
                "excludes": f"e{i}",
                "levels": {lv: lv[0] for lv in levels},
                "thresholds": {"low": 0.3, "mid": 0.5, "high": 0.7},
            }
            for i in NINE_ITEMS
        },
    }
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(caps), encoding="utf-8")
    model = {
        "id": LONG_ID,
        "model": "Example",
        "effort": "high",
        "snapshot": "2026-09-26",
        "context_window_tokens": 1000000,
        "vision": True,
        "items": {
            i: {"score": 0.75, "cost_per_task": 0.1234, "time_per_task_s": 12.3}
            for i in NINE_ITEMS
        },
    }
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / f"{LONG_ID}.yaml").write_text(yaml.safe_dump(model), encoding="utf-8")
    (tmp_path / "pool.yaml").write_text(
        yaml.safe_dump({"configs": {LONG_ID: {"services": ["commandcode"]}}}), encoding="utf-8"
    )
    (tmp_path / "sanity.yaml").write_text(
        yaml.safe_dump({"tasks": [{"id": "s1", "label": "専門家級の難問への正答", "levels": {NINE_ITEMS[0]: "low"}}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(tmp_path / "capabilities.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(tmp_path / "pool.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_SANITY", str(tmp_path / "sanity.yaml"))
    return tmp_path


def test_models_score_table_with_a_23_char_id_fits_an_80_column_terminal(long_root, capsys, monkeypatch):
    _force_terminal(monkeypatch)
    assert main(["models", "--detail"]) == 0
    out = capsys.readouterr().out
    score_table = out.split("kind per item:")[0]
    rows = [ln for ln in score_table.splitlines() if ln.startswith(LONG_ID)]
    assert len(rows) == 1, f"{LONG_ID} split across lines: {rows!r}"
    assert rows[0].split() == [LONG_ID, *["0.750"] * 9]
    _assert_fits_terminal(out)
    # The default summary keeps the same 23-character id on one line, too.
    assert main(["models"]) == 0
    summary = capsys.readouterr().out.split("\npool:")[0]
    rows = [ln for ln in summary.splitlines() if ln.startswith(LONG_ID)]
    assert len(rows) == 1, f"{LONG_ID} split across lines: {rows!r}"
    assert rows[0].split() == [LONG_ID, *["H"] * 9]
    _assert_fits_terminal(summary)


def test_sanity_keeps_a_23_char_chosen_id_on_one_line(long_root, capsys, monkeypatch):
    _force_terminal(monkeypatch)
    assert main(["sanity"]) == 0
    out = capsys.readouterr().out
    assert any(ln.startswith("s1 ") and f" {LONG_ID} " in f" {ln} " for ln in out.splitlines()), (
        f"{LONG_ID} missing or split in {out!r}"
    )


def test_sanity_gives_label_and_levels_a_readable_minimum(long_root, capsys, monkeypatch):
    # The free-text columns wrap, but never to one or two characters: they keep a readable
    # minimum width even when the identifier columns no longer leave room.
    _force_terminal(monkeypatch)
    assert main(["sanity"]) == 0
    out = capsys.readouterr().out
    assert _column_width(out, "label") >= 12
    assert _column_width(out, "levels") >= 12


def test_piped_models_has_no_border_or_color_and_one_line_per_config(root, capsys):
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert not set(out) & set("─│┌┐└┘├┤┬┴┼")
    summary = out.split("\npool:")[0]
    for cid in ("cheap-low", "near-cheap", "mid-high", "strong-max"):
        assert len([ln for ln in summary.splitlines() if ln.startswith(cid)]) == 1


def test_route_explain_carries_the_cost_breakdown(root, capsys):
    assert main(["route", "--levels", "alpha=low,beta=low", "--explain", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cost_basis"] == "requested_items"
    assert out["cost_items_requested"] == ["alpha", "beta"]
    row = [r for r in out["ranking"] if r["config"] == "mid-high"][0]
    assert row["cost"] == pytest.approx(6.0)
    assert row["cost_items"] == {"alpha": pytest.approx(2.0), "beta": pytest.approx(4.0)}
    assert row["time_per_task_s"] == pytest.approx(120.0)
    assert out["selection"]["chosen"]["cost"] == pytest.approx(3.6)


def test_all_none_cost_basis_is_all_items(root, capsys):
    assert main(["route", "--levels", "alpha=none", "--explain", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cost_basis"] == "all_items"
    row = [r for r in out["ranking"] if r["config"] == "cheap-low"][0]
    assert row["cost"] == pytest.approx(10.5)


def test_bad_levels_is_error(root, capsys):
    assert main(["route", "--levels", "bogus=high", "x"]) == 2
    assert "unknown item" in capsys.readouterr().err


SANITY = """
tasks:
  - id: s1
    label: alpha mid
    levels: {alpha: mid}
  - id: s2
    label: alpha and beta low
    levels: {alpha: low, beta: low}
"""


def _write_sanity(root, body: str) -> None:
    (root / "sanity.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


def test_sanity_lists_every_case_in_table_and_json(root, capsys):
    assert main(["sanity"]) == 0
    table = capsys.readouterr().out
    assert "s1" in table and "s2" in table
    assert "cost/task" in table
    assert "distinct configs chosen:" in table and "relaxed:" in table
    # The set is a reading, not a check: no expected config, no match count, no DIFF.
    assert "expected" not in table and "DIFF" not in table and "matched" not in table

    assert main(["sanity", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "balanced"
    assert [r["id"] for r in data["results"]] == ["s1", "s2"]
    assert data["results"][0]["levels"] == {"alpha": "mid"}
    assert set(data["results"][0]) == {
        "id",
        "label",
        "levels",
        "chosen",
        "service",
        "cost_per_task",
        "time_per_task_s",
        "fallback",
        "relaxations",
    }


def test_sanity_reads_the_xdg_default_without_the_env(root, monkeypatch, capsys):
    monkeypatch.delenv("CAPABILITY_ROUTER_SANITY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "xdg"))
    target = root / "xdg" / "capability-router" / "sanity.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(SANITY), encoding="utf-8")
    assert main(["sanity", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in data["results"]] == ["s1", "s2"]


BAD_CASES = {
    "missing-id": """
        tasks:
          - label: no id
            levels: {alpha: mid}
    """,
    "missing-label": """
        tasks:
          - id: no-label
            levels: {alpha: mid}
    """,
    "missing-levels": """
        tasks:
          - id: no-levels
            label: none
    """,
    "unknown-item": """
        tasks:
          - id: bad-item
            label: bad
            levels: {nope: low}
    """,
    "unknown-level": """
        tasks:
          - id: bad-level
            label: bad
            levels: {alpha: bogus}
    """,
}


@pytest.mark.parametrize("body", BAD_CASES.values(), ids=BAD_CASES)
def test_sanity_bad_case_is_error(root, capsys, body):
    _write_sanity(root, body)
    assert main(["sanity"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: sanity case")
    assert "missing or empty" in err or "unknown" in err


def test_sanity_missing_label_names_the_case(root, capsys):
    _write_sanity(root, BAD_CASES["missing-label"])
    assert main(["sanity"]) == 2
    err = capsys.readouterr().err
    assert "no-label" in err and "'label'" in err


def test_sanity_unknown_level_names_the_case(root, capsys):
    _write_sanity(root, BAD_CASES["unknown-level"])
    assert main(["sanity"]) == 2
    err = capsys.readouterr().err
    assert "bad-level" in err and "unknown level 'bogus'" in err


def test_sanity_rejects_jev(root, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["sanity", "--jev"])
    assert excinfo.value.code == 2
    assert "unrecognized arguments: --jev" in capsys.readouterr().err
