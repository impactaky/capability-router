"""Resolve each config's items to numbers: a score per item and cost/time per item.

A catalog item carries either a `score` (0..1, or null) or a `level` (`H`/`M`/`L`/`-`). A level
is put on the item's score scale with the definition's `thresholds` when it defines them, and with
the fixed midpoints `H`=1.0, `M`=2/3, `L`=1/3, `-`=0 when it does not. An item a config does not
carry has no score and cannot satisfy a requirement on it.

A score is absolute: it does not move when the catalog or pool changes, so the user's thresholds
keep their meaning. Nothing here names an item or a model.
"""

from __future__ import annotations

from .config import Capabilities, ModelConfig


def item_scores(caps: Capabilities, cfg: ModelConfig) -> dict[str, float | None]:
    """The score of every item in the definition, or None when the config has no value for it."""
    out: dict[str, float | None] = {}
    for name, item in caps.items.items():
        value = cfg.value(name)
        if value is None:
            out[name] = None
        elif value.by_level:
            out[name] = item.score_for_level(value.level)  # type: ignore[arg-type]
        else:
            out[name] = value.score
    return out


def item_cost_per_task(caps: Capabilities, cfg: ModelConfig) -> dict[str, float | None]:
    """Cost per task for every item, or None when the config has no value for it."""
    return {name: (cfg.value(name).cost_per_task if cfg.value(name) else None) for name in caps.items}


def item_time_per_task(caps: Capabilities, cfg: ModelConfig) -> dict[str, float | None]:
    """Seconds per task for every item, or None when the config has no value for it."""
    return {name: (cfg.value(name).time_per_task_s if cfg.value(name) else None) for name in caps.items}
