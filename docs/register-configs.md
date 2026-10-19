# Register configs

Write a catalog file for each config (a model and reasoning effort pair), and list its services in `pool.yaml`.

## Prerequisites

- Your own `capabilities.yaml` ([define capability items](define-items.md))
- A way to have each model solve the anchor problems

## Steps

1. These commands create a catalog file for config `big-high` and a `pool.yaml` listing its service (choose item values as described in [set item values](#values)).
   ```sh
   m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"; mkdir -p "$m"
   echo '{id: big-high, model: Big Model, effort: high, items: {sql: {level: H, cost_per_task: 3, time_per_task_s: 60}}}' > "$m/big-high.yaml"
   echo '{configs: {big-high: {services: [claude]}}}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/pool.yaml"
   ```
2. Check the registered configs.
   ```sh
   capability-router models
   ```
   Each enabled config has one line showing its item levels (`H`/`M`/`L`/`-`), total cost and time, and services.

<a id="values"></a>
## Set item values

- With anchor pass rates for each level: write `level: H`/`M`/`L`/`'-'`. Run `python examples/levels_from_anchors.py anchor-results.yaml --pass-rate 0.5` to print the `level` lines.
- With a number in 0..1 per item (accuracy on a problem set or benchmark): write `score: 0.62` and `thresholds` for that item in `capabilities.yaml`. Run `python examples/thresholds.py <catalog> <capabilities.yaml> --tasks sql=10` to print placeholder `thresholds`.
- Without cost or time measurements yet: give every config the same `cost_per_task` and `time_per_task_s`.
