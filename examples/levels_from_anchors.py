#!/usr/bin/env python3
"""Propose catalog `level` values from per-level anchor pass rates.

This is the second half of the tutorial's anchor workflow (docs/tutorial.md). For one item, write
a handful of anchor problems, tag each as `low`, `mid` or `high`, and have every config solve all
of them. Record the share each config solved at each level in a yaml shaped like
examples/anchor-results.yaml:

    example-large:
      coding: {low: 1.0, mid: 0.75, high: 0.5}

Run this script on that file. It looks from `low` upward and takes the highest level whose pass
rate is at least `--pass-rate` (default 0.5) and whose lower levels are also at least that high.
If `low` is below the pass rate the config does not even clear `low`, so its level is `-`. The
script prints the `items.<item>.level` lines to paste into that config's catalog file; it never
rewrites a file. A rate for a level that is absent ends the ladder there.

    python examples/levels_from_anchors.py examples/anchor-results.yaml --pass-rate 0.5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

LEVEL_LETTERS = (("low", "L"), ("mid", "M"), ("high", "H"))


def propose_level(rates: dict[str, Any], pass_rate: float = 0.5) -> str:
    """The highest level reached before the first below `pass_rate`, or `-` below `low`."""
    level = "-"
    for name, letter in LEVEL_LETTERS:
        if name not in rates:
            break
        if float(rates[name]) >= pass_rate:
            level = letter
        else:
            break
    return level


def levels_from(anchor_results: dict[str, Any], pass_rate: float = 0.5) -> dict[str, dict[str, str]]:
    """config -> item -> proposed level, in the order of the input."""
    return {
        config: {item: propose_level(rates, pass_rate) for item, rates in items.items()}
        for config, items in anchor_results.items()
    }


def render(levels: dict[str, dict[str, str]]) -> str:
    """The pasteable yaml: one `items:` block per config, with a comment naming the config."""
    lines: list[str] = []
    for config, items in levels.items():
        lines.append(f"# {config}")
        lines.append("items:")
        for item, level in items.items():
            value = f"'{level}'" if level == "-" else level
            lines.append(f"  {item}: {{level: {value}}}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("anchor_results", type=Path, help="yaml of <config>: {<item>: {low, mid, high}}")
    parser.add_argument("--pass-rate", type=float, default=0.5, help="level pass rate (default 0.5)")
    args = parser.parse_args(argv)
    data = yaml.safe_load(args.anchor_results.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(f"error: {args.anchor_results}: must be a mapping of config to items", file=sys.stderr)
        return 2
    sys.stdout.write(render(levels_from(data, args.pass_rate)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
