"""Where the definition, catalog and pool.yaml are read from, and their absence errors."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from capability_router.cli import main
from capability_router.config import (
    capabilities_path,
    load_routing,
    models_dir,
    pool_path,
    sanity_path,
)
from conftest import CAPS, MODELS


def test_paths_prefer_env_then_xdg_then_home():
    assert capabilities_path({
        "CAPABILITY_ROUTER_CAPABILITIES": "/c.yaml",
        "XDG_CONFIG_HOME": "/cfg",
        "HOME": "/home",
    }) == Path("/c.yaml")
    assert capabilities_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/home"}) == Path("/cfg/capability-router/capabilities.yaml")
    assert capabilities_path({"HOME": "/home"}) == Path("/home/.config/capability-router/capabilities.yaml")
    assert sanity_path({"CAPABILITY_ROUTER_SANITY": "/s.yaml"}) == Path("/s.yaml")
    assert sanity_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/home"}) == Path("/cfg/capability-router/sanity.yaml")
    assert models_dir({
        "CAPABILITY_ROUTER_MODELS": "/cat",
        "XDG_STATE_HOME": "/state",
        "HOME": "/home",
    }) == Path("/cat")
    assert models_dir({"XDG_STATE_HOME": "/state", "HOME": "/home"}) == Path("/state/capability-router/models")
    assert models_dir({"HOME": "/home"}) == Path("/home/.local/state/capability-router/models")
    assert pool_path({
        "CAPABILITY_ROUTER_POOL": "/p.yaml",
        "XDG_CONFIG_HOME": "/cfg",
        "HOME": "/home",
    }) == Path("/p.yaml")
    assert pool_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/home"}) == Path("/cfg/capability-router/pool.yaml")
    assert pool_path({"HOME": "/home"}) == Path("/home/.config/capability-router/pool.yaml")


def _plant(config_dir: Path, models: Path, pool: Path, config_id: str = "cheap-low") -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    caps = config_dir / "capabilities.yaml"
    caps.write_text(textwrap.dedent(CAPS), encoding="utf-8")
    models.mkdir(parents=True)
    text = textwrap.dedent(MODELS["cheap-low"]).replace("id: cheap-low", f"id: {config_id}", 1)
    (models / f"{config_id}.yaml").write_text(text, encoding="utf-8")
    pool.parent.mkdir(parents=True, exist_ok=True)
    pool.write_text(
        yaml.safe_dump({"configs": {config_id: {"services": ["codex"]}}}),
        encoding="utf-8",
    )
    return caps


def test_env_overrides_are_read(tmp_path, monkeypatch):
    caps = _plant(tmp_path / "conf", tmp_path / "cat", tmp_path / "p.yaml", "from-env")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(caps))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "cat"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(tmp_path / "p.yaml"))
    _, loaded, _ = load_routing()
    assert [m.id for m in loaded] == ["from-env"]


def test_xdg_defaults_are_read_when_the_env_overrides_are_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPABILITY_ROUTER_CAPABILITIES", raising=False)
    monkeypatch.delenv("CAPABILITY_ROUTER_MODELS", raising=False)
    monkeypatch.delenv("CAPABILITY_ROUTER_POOL", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    caps = _plant(
        tmp_path / "config" / "capability-router",
        tmp_path / "state" / "capability-router" / "models",
        tmp_path / "config" / "capability-router" / "pool.yaml",
        "from-xdg",
    )
    _, loaded, _ = load_routing()
    assert [m.id for m in loaded] == ["from-xdg"]
    assert capabilities_path() == caps
    assert models_dir() == tmp_path / "state" / "capability-router" / "models"
    assert pool_path() == tmp_path / "config" / "capability-router" / "pool.yaml"


def test_missing_capabilities_names_the_path_and_the_env(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CAPABILITY_ROUTER_CAPABILITIES", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    expected = tmp_path / "config" / "capability-router" / "capabilities.yaml"
    for argv in (["models"], ["criteria"]):
        assert main(argv) == 2
        err = capsys.readouterr().err
        assert str(expected) in err
        assert "CAPABILITY_ROUTER_CAPABILITIES" in err
        assert "capabilities not found" in err


def test_missing_sanity_names_the_path_and_the_env(tmp_path, monkeypatch, capsys):
    caps = _plant(tmp_path / "conf", tmp_path / "cat", tmp_path / "p.yaml")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(caps))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "cat"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(tmp_path / "p.yaml"))
    monkeypatch.delenv("CAPABILITY_ROUTER_SANITY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    expected = tmp_path / "config" / "capability-router" / "sanity.yaml"
    assert main(["sanity"]) == 2
    err = capsys.readouterr().err
    assert str(expected) in err
    assert "CAPABILITY_ROUTER_SANITY" in err
    assert "sanity not found" in err


def test_missing_catalog_names_the_path_and_the_env(tmp_path, monkeypatch, capsys):
    caps = _plant(tmp_path / "conf", tmp_path / "cat", tmp_path / "p.yaml")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(caps))
    monkeypatch.delenv("CAPABILITY_ROUTER_MODELS", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    expected = tmp_path / "state" / "capability-router" / "models"
    for argv in (["models"], ["sanity"]):
        assert main(argv) == 2
        err = capsys.readouterr().err
        assert str(expected) in err
        assert "CAPABILITY_ROUTER_MODELS" in err
        assert "catalog not found" in err


def test_missing_pool_names_the_path_and_the_env(tmp_path, monkeypatch, capsys):
    caps = _plant(tmp_path / "conf", tmp_path / "cat", tmp_path / "p.yaml")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(caps))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "cat"))
    monkeypatch.delenv("CAPABILITY_ROUTER_POOL", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    expected = tmp_path / "config" / "capability-router" / "pool.yaml"
    assert main(["models"]) == 2
    err = capsys.readouterr().err
    assert str(expected) in err
    assert "CAPABILITY_ROUTER_POOL" in err
    assert "pool.yaml not found" in err


@pytest.mark.parametrize("body", ["", "- example\n", "sample\n"])
@pytest.mark.parametrize("command", ["models", "route"])
def test_non_mapping_catalog_reports_file_without_traceback(tmp_path, monkeypatch, capsys, body, command):
    caps = _plant(tmp_path / "conf", tmp_path / "cat", tmp_path / "p.yaml")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(caps))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "cat"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(tmp_path / "p.yaml"))
    invalid = tmp_path / "cat" / "broken.yaml"
    invalid.write_text(body, encoding="utf-8")
    argv = [command] if command == "models" else ["route", "--levels", "alpha=low", "x"]

    assert main(argv) == 2
    err = capsys.readouterr().err
    assert str(invalid) in err
    assert "must be a mapping" in err
    assert "Traceback" not in err
