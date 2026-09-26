"""Load the capability definition, the item-unit catalog and pool.yaml.

Router logic never references a model by name: everything model-specific lives in the catalog
(one yaml per config), everything item-specific in the user's capability definition.

The capability definition is user-defined: the items, what each measures and excludes, the
meaning of every level, optional anchor `examples`, optional per-item `thresholds`, and the
routing parameters. It is read from `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml`,
or from `$CAPABILITY_ROUTER_CAPABILITIES` when that is set. The repository ships no items.

The catalog is what each config can do, one item at a time: a `score` (0..1) or a `level`
(`H`/`M`/`L`/`-`) plus a `cost_per_task` and a `time_per_task_s`. It is read from
`${XDG_STATE_HOME:-~/.local/state}/capability-router/models/`, or from `$CAPABILITY_ROUTER_MODELS`.
pool.yaml says which catalog configs are enabled and which services each one runs on. It is read
from `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml`, or from `$CAPABILITY_ROUTER_POOL`.
Only enabled configs make up the pool, so every routing command sees the pool, never the whole
catalog.

The sanity set is user-defined too and read from
`${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml`, or from `$CAPABILITY_ROUTER_SANITY`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

# The level ladder. The definition may write `levels` but it must be exactly this.
LEVELS = ("none", "low", "mid", "high")
# The level symbols a catalog item may carry, and the rank each one satisfies.
CATALOG_LEVELS = ("H", "M", "L", "-")
_LEVEL_RANK = {"none": 0, "low": 1, "mid": 2, "high": 3}
_CATALOG_RANK = {"H": 3, "M": 2, "L": 1, "-": 0}
# A catalog `level` is put on the score scale with the item's `thresholds` when it has them,
# otherwise with these fixed midpoints (see docs/spec.md).
FALLBACK_LEVEL_SCORE = {"H": 1.0, "M": 2 / 3, "L": 1 / 3, "-": 0.0}
DEFAULT_LEVEL_WEIGHT = {"none": 0.0, "low": 1.0, "mid": 2.0, "high": 3.0}

_ITEM_KEYS = {"measures", "excludes", "levels", "examples", "question", "thresholds"}
_THRESHOLD_KEYS = ("low", "mid", "high")
_EXAMPLE_LEVELS = ("low", "mid", "high")
_OLD_CAPABILITY_KEYS = (
    "axes",
    "benchmarks",
    "thresholds",
    "level_weight",
    "cost_band",
    "score_margin",
    "time_cost_band",
    "time_ratio",
    "level_threshold",
    "high_ratio",
    "mid_ratio",
)
_OLD_CATALOG_KEYS = (
    "benchmarks",
    "evaluations",
    "cost",
    "performance",
    "tasks",
    "source",
    "notes",
)
_CATALOG_KEYS = {"id", "model", "effort", "snapshot", "context_window_tokens", "vision", "items"}


@dataclass(frozen=True)
class Item:
    """One capability item: what it measures, its levels, anchors and optional thresholds."""

    name: str
    measures: str
    excludes: str
    levels: dict[str, str]
    examples: dict[str, tuple[str, ...]]
    question: str | None
    thresholds: dict[str, float] | None

    def question_text(self) -> str:
        """The Jev instructions: the explicit `question`, or one built from `measures`."""
        if self.question:
            return self.question
        return (
            "How much does this task require the following capability: "
            f"{self.measures} Choose the lowest level that is sufficient."
        )

    def criteria_for(self, level: str) -> str:
        """The level description, with ` Examples: <a>; <b>.` when the level has anchors."""
        text = self.levels[level]
        anchors = self.examples.get(level)
        if anchors:
            text += " Examples: " + "; ".join(anchors) + "."
        return text

    def score_for_level(self, level: str) -> float:
        """The score a catalog `level` stands for: this item's threshold, else the fixed midpoint."""
        if self.thresholds is not None and level != "-":
            return self.thresholds[{"H": "high", "M": "mid", "L": "low"}[level]]
        return FALLBACK_LEVEL_SCORE[level]


@dataclass(frozen=True)
class Capabilities:
    version: int
    levels: tuple[str, ...]
    items: dict[str, Item]
    level_weight: dict[str, float]
    cost_band: float
    score_margin: float
    time_cost_band: float
    time_ratio: float
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ItemValue:
    """One config's value for one item. Exactly one of `score`/`level` is set, `score` may be None."""

    score: float | None
    level: str | None
    cost_per_task: float
    time_per_task_s: float

    @property
    def by_level(self) -> bool:
        return self.level is not None


