"""Filter by the user's thresholds, relax step by step when nobody passes, then pick by mode.

Each item's pass/fail comes from the capability definition:

- A catalog item written as a `level` (`H`/`M`/`L`/`-`) passes when it covers the required level:
  `H` reaches `high`, `M` reaches `mid`, `L` reaches `low`, and `-` only satisfies `none`.
- A catalog item written as a `score` passes when the score is at least the definition's threshold
  for that level. The definition must give `thresholds` for any item a catalog scores.
- A config with no value for a required item never passes that item.

There is no pool-relative threshold: the user's numbers are absolute, so the ladder does not move
when the catalog changes. Selection starts from the cheapest passing config rather than the best
one: a config that clears every requirement is by definition enough, and paying more only buys
margin. When nobody clears the bar the requirements are relaxed one step at a time, worst offender
first, instead of being thrown away wholesale.

Every config runs on one or more services (pool.yaml), and a service's standing comes from its
usage (availability.py). A config whose every service is exhausted does not pass. Among the passing
configs, the service tier and surplus decide first: the best-standing service that has a passing
config wins, and the mode (cheap / balanced / best / fast-balanced) then picks among that service's
passing configs. Services tied on tier and surplus are compared together. Without usage every
service stands level, so the mode alone decides.

Cost is the sum, over the items the request puts above `none`, of that item's `cost_per_task`. A
request that asks for nothing is charged for every item the definition has. Time is summed the
same way from `time_per_task_s`; only `fast-balanced` reads it. A config that lacks a value for a
required item has no comparable cost or time, so `cheap` and `balanced` skip it and say so in the
warnings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .availability import TIERS, Standing, neutral
from .config import Capabilities, ModelConfig, levels_satisfied
from .jev import AxisEstimate
from .normalize import item_cost_per_task, item_scores, item_time_per_task

MODES = ("best", "balanced", "cheap", "fast-balanced")
EPS = 1e-3
COST_TOL = 1e-9


@dataclass
class TaskMeta:
    has_image: bool = False
    input_tokens: int | None = None
    context_margin: float = 0.8  # input may use up to this fraction of the context window


@dataclass
class Candidate:
    config: ModelConfig
    item_scores: dict[str, float | None]
    passed: bool
    reasons: list[str] = field(default_factory=list)
    failed_items: tuple[str, ...] = ()
    score: float | None = None
    cost: float | None = None  # cost per task for the items this request asks for
    cost_items: dict[str, float | None] = field(default_factory=dict)
    time_per_task_s: float | None = None  # seconds per task for the same items; only `fast-balanced` reads it
    services: tuple[str | None, ...] = (None,)  # pool.yaml order
    available: tuple[str | None, ...] = (None,)  # the services that are not exhausted


@dataclass(frozen=True)
class Relaxation:
    """One step: the item whose cut-off was rejecting the most configs, lowered one level."""

    item: str
    from_level: str
    to_level: str
    rejected: int


@dataclass
class Decision:
    chosen: ModelConfig | None
    mode: str
    levels: dict[str, str]  # what the estimator asked for
    required: dict[str, str]  # what was actually applied, after any relaxation
    estimates: dict[str, AxisEstimate]
    candidates: list[Candidate]
    warnings: list[str]
    fallback: bool = False
    cost_basis: str = "requested_items"  # or "all_items" when nothing is required
    thresholds: dict[str, dict[str, float] | None] = field(default_factory=dict)
    relaxations: list[Relaxation] = field(default_factory=list)
    selection: dict = field(default_factory=dict)
    service: str | None = None
    standings: dict[str, Standing] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chosen": self.chosen.id if self.chosen else None,
            "service": self.service,
            "mode": self.mode,
            "fallback": self.fallback,
            "cost_basis": self.cost_basis,
            "cost_items_requested": [
                a for a in self.levels if self.levels.get(a, "none") != "none"
            ],
            "levels": self.levels,
            "required": self.required,
            "estimates": {
                a: {
                    "level": e.level,
                    "probabilities": e.probabilities,
                    "confidence": e.confidence,
                    "score": e.score,
                }
                for a, e in self.estimates.items()
            },
            "ranking": [
                {
                    "config": c.config.id,
                    "score": c.score,
                    "cost": c.cost,
                    "cost_items": c.cost_items,
                    "time_per_task_s": c.time_per_task_s,
                    "passed": c.passed,
                    "services": list(c.services),
                    "available_services": list(c.available),
                    "item_scores": c.item_scores,
                    "reasons": c.reasons,
                }
                for c in sorted(
                    self.candidates,
                    key=lambda c: (not c.passed, -(c.score if c.score is not None else -1)),
                )
            ],
            "thresholds": self.thresholds,
            "relaxations": [
                {"item": r.item, "from": r.from_level, "to": r.to_level, "rejected": r.rejected}
                for r in self.relaxations
            ],
            "selection": self.selection,
            "services": [
                st.to_dict()
                for st in sorted(
                    self.standings.values(), key=lambda st: (TIERS.index(st.tier), -st.surplus)
                )
            ],
            "warnings": self.warnings,
        }


def thresholds(caps: Capabilities) -> dict[str, dict[str, float] | None]:
    """The user's `thresholds` per item, or None for an item the definition leaves to `level`."""
    return {
        name: (None if item.thresholds is None else dict(item.thresholds))
        for name, item in caps.items.items()
    }


