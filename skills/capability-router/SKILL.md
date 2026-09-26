---
name: capability-router
description: Route one or more task delegations to an LLM model and reasoning effort config. The caller estimates a level for every item in the capability definition and passes --levels. The CLI applies the user's thresholds, selects an available service by usage, and returns a config ID and service ID. It does not invoke a model.
---

# capability-router

Place this directory in your agent's skills directory. The capability definition and its generated `criteria.md` are yours; prepare them with the repository's [setup guide](../../docs/setup.md) and [tutorial](../../docs/tutorial.md).

Use `capability-router` if it is on PATH. Otherwise run `uv run --project <repo> capability-router`.

```sh
capability-router route --levels "$LEVELS" --mode balanced "task text"
```

Stdout is one line: `<config id> <service id>`. The service is `codex`, `claude`, `cursor`, or `commandcode`. This skill does not invoke the model. Look up the returned config ID in the catalog and pass its `model` and `effort` to the selected service's launch options. The fictional `examples/models/example-small.yaml`, for example, maps `example-small codex` to model `Example Small` and effort `low`. Launch options depend on the service.

Use `--no-usage` to ignore usage. A service whose usage cannot be fetched is treated as `normal` with zero surplus.

## How do I estimate requirements?

The calling LLM estimates the task's levels itself. **Always pass every item in the capability definition to `--levels`, including `none`.** Omitting `--levels` makes the CLI use a different estimator.

1. **Read the generated criteria.** Open `criteria.md`, which sits beside your capability definition. The definition is `$CAPABILITY_ROUTER_CAPABILITIES` when that is set, otherwise `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml`. If `criteria.md` is missing or out of date, run `capability-router criteria` once to (re)generate it. If you have already read it in this session, do not read it again.
2. **Rate every item.** Work through each item in `criteria.md`, choose the lowest sufficient level based on the deliverable, and do not count the task instructions, order, or acceptance criteria themselves. A level means the task is about as demanding as that level's examples when the item gives them.
3. **Keep scores out of the estimate.** Do not inspect the catalog or any `capability-router models` output before finishing, including `--detail`, which prints the numeric scores. Otherwise the config scores can bias the required levels.
4. **Build one `--levels` value.** Join `item=level` pairs with commas. Levels are `none`, `low`, `mid`, and `high`. Include every item from the definition, as here:

```
capability-router route --levels coding=high,long_context=none,writing=mid "task text"
```

Below, `LEVELS` stands for this all-items string.

## How do I handle several tasks?

Accept one or more tasks, but **call the CLI once per task**. One call cannot route several tasks.

1. Estimate and build `--levels` separately for each task.
2. Call `route` for each task and record the config and service IDs.
3. Return a table, even for one task:

| task | required levels (other than none) | mode | config | service |
|---|---|---|---|---|
| `task text` | `item=level` pairs, or `-` if all `none` | `balanced` | `config id` | `service id` |

Show only non-`none` items in the result table. If the user corrects a level, rerun only that row with revised `--levels`.

## When should I skip the router?

When the deliverable is mostly polished prose and the user's items do not cover that judgment, the caller picks a writing config directly from its catalog and pool. Use the router normally when the deliverable is research, verification, or a change you can check, such as checking the evidence behind a proposal or finding technical errors in a manuscript.

## How do I choose a mode?

- `cheap`: The lowest cost qualifying config. Use for interactive work that must not keep a person waiting, light summaries, formatting, and short questions.
- `balanced` (default): Start with the cheapest qualifying config; trade up only when `cost_band` and `score_margin` from the definition's `routing` permit it. Use when unsure.
- `best`: The highest ranking score among qualifying configs, regardless of cost. Use when correctness is paramount, such as design, difficult reasoning, or technical research.
- `fast-balanced`: Start with the cheapest qualifying config; trade up to the fastest qualifying one when `time_cost_band` and `time_ratio` permit it. Use when a person is waiting and a moderate cost increase is acceptable. The catalog times compare configs; they are not predictions of actual elapsed seconds.

Cost means the sum of `cost_per_task` for the requested items, or for every item when the request is all `none`. Asking for extra items can change which config is cheapest. Every mode uses the same requirement filter; mode only selects among configs that pass it.

## How do I inspect the choice?

```
capability-router route --levels "$LEVELS" --explain "task text"
```

The JSON includes `chosen`, `service`, input `levels`, applied `required` levels, `estimates`, `ranking`, `thresholds`, `relaxations`, `selection`, `services`, `cost_basis`, and `warnings`. Inspect it when the selection is surprising.

- `estimates`: With `--levels`, `probabilities` is `1.0` for each supplied level; `confidence` and `score` are `null`. `estimator: fixed` confirms this path.
- `thresholds`: The user's per-item thresholds, or `null` for an item decided by `level` alone. `capability-router models --detail` also shows them.
- `cost` and `cost_items`: Each ranking row sums `cost_per_task` for the requested items, with an item breakdown. `cost_basis` is `requested_items`, or `all_items` when every level is `none`.
- `time_per_task_s`: Sum of `time_per_task_s` for the requested items, or every item when every level is `none`. Only `fast-balanced` uses it for selection.
- `selection`: In `balanced`, shows `cheapest_passing`, `chosen`, `score_delta`, and `traded_up`. `selection.service` shows the chosen service's `tier` and `surplus`.
- `services`: Each service's usage tier and surplus. `exhausted` means a window has no remaining allowance; `low_5h` is deprioritized; `normal` is available. Surplus includes personal `offset`. Non-`ok` status means usage was unavailable and base surplus is zero. `usage_source` is `cache`, `fetched`, `file`, or `none`.
- Cost and time are required per item, so the only miss is a config that omits an item: it has no comparable cost for a request that needs that item, or for an all-`none` request, which sums every item. `cheap` and `balanced` exclude such a config, and a missing time likewise excludes it from `fast-balanced` trade-ups. Warnings name affected configs.
- `fallback: true`: No config met the original levels, so the router relaxed them. `relaxations` shows the changes; some original requirements may remain unmet.

Changing catalog membership does not alter an existing config's item value. Use `capability-router models --costs` for item costs and times, `capability-router models` for the H/M/L summary and service assignments, or `capability-router models --detail` for the numeric scores and thresholds.

## How do I log a delegation?

`route` writes one log record by default. When sending work to another agent, pass `--label` and `--print-log-id`:

```
capability-router route --levels "$LEVELS" --mode <mode> --label "short label" --print-log-id "task text"
```

Stdout then has `<config id> <service id> <log-id>`. Put that log ID in the order or other handoff. After the delegation, append an outcome with the same ID whether it passed, failed, or was abandoned:

```
capability-router log outcome <log-id> --status pass|fail|abandoned [--rounds <rework count>] [--implementer "<kind:args>"] [--note "<note>"]
```

Without `--duration <seconds>`, duration runs from the route record to now. `capability-router log` shows aggregates. Routing still works when logging is disabled with `--no-log` or `CAPABILITY_ROUTER_LOG=off`, or when a write fails.

## What if the input has images or is long?

Use `--has-image` to exclude configs without vision. Use `--input-tokens <n>` to exclude configs with insufficient context for long input; otherwise the CLI estimates tokens from the task text.
