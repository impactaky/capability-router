# capability-router

[日本語](README.ja.md)

capability-router is a CLI for delegating a task to another LLM. The caller rates the task's requirements across the capability items as `none`, `low`, `mid`, or `high`. The router selects a qualifying config and the service that can run it. A config is a model and reasoning effort pair.

Capability items are **user-defined**. The repository ships no items, no catalog values, and no evaluation data. You define your items, their levels, their anchors, and their thresholds in `capabilities.yaml`, and you fill the catalog with one score or level, a cost, and a time per item.

## How do I try it?

Install Python 3.11 or later and [uv](https://docs.astral.sh/uv/). Pass `item=level` to `--levels`; omitted items default to `none`. This example uses the fictional definition and catalog in `examples/`.

```sh
CAPABILITY_ROUTER_CAPABILITIES=examples/capabilities.yaml \
CAPABILITY_ROUTER_MODELS=examples/models \
CAPABILITY_ROUTER_POOL=examples/pool.yaml \
  uv run capability-router route --no-usage --no-log --levels coding=low "x"
```

```text
example-small codex
```

`--no-usage` skips usage retrieval, and `--no-log` skips the delegation log. Without `--levels`, the CLI asks the external Jev API to estimate requirements and needs `TYPESAFE_API_KEY`.

## How do I set it up for real use?

1. **Install prerequisites.** Install Python 3.11 or later and uv. See [setup](docs/setup.md).
2. **Define your items.** Copy `examples/capabilities.template.yaml` to `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` and fill in your items. [Tutorial](docs/tutorial.md) shows how to build the anchor problems, levels and thresholds.
3. **Build the catalog.** Create one YAML file per config under `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/`, one value per item. See the [specification](docs/spec.md).
4. **Create `pool.yaml`.** Assign configs to services. See [setup](docs/setup.md) for its location and the [specification](docs/spec.md) for its format.
5. **Generate `criteria.md`.** Run `capability-router criteria` so the calling LLM reads your items. See [SKILL.md](skills/capability-router/SKILL.md).
6. **Set up usage retrieval (optional).** [Setup](docs/setup.md) covers prerequisites and checks. Service IDs are fixed to `codex`, `claude`, `cursor`, and `commandcode`. If no retrieval tool is available, `route` still runs and treats each service as `normal` with zero surplus.
7. **Use the skill.** [SKILL.md](skills/capability-router/SKILL.md) covers placement and invocation.

## How do I define an item?

An item is defined by its anchor problems. A task is `low` when it is about as demanding as the item's `low` anchors, and so on; a config satisfies a level when it passes a large enough share of those anchors. The level text is a short summary of its anchors. When a level has no anchors, the level is judged from the text alone and any threshold is a placeholder. See the [tutorial](docs/tutorial.md).

```yaml
items:
  coding:
    measures: Implementing a given specification or algorithm as correct code.
    excludes: The finish of a written deliverable.
    levels: {none: ..., low: ..., mid: ..., high: ...}
    examples:
      low: [Fix an off-by-one error in an existing loop.]
      mid: [Implement a config loader with validation and tests.]
      high: [Implement a numerically stable matrix decomposition from its specification.]
    thresholds: {low: 0.3, mid: 0.5, high: 0.7}
```

A catalog config gives each item a `score` (0..1) **or** a `level` (`H`/`M`/`L`/`-`), plus a `cost_per_task` and a `time_per_task_s`:

```yaml
id: example-large
model: Example Large
effort: high
items:
  coding: {level: H, cost_per_task: 1.0, time_per_task_s: 30}
  long_context: {score: 0.8, cost_per_task: 1.0, time_per_task_s: 30}
```

## How is one config selected?

```text
Requirements + available configs
  ↓
Filter by image support and input length
  ↓
Discard configs below the required levels
  ↓
Choose a service by usage
  ↓
Choose a config within that service using --mode
  ↓
Config ID + service ID
```

If no config qualifies for reasons other than usage, the router relaxes requirements one level at a time. `--mode` chooses among qualifying configs.

| `--mode` | Selection |
|---|---|
| `balanced` (default) | Start with the cheapest; choose a higher scoring config when the gain justifies its cost |
| `cheap` | Lowest cost |
| `best` | Highest combined score on requested items |
| `fast-balanced` | Start with the cheapest; choose a faster config when the time gain justifies its cost |

## Where are the details?

- [Tutorial: build your own items](docs/tutorial.md)
- [Agent instructions](skills/capability-router/SKILL.md)
- [Specification](docs/spec.md)
- [Setup](docs/setup.md)
- [Design decisions](docs/design.md)