def requested_items(caps: Capabilities, levels: dict[str, str]) -> list[str]:
    """The items the request actually puts above `none`, in declaration order."""
    return [a for a in caps.items if caps.level_weight.get(levels.get(a, "none"), 0.0) > 0]


def task_cost(
    caps: Capabilities, cfg: ModelConfig, levels: dict[str, str]
) -> tuple[float | None, dict[str, float | None], float | None]:
    """Cost, per-item breakdown and total time for the items this request asks for.

    An all-`none` request has no requested items, so it is priced on every item the definition
    has. A config missing any of those items gets no cost (or time) at all rather than a partial
    sum, so it is excluded from the cost comparison instead of being compared on a made-up number.
    """
    costs = item_cost_per_task(caps, cfg)
    times = item_time_per_task(caps, cfg)
    items = requested_items(caps, levels) or list(caps.items)
    breakdown = {item: costs[item] for item in items}
    if any(v is None for v in breakdown.values()):
        total = None
    else:
        total = sum(v for v in breakdown.values())  # type: ignore[arg-type]
    values = [times[item] for item in items]
    time_total = None if any(v is None for v in values) else sum(values)  # type: ignore[arg-type]
    return total, breakdown, time_total


def metadata_filter(cfg: ModelConfig, meta: TaskMeta) -> list[str]:
    reasons: list[str] = []
    if meta.has_image and cfg.vision is False:
        reasons.append("task has image input but config has no vision")
    if meta.input_tokens is not None and cfg.context_window_tokens is not None:
        if meta.input_tokens > meta.context_margin * cfg.context_window_tokens:
            reasons.append(
                f"input ~{meta.input_tokens} tokens exceeds {meta.context_margin:.0%} of context window {cfg.context_window_tokens}"
            )
    return reasons


def geometric_mean(scores: dict[str, float | None], weights: dict[str, float]) -> float | None:
    num = 0.0
    den = 0.0
    for item, w in weights.items():
        if w <= 0:
            continue
        s = scores.get(item)
        if s is None:
            continue
        num += w * math.log(max(s, EPS))
        den += w
    if den == 0:
        return None
    return math.exp(num / den)


def ranking_weights(caps: Capabilities, levels: dict[str, str]) -> dict[str, float]:
    """Weights for the ranking mean: the level the estimator asked for. All-none ranks every item
    equally so `best` still means something."""
    weights = {a: caps.level_weight[levels.get(a, "none")] for a in caps.items}
    if all(w <= 0 for w in weights.values()):
        return {a: 1.0 for a in caps.items}
    return weights


def item_failure(caps: Capabilities, cfg: ModelConfig, item: str, level: str) -> str | None:
    """Why this config fails the required level on this item, or None when it passes."""
    if caps.level_weight[level] <= 0:
        return None
    value = cfg.value(item)
    if value is None:
        return f"{item}: no value but level {level} required"
    if value.by_level:
        if levels_satisfied(value.level, level):  # type: ignore[arg-type]
            return None
        return f"{item}: level {value.level} does not reach {level}"
    if value.score is None:
        return f"{item}: no score but level {level} required"
    need = caps.items[item].thresholds[level]  # type: ignore[index]
    if value.score < need:
        return f"{item}: {value.score:.3f} < {need:.3f} required for level {level}"
    return None