@dataclass(frozen=True)
class ModelConfig:
    id: str
    model: str
    effort: str
    snapshot: str
    items: dict[str, ItemValue]
    context_window_tokens: int | None
    vision: bool | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    def value(self, item: str) -> ItemValue | None:
        return self.items.get(item)


def capabilities_path(env: Mapping[str, str] | None = None) -> Path:
    """The capability definition: `$CAPABILITY_ROUTER_CAPABILITIES`, else the XDG config default."""
    env = os.environ if env is None else env
    if env.get("CAPABILITY_ROUTER_CAPABILITIES"):
        return Path(env["CAPABILITY_ROUTER_CAPABILITIES"])
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / "capability-router" / "capabilities.yaml"


def sanity_path(env: Mapping[str, str] | None = None) -> Path:
    """The sanity set: `$CAPABILITY_ROUTER_SANITY`, else the XDG config default."""
    env = os.environ if env is None else env
    if env.get("CAPABILITY_ROUTER_SANITY"):
        return Path(env["CAPABILITY_ROUTER_SANITY"])
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / "capability-router" / "sanity.yaml"


def criteria_path(caps_path: Path) -> Path:
    """`criteria.md` beside the capability definition, the default `criteria` output."""
    return caps_path.with_name("criteria.md")


def load_sanity(path: Path) -> dict[str, Any]:
    """The sanity set (`tasks: [...]`), or a missing-file error naming the path and the env."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(
            f"sanity not found: {path}. Put your sanity set at "
            "${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml "
            "or set CAPABILITY_ROUTER_SANITY to that file."
        ) from None
    return yaml.safe_load(text)


def models_dir(env: Mapping[str, str] | None = None) -> Path:
    """Catalog directory: `$CAPABILITY_ROUTER_MODELS`, else the XDG state default."""
    env = os.environ if env is None else env
    if env.get("CAPABILITY_ROUTER_MODELS"):
        return Path(env["CAPABILITY_ROUTER_MODELS"])
    state = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".local" / "state")
    return Path(state) / "capability-router" / "models"


def pool_path(env: Mapping[str, str] | None = None) -> Path:
    """pool.yaml: `$CAPABILITY_ROUTER_POOL`, else the XDG config default."""
    env = os.environ if env is None else env
    if env.get("CAPABILITY_ROUTER_POOL"):
        return Path(env["CAPABILITY_ROUTER_POOL"])
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / "capability-router" / "pool.yaml"


def _missing_capabilities(path: Path) -> ValueError:
    return ValueError(
        f"capabilities not found: {path}. "
        "Put your capability definition at "
        "${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml "
        "or set CAPABILITY_ROUTER_CAPABILITIES to that file. "
        "See examples/capabilities.template.yaml for the format."
    )


def _missing_catalog(path: Path) -> ValueError:
    return ValueError(
        f"catalog not found: {path}. "
        "Put model configs in ${XDG_STATE_HOME:-~/.local/state}/capability-router/models/ "
        "or set CAPABILITY_ROUTER_MODELS to that directory."
    )


def _missing_pool(path: Path) -> ValueError:
    return ValueError(
        f"pool.yaml not found: {path}. "
        "Put pool.yaml at ${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml "
        "or set CAPABILITY_ROUTER_POOL to that file."
    )


def load_capabilities(path: Path) -> Capabilities:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _missing_capabilities(path) from None
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: capability definition must be a mapping")
    _reject_old_capability_keys(data, path)

    version = data.get("version", 3)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"{path}: `version` must be an integer, got {version!r}")
    if version != 3:
        raise ValueError(f"{path}: unsupported capability version {version}; this build reads version 3")

    levels = data.get("levels", list(LEVELS))
    if tuple(levels) != LEVELS:
        raise ValueError(f"{path}: `levels` must be exactly {list(LEVELS)}, got {levels!r}")

    items_spec = data.get("items")
    if not isinstance(items_spec, dict) or not items_spec:
        raise ValueError(f"{path}: `items` must be a non-empty mapping of item name to its definition")
    items = {name: _load_item(path, name, spec) for name, spec in items_spec.items()}

    unknown = sorted(set(data) - {"version", "levels", "items", "routing"})
    if unknown:
        raise ValueError(f"{path}: unknown keys {unknown}; the item definition and routing parameters go under `items` and `routing`")
    routing = _load_routing_spec(path, data.get("routing") or {})

    return Capabilities(
        version=version,
        levels=LEVELS,
        items=items,
        raw=data,
        **routing,
    )


def _reject_old_capability_keys(data: dict[str, Any], path: Path) -> None:
    old = [key for key in _OLD_CAPABILITY_KEYS if key in data]
    if old:
        raise ValueError(
            f"{path}: unsupported old capability keys {old}; "
            "define each item under `items` with `measures`, `excludes`, `levels` and optional "
            "`examples`, `question`, `thresholds`, and put routing parameters under `routing`"
        )


def _load_item(path: Path, name: str, spec: Any) -> Item:
    where = f"{path}: item {name!r}"
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: must be a mapping")
    extra = sorted(set(spec) - _ITEM_KEYS)
    if extra:
        raise ValueError(f"{where}: unknown keys {extra}")
    measures = _required_text(spec.get("measures"), f"{where}: `measures`")
    excludes = _required_text(spec.get("excludes"), f"{where}: `excludes`")
    levels = _load_levels(where, spec.get("levels"))
    examples = _load_examples(where, spec.get("examples"))
    question = spec.get("question")
    if question is not None:
        question = _required_text(question, f"{where}: `question`")
    thresholds = _load_thresholds(where, spec.get("thresholds"))
    return Item(
        name=name,
        measures=measures,
        excludes=excludes,
        levels=levels,
        examples=examples,
        question=question,
        thresholds=thresholds,
    )


def _load_levels(where: str, spec: Any) -> dict[str, str]:
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: `levels` must be a mapping with all of {list(LEVELS)}")
    missing = [lv for lv in LEVELS if lv not in spec]
    extra = sorted(set(spec) - set(LEVELS))
    if missing or extra:
        raise ValueError(f"{where}: `levels` must have exactly {list(LEVELS)}; missing {missing}, unknown {extra}")
    return {lv: _required_text(spec[lv], f"{where}: levels.{lv}") for lv in LEVELS}


def _load_examples(where: str, spec: Any) -> dict[str, tuple[str, ...]]:
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: `examples` must be a mapping of low/mid/high to a list")
    extra = sorted(set(spec) - set(_EXAMPLE_LEVELS))
    if extra:
        raise ValueError(f"{where}: `examples` may only key {list(_EXAMPLE_LEVELS)}, got {extra}")
    examples: dict[str, tuple[str, ...]] = {}
    for lv, values in spec.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"{where}: examples.{lv} must be a non-empty list of strings")
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{where}: examples.{lv} entries must be non-empty strings")
        examples[lv] = tuple(values)
    return examples


def _load_thresholds(where: str, spec: Any) -> dict[str, float] | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: `thresholds` must be a mapping of low/mid/high")
    extra = sorted(set(spec) - set(_THRESHOLD_KEYS))
    missing = [k for k in _THRESHOLD_KEYS if k not in spec]
    if missing or extra:
        raise ValueError(f"{where}: `thresholds` must have exactly {list(_THRESHOLD_KEYS)}; missing {missing}, unknown {extra}")
    values: dict[str, float] = {}
    for key in _THRESHOLD_KEYS:
        value = spec[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where}: thresholds.{key} must be a number, got {value!r}")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{where}: thresholds.{key} must be between 0 and 1, got {value!r}")
        values[key] = float(value)
    if not (values["low"] <= values["mid"] <= values["high"]):
        raise ValueError(
            f"{where}: thresholds must satisfy low <= mid <= high, got {values!r}"
        )
    return values


def _load_routing_spec(path: Path, spec: Any) -> dict[str, Any]:
    where = f"{path}: routing"
    if not isinstance(spec, dict):
        raise ValueError(f"{where} must be a mapping")
    extra = sorted(set(spec) - {"level_weight", "cost_band", "score_margin", "time_cost_band", "time_ratio"})
    if extra:
        raise ValueError(f"{where}: unknown keys {extra}")
    return {
        "level_weight": _load_level_weight(where, spec.get("level_weight")),
        "cost_band": _positive_number(spec.get("cost_band", 1.25), f"{where}: cost_band"),
        "score_margin": _non_negative_number(spec.get("score_margin", 0.05), f"{where}: score_margin"),
        "time_cost_band": _positive_number(spec.get("time_cost_band", 2.5), f"{where}: time_cost_band"),
        "time_ratio": _positive_number(spec.get("time_ratio", 0.5), f"{where}: time_ratio"),
    }


def _load_level_weight(where: str, spec: Any) -> dict[str, float]:
    if spec is None:
        return dict(DEFAULT_LEVEL_WEIGHT)
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: level_weight must be a mapping of {list(LEVELS)}")
    extra = sorted(set(spec) - set(LEVELS))
    missing = [lv for lv in LEVELS if lv not in spec]
    if missing or extra:
        raise ValueError(f"{where}: level_weight must have exactly {list(LEVELS)}; missing {missing}, unknown {extra}")
    return {lv: _non_negative_number(spec[lv], f"{where}: level_weight.{lv}") for lv in LEVELS}


def load_model(path: Path) -> ModelConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: catalog config must be a mapping")
    old = [key for key in _OLD_CATALOG_KEYS if key in data]
    if old:
        raise ValueError(
            f"{path}: unsupported old catalog keys {old}; put each item under `items` as "
            "`{score: ...}` or `{level: H|M|L|-}` plus `cost_per_task` and `time_per_task_s`"
        )
    unknown = sorted(set(data) - _CATALOG_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown keys {unknown}")

    config_id = _required_text(data.get("id"), f"{path}: `id`")
    model = _required_text(data.get("model"), f"{path}: `model`")
    items_spec = data.get("items")
    if not isinstance(items_spec, dict) or not items_spec:
        raise ValueError(f"{path}: `items` must be a non-empty mapping of item name to its value")
    items = {name: _load_item_value(path, config_id, name, spec) for name, spec in items_spec.items()}

    return ModelConfig(
        id=config_id,
        model=model,
        effort=str(data.get("effort", "")),
        snapshot=str(data.get("snapshot", "")),
        items=items,
        context_window_tokens=_opt_int(data.get("context_window_tokens")),
        vision=data.get("vision"),
        raw=data,
    )


def _load_item_value(path: Path, config_id: str, name: str, spec: Any) -> ItemValue:
    where = f"{path}: config {config_id!r} item {name!r}"
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: must be a mapping")
    extra = sorted(set(spec) - {"score", "level", "cost_per_task", "time_per_task_s"})
    if extra:
        raise ValueError(f"{where}: unknown keys {extra}")
    has_score, has_level = "score" in spec, "level" in spec
    if has_score == has_level:
        raise ValueError(f"{where}: give exactly one of `score` or `level`")
    score = spec.get("score")
    level = spec.get("level")
    if has_score:
        score = _opt_score(score, where)
    else:
        if level not in CATALOG_LEVELS:
            raise ValueError(f"{where}: unknown level {level!r}; expected one of {list(CATALOG_LEVELS)}")
    if "cost_per_task" not in spec:
        raise ValueError(f"{where}: missing cost_per_task")
    if "time_per_task_s" not in spec:
        raise ValueError(f"{where}: missing time_per_task_s")
    return ItemValue(
        score=score,
        level=level if has_level else None,
        cost_per_task=_non_negative_number(spec["cost_per_task"], f"{where}: cost_per_task"),
        time_per_task_s=_non_negative_number(spec["time_per_task_s"], f"{where}: time_per_task_s"),
    )


def load_models(catalog: Path) -> list[ModelConfig]:
    configs = [load_model(p) for p in sorted(catalog.glob("*.yaml"))]
    ids = [c.id for c in configs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate config ids: {sorted(dupes)}")
    return configs


def validate_catalog(caps: Capabilities, configs: list[ModelConfig]) -> None:
    """Checks that hold for the definition and any catalog it is read against.

    Every catalog item must be defined, and an item any config scores must carry thresholds,
    because a score is only a pass/fail decision against them. Errors name the config and item.
    """
    scored: list[str] = []
    for cfg in configs:
        for name, value in cfg.items.items():
            if name not in caps.items:
                raise ValueError(
                    f"{cfg.id}: item {name!r} is not in the capability definition "
                    f"({', '.join(caps.items)})"
                )
            if not value.by_level and name not in scored:
                scored.append(name)
    for name in scored:
        if caps.items[name].thresholds is None:
            raise ValueError(
                f"{name}: catalog configs score this item but the definition has no "
                "`thresholds` for it; add `thresholds` or use `level` in the catalog"
            )


def levels_satisfied(catalog_level: str, required: str) -> bool:
    """Whether a catalog level covers a required level (`H` reaches `high`, `-` reaches `none`)."""
    return _CATALOG_RANK[catalog_level] >= _LEVEL_RANK[required]


@dataclass(frozen=True)
class PoolEntry:
    config: str
    services: tuple[str, ...]  # in the order pool.yaml lists them; the first wins a tie
    enabled: bool


def load_pool(path: Path, catalog_ids: list[str], known_services: tuple[str, ...]) -> dict[str, PoolEntry]:
    """pool.yaml: `configs: {<config-id>: {services: [...], enabled: true}}`.

    Every catalog config must be listed, so leaving one out never disables it silently. An id
    that is not in the catalog, a service `usage` does not know, an empty or repeated service
    list, and any other key are errors. `enabled` defaults to true.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise _missing_pool(path) from None
    configs = data.get("configs") if isinstance(data, dict) else None
    if not isinstance(configs, dict):
        raise ValueError(f"{path.name}: `configs` must be a mapping of config id to its entry")
    unknown = sorted(set(configs) - set(catalog_ids))
    if unknown:
        raise ValueError(f"{path.name}: configs not in models/: {unknown}")
    missing = [c for c in catalog_ids if c not in configs]
    if missing:
        raise ValueError(f"{path.name}: configs in models/ but not listed: {missing}")
    pool: dict[str, PoolEntry] = {}
    for cid in catalog_ids:
        spec = configs[cid]
        where = f"{path.name}: {cid}"
        if not isinstance(spec, dict):
            raise ValueError(f"{where}: entry must be a mapping with `services`")
        extra = sorted(set(spec) - {"services", "enabled"})
        if extra:
            raise ValueError(f"{where}: unknown keys {extra}")
        services = spec.get("services")
        if not isinstance(services, list) or not services:
            raise ValueError(f"{where}: `services` must be a non-empty list (use `enabled: false` to disable)")
        bad = [s for s in services if s not in known_services]
        if bad:
            raise ValueError(f"{where}: unknown services {bad}; expected some of {list(known_services)}")
        if len(set(services)) != len(services):
            raise ValueError(f"{where}: a service is listed twice")
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{where}: `enabled` must be true or false")
        pool[cid] = PoolEntry(config=cid, services=tuple(services), enabled=enabled)
    return pool


