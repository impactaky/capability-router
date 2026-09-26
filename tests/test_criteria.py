"""The generated LLM criteria (`capability-router criteria`) and the `route` staleness warning."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from capability_router.cli import CRITERIA_RULES, main


def _run_criteria(capsys, *extra: str) -> str:
    assert main(["criteria", "--output", "-", *extra]) == 0
    return capsys.readouterr().out


def test_criteria_starts_with_the_source_hash_and_the_shared_rules(root, capsys):
    out = _run_criteria(capsys)
    digest = hashlib.sha256((root / "capabilities.yaml").read_bytes()).hexdigest()
    lines = out.splitlines()
    assert lines[0] == f"<!-- capability-router criteria: sha256={digest} -->"
    for rule in CRITERIA_RULES:
        assert rule in out


def test_criteria_lists_items_in_definition_order_with_measures_excludes_and_levels(root, capsys):
    out = _run_criteria(capsys)
    items = re.findall(r"^### (\S+)$", out, flags=re.M)
    assert items == ["alpha", "beta", "gamma", "delta"]
    for name in items:
        block = out.split(f"### {name}", 1)[1].split("###", 1)[0]
        assert "Measures: " in block and "Excludes: " in block
        order = re.findall(r"^- (\w+):", block, flags=re.M)
        assert order == ["none", "low", "mid", "high"]


def test_criteria_puts_examples_under_their_level(root, capsys):
    out = _run_criteria(capsys)
    block = out.split("### beta", 1)[1].split("###", 1)[0]
    assert "  - e.g. beta mid" in block
    assert "  - e.g. beta low" in block


def test_criteria_writes_beside_the_definition_by_default(root, capsys):
    assert main(["criteria"]) == 0
    out = capsys.readouterr().out
    written = root / "criteria.md"
    assert written.is_file()
    assert str(written) in out
    assert written.read_text(encoding="utf-8").startswith("<!-- capability-router criteria: sha256=")


def test_route_warns_when_criteria_is_stale(root, capsys):
    assert main(["criteria"]) == 0
    capsys.readouterr()
    # Matching hash: no warning.
    assert main(["route", "--no-usage", "--no-log", "--levels", "alpha=low", "x"]) == 0
    assert "stale" not in capsys.readouterr().err
    # Change the definition by one byte: now stale, and the route still succeeds.
    text = (root / "capabilities.yaml").read_text(encoding="utf-8")
    (root / "capabilities.yaml").write_text(text + "\n# changed\n", encoding="utf-8")
    assert main(["route", "--no-usage", "--no-log", "--levels", "alpha=low", "x"]) == 0
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1 and err[0].startswith("warning:") and "stale" in err[0]


def test_route_does_not_warn_without_criteria(root, capsys):
    assert main(["route", "--no-usage", "--no-log", "--levels", "alpha=low", "x"]) == 0
    assert capsys.readouterr().err == ""


def test_route_does_not_warn_when_criteria_matches(root, capsys):
    assert main(["criteria"]) == 0
    capsys.readouterr()
    assert main(["route", "--no-usage", "--no-log", "--levels", "alpha=low", "x"]) == 0
    assert capsys.readouterr().err == ""