def evaluate(
    caps: Capabilities,
    models: list[ModelConfig],
    required: dict[str, str],
    weights: dict[str, float],
    meta: TaskMeta,
    levels: dict[str, str] | None = None,
) -> list[Candidate]:
    """`required` is what is applied after any relaxation; `levels` is what the task asked for.

    Cost is priced on `levels`, not on `required`: relaxing a cut-off is the router giving up on
    a requirement, not the task needing less. When `levels` is omitted, `required` stands in.
    """
    priced_levels = required if levels is None else levels
    candidates: list[Candidate] = []
    for cfg in models:
        scores = item_scores(caps, cfg)
        reasons = metadata_filter(cfg, meta)
        failed: list[str] = []
        for item in caps.items:
            why = item_failure(caps, cfg, item, required.get(item, "none"))
            if why is not None:
                reasons.append(why)
                failed.append(item)
        cand = Candidate(
            config=cfg,
            item_scores=scores,
            passed=not reasons,
            reasons=reasons,
            failed_items=tuple(failed),
        )
        cand.score = geometric_mean(scores, weights)
        cand.cost, cand.cost_items, cand.time_per_task_s = task_cost(caps, cfg, priced_levels)
        candidates.append(cand)
    if candidates and all(c.score is None for c in candidates):
        # Every weighted item is missing from every config, so the ranking has nothing to stand
        # on. Rank on all items equally instead, the same way an all-`none` request does.
        flat = {item: 1.0 for item in caps.items}
        for cand in candidates:
            cand.score = geometric_mean(cand.item_scores, flat)
    return candidates


def next_relaxation(
    caps: Capabilities, candidates: list[Candidate], required: dict[str, str]
) -> Relaxation | None:
    """The requested item whose cut-off rejects the most configs, lowered by one level."""
    ranked: list[tuple[int, int, int, str]] = []
    for order, item in enumerate(caps.items):
        level = required.get(item, "none")
        if caps.level_weight[level] <= 0:
            continue
        rejected = sum(1 for c in candidates if item in c.failed_items)
        # most rejections first, then the steepest demand, then declaration order
        ranked.append((-rejected, -caps.levels.index(level), order, item))
    if not ranked:
        return None
    neg_rejected, _, _, item = min(ranked)
    level = required[item]
    return Relaxation(
        item=item,
        from_level=level,
        to_level=caps.levels[caps.levels.index(level) - 1],
        rejected=-neg_rejected,
    )


def _cost_key(c: Candidate) -> float:
    return c.cost if c.cost is not None else math.inf


def _brief(c: Candidate) -> dict:
    return {
        "config": c.config.id,
        "cost": c.cost,
        "cost_items": c.cost_items,
        "time_per_task_s": c.time_per_task_s,
        "score": c.score,
    }


def choose(
    caps: Capabilities, candidates: list[Candidate], mode: str
) -> tuple[ModelConfig | None, list[str], dict]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    warnings: list[str] = []
    pool = [c for c in candidates if c.passed and c.score is not None]
    if not pool:
        pool = [c for c in candidates if c.score is not None]
        if not pool:
            return None, ["no config has any item data"], {"mode": mode}
        warnings.append(
            "no config passed even after relaxing every requirement; ranking all configs"
        )

    if mode == "best":
        # `best` never compares cost, so a config without one is still eligible.
        chosen = max(pool, key=lambda c: (c.score, -_cost_key(c)))
        selection = {"mode": mode, "chosen": _brief(chosen)}
        return chosen.config, warnings, selection

    priced, unpriced_warnings = _priced(pool, mode)
    warnings.extend(unpriced_warnings)
    if not priced:
        warnings.append(
            f"{mode}: no config has cost data for the requested items; falling back to the highest score"
        )
        chosen = max(pool, key=lambda c: c.score)  # type: ignore[arg-type]
        return chosen.config, warnings, {"mode": mode, "chosen": _brief(chosen)}
    if mode == "cheap":
        chosen = min(priced, key=lambda c: (_cost_key(c), -c.score))  # type: ignore[operator]
        selection = {"mode": mode, "chosen": _brief(chosen)}
    elif mode == "fast-balanced":
        chosen, selection, band_warnings = choose_fast_balanced(caps, priced)
        warnings.extend(band_warnings)
    else:
        chosen, selection, band_warnings = choose_balanced(caps, priced)
        warnings.extend(band_warnings)
    return chosen.config, warnings, selection


