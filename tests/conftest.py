from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

# Four synthetic items: alpha/beta/delta are scored against explicit thresholds, gamma is written
# as a level and has no thresholds (so H/M/L stand for 1.0 / 2/3 / 1/3). Every config carries
# every item; delta is scored `null` everywhere, which exercises "a value exists for cost but the
# item has no score, so requiring it fails" without making an all-`none` request unpriceable.
CAPS = """
version: 3
levels: [none, low, mid, high]
items:
  alpha:
    measures: alpha measure
    excludes: alpha excludes
    levels: {none: n, low: l, mid: m, high: h}
    thresholds: {low: 0.3, mid: 0.5, high: 0.7}
  beta:
    measures: beta measure
    excludes: beta excludes
    levels: {none: n, low: l, mid: m, high: h}
    examples: {low: [beta low], mid: [beta mid], high: [beta high]}
    thresholds: {low: 0.3, mid: 0.5, high: 0.7}
  gamma:
    measures: gamma measure
    excludes: gamma excludes
    levels: {none: n, low: l, mid: m, high: h}
  delta:
    measures: delta measure
    excludes: delta excludes
    levels: {none: n, low: l, mid: m, high: h}
    thresholds: {low: 0.25, mid: 0.45, high: 0.65}
routing:
  cost_band: 1.25
  score_margin: 0.05
  time_cost_band: 2.5
  time_ratio: 0.5
"""

# Per-evaluation costs keep the cheap-to-dear order while charging a different amount per item.
# cheap-low prices an all-`none` request at 10.5, so `balanced`'s budget is 10.5 * 1.25 = 13.125
# and near-cheap at 12.6 is the only other config inside it. near-cheap also scores far enough
# above cheap-low to clear score_margin, so `balanced` trades up to it.
MODELS = {
    "cheap-low": """
id: cheap-low
model: Cheap
effort: low
snapshot: 2026-09-23
context_window_tokens: 100000
vision: true
items:
  alpha: {score: 0.30, cost_per_task: 1.0, time_per_task_s: 20.0}
  beta: {score: 0.30, cost_per_task: 2.0, time_per_task_s: 40.0}
  gamma: {level: L, cost_per_task: 5.0, time_per_task_s: 100.0}
  delta: {score: null, cost_per_task: 2.5, time_per_task_s: 50.0}
""",
    "near-cheap": """
id: near-cheap
model: NearCheap
effort: mid
snapshot: 2026-09-23
context_window_tokens: 1000000
vision: true
items:
  alpha: {score: 0.62, cost_per_task: 1.2, time_per_task_s: 24.0}
  beta: {score: 0.62, cost_per_task: 2.4, time_per_task_s: 48.0}
  gamma: {level: M, cost_per_task: 6.0, time_per_task_s: 120.0}
  delta: {score: null, cost_per_task: 3.0, time_per_task_s: 60.0}
""",
    "mid-high": """
id: mid-high
model: Mid
effort: high
snapshot: 2026-09-23
context_window_tokens: 200000
vision: false
items:
  alpha: {score: 0.75, cost_per_task: 2.0, time_per_task_s: 40.0}
  beta: {score: 0.75, cost_per_task: 4.0, time_per_task_s: 80.0}
  gamma: {level: H, cost_per_task: 10.0, time_per_task_s: 200.0}
  delta: {score: null, cost_per_task: 5.0, time_per_task_s: 100.0}
""",
    "strong-max": """
id: strong-max
model: Strong
effort: max
snapshot: 2026-09-23
context_window_tokens: 1000000
vision: true
items:
  alpha: {score: 0.80, cost_per_task: 10.0, time_per_task_s: 200.0}
  beta: {score: 0.80, cost_per_task: 20.0, time_per_task_s: 400.0}
  gamma: {level: H, cost_per_task: 50.0, time_per_task_s: 1000.0}
  delta: {score: null, cost_per_task: 25.0, time_per_task_s: 500.0}
""",
}

# Where each synthetic config runs. strong-max runs on two services so the many-to-many case is
# always present; a config a test adds later runs on codex (see sync_pool).
SERVICES = {
    "cheap-low": ["codex"],
    "near-cheap": ["cursor"],
    "mid-high": ["claude"],
    "strong-max": ["claude", "commandcode"],
}

SANITY = """
tasks:
  - id: s1
    label: alpha mid
    levels: {alpha: mid}
  - id: s2
    label: alpha and beta low
    levels: {alpha: low, beta: low}
"""


def sync_pool(root: Path, **overrides: dict) -> None:
    """Rewrite pool.yaml so it lists exactly the configs in models/ (every one must be listed).

    `overrides` replaces a config's entry, e.g. `sync_pool(root, **{"mid-high": {"enabled": False,
    "services": ["claude"]}})`.
    """
    configs = {}
    for path in sorted((root / "models").glob("*.yaml")):
        cid = path.stem
        configs[cid] = overrides.get(cid, {"services": SERVICES.get(cid, ["codex"])})
    (root / "pool.yaml").write_text(yaml.safe_dump({"configs": configs}), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic capability definition, catalog, pool and sanity set.

    capabilities.yaml, the catalog, pool.yaml and sanity.yaml are found through
    CAPABILITY_ROUTER_CAPABILITIES, CAPABILITY_ROUTER_MODELS, CAPABILITY_ROUTER_POOL and
    CAPABILITY_ROUTER_SANITY, all pointed at this directory.
    """
    (tmp_path / "capabilities.yaml").write_text(textwrap.dedent(CAPS), encoding="utf-8")
    (tmp_path / "models").mkdir()
    for name, body in MODELS.items():
        (tmp_path / "models" / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    (tmp_path / "sanity.yaml").write_text(textwrap.dedent(SANITY), encoding="utf-8")
    monkeypatch.setenv("CAPABILITY_ROUTER_CAPABILITIES", str(tmp_path / "capabilities.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("CAPABILITY_ROUTER_POOL", str(tmp_path / "pool.yaml"))
    monkeypatch.setenv("CAPABILITY_ROUTER_SANITY", str(tmp_path / "sanity.yaml"))
    sync_pool(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _no_real_usage(tmp_path_factory, monkeypatch):
    """`route` never fetches real usage or reads the real services settings in tests.

    The default snapshot is empty, so every service counts as on pace. A test that needs usage
    passes `--usage-file`, or sets CAPABILITY_ROUTER_SERVICES to its own settings file.
    """
    from capability_router import usage

    home = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.delenv("CAPABILITY_ROUTER_SERVICES", raising=False)
    empty = {"fetchedAt": "2026-09-23T07:48:00.000Z", "services": []}
    monkeypatch.setattr(usage, "cached_snapshot", lambda *a, **k: (empty, "fetched"))


@pytest.fixture(autouse=True)
def _isolated_delegation_log(tmp_path_factory, monkeypatch):
    """Every test writes its delegation log to a fresh tmp path, never the real one.

    The task text is off by default too, so a test that wants it must ask for it explicitly.
    """
    log = tmp_path_factory.mktemp("delegation") / "delegations.jsonl"
    monkeypatch.setenv("CAPABILITY_ROUTER_LOG", str(log))
    monkeypatch.delenv("CAPABILITY_ROUTER_LOG_TASK", raising=False)