def load_routing() -> tuple[Capabilities, list[ModelConfig], dict[str, tuple[str, ...]]]:
    """The definition, the pool (enabled configs, catalog order) and each one's services."""
    from .usage import SERVICE_IDS  # the only module that names the services

    caps_file = capabilities_path()
    if not caps_file.is_file():
        raise _missing_capabilities(caps_file)
    caps = load_capabilities(caps_file)
    catalog_dir = models_dir()
    if not catalog_dir.is_dir():
        raise _missing_catalog(catalog_dir)
    catalog = load_models(catalog_dir)
    validate_catalog(caps, catalog)
    pool_file = pool_path()
    if not pool_file.is_file():
        raise _missing_pool(pool_file)
    pool = load_pool(pool_file, [c.id for c in catalog], SERVICE_IDS)
    models = [c for c in catalog if pool[c.id].enabled]
    return caps, models, {c.id: pool[c.id].services for c in models}


def load_all() -> tuple[Capabilities, list[ModelConfig]]:
    """The definition and the pool (the enabled configs of the catalog)."""
    caps, models, _ = load_routing()
    return caps, models


def _required_text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _non_negative_number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number, got {value!r}")
    if float(value) < 0:
        raise ValueError(f"{what} must be 0 or more, got {value!r}")
    return float(value)


def _positive_number(value: Any, what: str) -> float:
    result = _non_negative_number(value, what)
    if result <= 0:
        raise ValueError(f"{what} must be greater than 0, got {value!r}")
    return result


def _opt_score(value: Any, where: str) -> float | None:
    if value is None:
        return None
    score = _non_negative_number(value, f"{where}: score")
    if score > 1.0:
        raise ValueError(f"{where}: score must be between 0 and 1, got {value!r}")
    return score


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValueError(f"expected a positive integer, got {v!r}")
    return v