def _priced(pool: list[Candidate], mode: str) -> tuple[list[Candidate], list[str]]:
    """Split off the configs that have no cost for the requested items."""
    priced = [c for c in pool if c.cost is not None]
    no_cost = [c for c in pool if c.cost is None]
    warnings = []
    if no_cost:
        warnings.append(
            f"{mode}: no cost data for the requested items, excluded from the cost comparison: "
            + ", ".join(sorted(c.config.id for c in no_cost))
        )
    return priced, warnings


def choose_balanced(
    caps: Capabilities, priced: list[Candidate]
) -> tuple[Candidate, dict, list[str]]:
    """Cheapest passing config by default; trade up only inside `cost_band` and only for a
    ranking score at least `score_margin` higher. `priced` has a cost for every candidate."""
    warnings: list[str] = []
    base = min(priced, key=lambda c: (c.cost, -c.score))  # type: ignore[operator]
    budget = base.cost * caps.cost_band  # type: ignore[operator]
    contenders = [
        c
        for c in priced
        if c.cost <= budget * (1 + COST_TOL)  # type: ignore[operator]
        and c.score >= base.score + caps.score_margin  # type: ignore[operator]
    ]
    chosen = max(contenders, key=lambda c: (c.score, -c.cost)) if contenders else base  # type: ignore[operator]
    warnings.append(
        f"balanced: cheapest passing {base.config.id} (cost {base.cost:.4g},"
        f" score {base.score:.3f}); budget {budget:.4g} = cost_band {caps.cost_band:g},"
        f" score_margin {caps.score_margin:g}; {len(contenders)} config(s) qualified to trade up"
    )
    selection = {
        "mode": "balanced",
        "cheapest_passing": _brief(base),
        "chosen": _brief(chosen),
        "score_delta": chosen.score - base.score,  # type: ignore[operator]
        "cost_band": caps.cost_band,
        "score_margin": caps.score_margin,
        "budget": budget,
        "traded_up": chosen.config.id != base.config.id,
    }
    return chosen, selection, warnings


def choose_fast_balanced(
    caps: Capabilities, priced: list[Candidate]
) -> tuple[Candidate, dict, list[str]]:
    """Cheapest passing config by default; trade up only inside `time_cost_band` and only to a
    config that takes at most `time_ratio` of its time, the quickest such config. `priced` has a
    cost for every candidate, and the catalog check gives every priced config a time too."""
    base = min(priced, key=lambda c: (c.cost, -c.score))  # type: ignore[operator]
    budget = base.cost * caps.time_cost_band  # type: ignore[operator]
    limit = None if base.time_per_task_s is None else base.time_per_task_s * caps.time_ratio
    contenders = [
        c
        for c in priced
        if limit is not None
        and c.time_per_task_s is not None
        and c.cost <= budget * (1 + COST_TOL)  # type: ignore[operator]
        and c.time_per_task_s <= limit
    ]
    # the quickest; then the cheaper, then the higher score
    chosen = min(contenders, key=lambda c: (c.time_per_task_s, c.cost, -c.score)) if contenders else base  # type: ignore[operator]
    warnings = [
        f"fast-balanced: cheapest passing {base.config.id} (cost {base.cost:.4g},"
        f" time {base.time_per_task_s}); budget {budget:.4g} = time_cost_band {caps.time_cost_band:g},"
        f" time limit {limit} = time_ratio {caps.time_ratio:g}; {len(contenders)} config(s) qualified to trade up"
    ]
    selection = {
        "mode": "fast-balanced",
        "cheapest_passing": _brief(base),
        "chosen": _brief(chosen),
        "time_cost_band": caps.time_cost_band,
        "time_ratio": caps.time_ratio,
        "budget": budget,
        "time_limit": limit,
        "traded_up": chosen.config.id != base.config.id,
    }
    return chosen, selection, warnings


