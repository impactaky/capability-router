#!/usr/bin/env python3
"""Propose `thresholds` from the best score at each item, when an item has no anchor problems.

For an item you measure with a `score` instead of a `level`, the thresholds are the pass marks a
score is read against. This script is the placeholder path in docs/tutorial.md: point it at your
catalog directory, your capability definition and the number of problems behind each item's
score, and it prints a `thresholds:` block per item to paste under `items.<item>`.

Rule, with `best` the highest numeric `score` for the item across the catalog and `n` the number
of problems:

    low  = best / 3
    high = best - 2 * sqrt(best * (1 - best) / n)
    mid  = (low + high) / 2
    high < low  ->  high = mid = low

When `--tasks` gives no `n` for an item, `high = best * 0.9` is used. A standard error from about
ten problems is large, so `high` lands close to `low` and the whole ladder is conservative: treat
these as placeholders and confirm them with `capability-router sanity` before trusting them.

Items whose catalog has no numeric `score` are skipped with a comment.

    python examples/thresholds.py examples/models examples/capabilities.yaml --tasks coding=10
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import yaml


def parse_tasks(spec: str | None) -> dict[str, int]:
    """`coding=10,long_context=10` to `{coding: 10, long_context: 10}`."""
    out: dict[str, int] = {}
    for entry in (spec or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"bad --tasks entry {entry!r}; expected <item>=<count>")
        item, count = entry.split("=", 1)
        try:
            value = int(count)
        except ValueError:
            raise ValueError(f"bad --tasks count for {item.strip()!r}: {count!r}") from None
        if value <= 0:
            raise ValueError(f"--tasks count for {item.strip()!r} must be positive, got {value}")
        out[item.strip()] = value
    return out


def best_scores(catalog_dir: Path) -> dict[str, float]:
    """The highest numeric `score` per item across every catalog file."""
    best: dict[str, float] = {}
    for path in sorted(catalog_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item, spec in (data.get("items") or {}).items():
            score = (spec or {}).get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            best[item] = max(best.get(item, float(score)), float(score))
    return best


def propose(best: float, tasks: int | None = None) -> dict[str, float]:
    """The `low`/`mid`/`high` thresholds for one item's best score."""
    low = best / 3
    if tasks:
        high = best - 2 * math.sqrt(best * (1 - best) / tasks)
    else:
        high = best * 0.9
    if high < low:
        high = low
    return {"low": low, "mid": (low + high) / 2, "high": high}


def render(items: list[str], proposals: dict[str, dict[str, float]]) -> str:
    lines: list[str] = []
    for item in items:
        if item not in proposals:
            lines.append(f"# {item}: no numeric score in the catalog, skipped")
            continue
        values = proposals[item]
        formatted = ", ".join(f"{key}: {values[key]:.3f}" for key in ("low", "mid", "high"))
        lines.append(f"# {item}")
        lines.append(f"thresholds: {{{formatted}}}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _definition_items(path: Path) -> list[str]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict) or not items:
        raise ValueError(f"{path}: `items` must be a non-empty mapping")
    return list(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalog", type=Path, help="catalog directory of <config>.yaml files")
    parser.add_argument("capabilities", type=Path, help="capability definition yaml")
    parser.add_argument("--tasks", help="problem count per item, e.g. coding=10,long_context=10")
    args = parser.parse_args(argv)
    try:
        tasks = parse_tasks(args.tasks)
        items = _definition_items(args.capabilities)
        unknown = sorted(set(tasks) - set(items))
        if unknown:
            raise ValueError(f"--tasks names items not in the definition: {unknown}")
        best = best_scores(args.catalog)
        proposals = {item: propose(best[item], tasks.get(item)) for item in items if item in best}
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(render(items, proposals))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