def _apply_services(
    candidates: list[Candidate],
    services: dict[str, tuple[str, ...]] | None,
    standings: dict[str, Standing],
) -> None:
    """Record each config's services, and fail the ones whose every service is exhausted."""
    for cand in candidates:
        svc: tuple[str | None, ...] = tuple(services[cand.config.id]) if services else (None,)
        cand.services = svc
        cand.available = tuple(s for s in svc if _standing(standings, s).tier != "exhausted")
        if not cand.available:
            why = "; ".join(f"{s}: {_standing(standings, s).reason}" for s in svc)
            cand.reasons.append(f"no service left ({why})")
            cand.passed = False


def _standing(standings: dict[str, Standing], service: str | None) -> Standing:
    return standings.get(service) if service in standings else neutral(service)  # type: ignore[return-value]


def _choose_by_service(
    caps: Capabilities,
    candidates: list[Candidate],
    standings: dict[str, Standing],
    mode: str,
) -> tuple[ModelConfig | None, str | None, list[str], dict]:
    """The best-standing service with an eligible config, then the mode inside it."""
    eligible = [c for c in candidates if c.passed] or [c for c in candidates if c.available]
    if not eligible:
        return None, None, ["every service of every config is exhausted"], {"mode": mode}
    keys = sorted({_standing(standings, s).rank_key for c in eligible for s in c.available})
    warnings: list[str] = []
    for key in keys:
        group = [c for c in eligible if any(_standing(standings, s).rank_key == key for s in c.available)]
        chosen, choose_warnings, selection = choose(caps, group, mode)
        if chosen is None:
            warnings.extend(choose_warnings)
            continue
        cand = next(c for c in group if c.config.id == chosen.id)
        service = next(s for s in cand.available if _standing(standings, s).rank_key == key)
        standing = _standing(standings, service)
        selection["service"] = {
            "chosen": service,
            "tier": standing.tier,
            "surplus": round(standing.surplus, 1),
            "tied_services": sorted(
                {s for c in group for s in c.available if _standing(standings, s).rank_key == key},
                key=str,
            ),
        }
        return chosen, service, warnings + choose_warnings, selection
    return None, None, warnings, {"mode": mode}


def route(
    caps: Capabilities,
    models: list[ModelConfig],
    estimates: dict[str, AxisEstimate],
    meta: TaskMeta,
    mode: str = "balanced",
    services: dict[str, tuple[str, ...]] | None = None,
    standings: dict[str, Standing] | None = None,
) -> Decision:
    """`services` maps each config to the services it runs on (pool.yaml) and `standings` holds
    each service's usage standing. Without them every config runs on one anonymous service."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    standings = dict(standings or {})
    if services:
        for svc in services.values():
            for sid in svc:
                standings.setdefault(sid, neutral(sid))
    levels = {a: e.level for a, e in estimates.items()}
    required = {a: levels.get(a, "none") for a in caps.items}
    weights = ranking_weights(caps, levels)
    warnings: list[str] = []
    relaxations: list[Relaxation] = []
    while True:
        candidates = evaluate(caps, models, required, weights, meta, levels)
        _apply_services(candidates, services, standings)
        if any(c.passed for c in candidates):
            break
        if not any(c.available for c in candidates):
            break  # usage, not the requirements, is what rejects everyone
        step = next_relaxation(caps, candidates, required)
        if step is None:
            break
        required[step.item] = step.to_level
        relaxations.append(step)
        warnings.append(
            f"no config passed; relaxed {step.item} {step.from_level} -> {step.to_level}"
            f" (it was rejecting {step.rejected} config(s))"
        )
    chosen, service, choose_warnings, selection = _choose_by_service(caps, candidates, standings, mode)
    return Decision(
        chosen=chosen,
        mode=mode,
        levels=levels,
        required=required,
        estimates=estimates,
        candidates=candidates,
        warnings=warnings + choose_warnings,
        fallback=bool(relaxations),
        cost_basis="requested_items" if requested_items(caps, levels) else "all_items",
        thresholds=thresholds(caps),
        relaxations=relaxations,
        selection=selection,
        service=service,
        standings=standings,
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate good enough for a context-window sanity filter."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other = len(text) - ascii_chars
    return int(ascii_chars / 4 + other / 1.5) + 1
