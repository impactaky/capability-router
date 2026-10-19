# Reference

## Commands

`capability-router` provides these subcommands.

- `route [options] ["task"]`: Print `<config id> <service id>` for a task supplied as an argument or on stdin. Record one delegation log entry.
- `models [--detail | --costs]`: Print each config's item values as `H`/`M`/`L`/`-`/`?`, total cost and time, and services. `--detail` shows scores and thresholds; `--costs` shows cost and time per item.
- `sanity [--mode M] [--json]`: Route every case in `sanity.yaml`, ignoring usage and `services.yaml`.
- `criteria [--output PATH]`: Write `criteria.md` beside the definition and print its path. With `--output -`, write to stdout.
- `usage [--json]`: Retrieve remaining allowance for each service and update the cache.
- `log [--since 7d|24h|30m|YYYY-MM-DD] [--json]`: Summarize delegation logs by config and service.
- `log outcome <id> --status pass|fail|abandoned [--duration S] [--rounds N] [--implementer TEXT] [--note TEXT]`: Append an outcome to an assignment record. Without `--duration`, use elapsed time since assignment. Recording the same ID again replaces its outcome.
- `--version`: Print the version.

## `route` options

`route` accepts these options.

- `--levels item=level,...`: Specify required levels (`none`/`low`/`mid`/`high`). Omitted items default to `none`. Without this option, Jev estimates requirements.
- `--mode cheap|balanced|best|fast-balanced`: Choose how to select among configs meeting every requirement (passing configs) within the selected service ([table below](#mode)).
- `--explain`: Print the full decision as JSON.
- `--has-image`: Exclude configs with `vision: false`.
- `--input-tokens N`: Exclude configs where N exceeds 80% of `context_window_tokens`. Without this option, estimate from the task text.
- `--no-usage`: Skip usage retrieval. Every service's surplus becomes 0 + `offset`.
- `--usage-file PATH`: Read a `usage --json` snapshot without retrieving usage or saving the cache.
- `--jev-fixture PATH`: Replay a recorded Jev response.
- `--label TEXT`: Save a label in the log.
- `--no-log`: Skip logging.
- `--print-log-id`: Print `<config> <service> <log-id>`. The ID is `-` when nothing was logged.

<a id="mode"></a>
## `--mode`

This table compares selection in the four modes and when to use them.

| Mode | Selection | When to use |
|---|---|---|
| `balanced` (default) | Start with the cheapest; trade up if cost is within 1.25 times and ranking score is at least 0.05 higher | Use when unsure which mode to choose |
| `cheap` | Choose the cheapest | Short, light tasks |
| `best` | Choose the config with the highest ranking score | Design, difficult reasoning and research |
| `fast-balanced` | Trade up to the fastest config costing at most 2.5 times as much and taking at most half the time | Someone is waiting and some extra cost is acceptable |

The table uses these terms.

- Cost: the sum of `cost_per_task` over requested items (all items when every level is `none`).
- Ranking score: a weighted geometric mean of item scores, weighted by `routing.level_weight` for the required levels.
- Score for an item written as a `level`: the threshold for that level. Without thresholds, `H`/`M`/`L` = 1.0 / 2/3 / 1/3, and `-` is 0.

## `--explain` keys

`--explain` prints these JSON keys.

- `chosen`, `service`, `mode`, `fallback`: The result. `fallback: true` means requirements were relaxed.
- `levels` / `required`: Supplied levels / levels applied after relaxation.
- `estimates`, `estimator`: Per-item estimates and their source (`fixed`, `jev`, `fixture`).
- `ranking`: Every config's `score`, `cost`, `passed`, `services`, `item_scores`, rejection `reasons`, and other details.
- `thresholds`: Per-item thresholds; `null` for items read only as a `level`.
- `relaxations`: Items lowered, levels before and after, and configs rejected at each relaxation step.
- `selection`: `cheapest_passing`, `chosen`, `score_delta`, `budget`, `traded_up`, and `service` (`chosen`, `tier`, `surplus`, `tied_services`).
- `services`: Each service's `status`, `tier` (`normal`/`low_5h`/`exhausted`), `surplus`, `base`, `offset`, `ticket`, and allowance windows.
- `cost_basis`, `cost_items_requested`: `requested_items`, or `all_items` when every item's level is `none`.
- `usage_source`, `usage_fetched_at`: One of `cache`, `fetched`, `file`, `none`, and the retrieval timestamp.
- `task_tokens_estimate`, `warnings`, `log_id`: Estimated input length, warnings and log ID.

## Files

This table lists default file locations and how to override them.

| File | Default location | Override |
|---|---|---|
| Capability definition | `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` | `CAPABILITY_ROUTER_CAPABILITIES` |
| `criteria.md` (generated) | Beside the definition | `criteria --output` |
| Catalog (`<config-id>.yaml` files) | `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` | `CAPABILITY_ROUTER_MODELS` |
| `pool.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml` | `CAPABILITY_ROUTER_POOL` |
| `services.yaml` (optional) | `${XDG_CONFIG_HOME:-~/.config}/capability-router/services.yaml` | `CAPABILITY_ROUTER_SERVICES` |
| `sanity.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml` | `CAPABILITY_ROUTER_SANITY` |
| Delegation log | `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` | `CAPABILITY_ROUTER_LOG` (`off` disables it) |
| Usage cache (five minutes) | `${XDG_CACHE_HOME:-~/.cache}/capability-router/usage.json` | `XDG_CACHE_HOME` |

<a id="capabilities"></a>
### `capabilities.yaml`

The capability definition accepts these keys.

- `version`: `3`.
- `items.<item>.measures`: What the item measures. Required; also used in the default Jev question.
- `items.<item>.excludes`: What the item does not measure. Required.
- `items.<item>.levels`: Descriptions for `none`/`low`/`mid`/`high`. Required.
- `items.<item>.examples`: Lists of anchor problems for `low`/`mid`/`high`. Optional.
- `items.<item>.question`: The Jev question. Optional.
- `items.<item>.thresholds`: `{low, mid, high}` satisfying `0 <= low <= mid <= high <= 1`. Required if any config writes this item as a `score`.
- `routing.level_weight`: Defaults to `{none: 0, low: 1, mid: 2, high: 3}`.
- `routing.cost_band`, `routing.score_margin`: Trade-up conditions for `balanced`. Defaults: 1.25 and 0.05.
- `routing.time_cost_band`, `routing.time_ratio`: Trade-up conditions for `fast-balanced`. Defaults: 2.5 and 0.5.

### Catalog files

A catalog file describing one config accepts these keys.

- `id`, `model`: Required.
- `effort`, `snapshot`: Optional free text.
- `context_window_tokens`, `vision`: Optional; used by the `--input-tokens` and `--has-image` filters.
- `items.<item>.score` or `.level`: Write exactly one: a `score` in 0..1 (or `null`), or a `level` of `H`/`M`/`L`/`'-'` (quotes required).
- `items.<item>.cost_per_task`, `.time_per_task_s`: Required nonnegative values, in units you choose.

### `pool.yaml`

`pool.yaml` assigns configs to services with these keys.

- `configs.<id>.services`: A nonempty list of `codex`/`claude`/`cursor`/`commandcode`. Required for every catalog config. Earlier services win ties.
- `configs.<id>.enabled`: Defaults to `true`. Set `false` to exclude a config without deleting its file.

### `services.yaml`

`services.yaml` adjusts service priority with these keys.

- `low_5h_percent`: Defaults to 5. Deprioritize services whose five-hour allowance remaining percentage is at or below this value (`low_5h`).
- `services.<id>.offset`: Points added to surplus.
- `services.<id>.ticket`: With `true`, use the remaining weekly percentage as surplus.

### `sanity.yaml`

`sanity` reads these keys from `sanity.yaml`.

- `tasks`: A list of `{id, label, levels}`. Omitted items default to `none`.

## Environment variables

These environment variables are read.

- `CAPABILITY_ROUTER_CAPABILITIES`, `_MODELS`, `_POOL`, `_SERVICES`, `_SANITY`, `_LOG`: File locations (above).
- `CAPABILITY_ROUTER_LOG_TASK=1`: Save task text in the log (not saved by default).
- `CAPABILITY_ROUTER_CODEXBAR`: The codexbar command (default: `codexbar`).
- `CAPABILITY_ROUTER_CURSOR_AUTH`: The cursor-agent authentication file (default: `${XDG_CONFIG_HOME:-~/.config}/cursor/auth.json`).
- `COMMAND_CODE_API_KEY`: Used to retrieve Command Code usage.
- `TYPESAFE_API_KEY`: Used for Jev when `--levels` is omitted.
- `TYPESAFE_BASE_URL`, `TYPESAFE_DEFAULT_MODEL`: Jev endpoint and model (defaults: `https://api.typesafe.ai` and `jev-latest`).

## Helper scripts

These helper scripts are in `examples/`.

- `examples/levels_from_anchors.py RESULTS.yaml [--pass-rate 0.5]`: Print catalog `level` lines from per-level pass rates shaped like `big-high: {sql: {low: 1.0, mid: 1.0, high: 0.75}}`.
- `examples/thresholds.py CATALOG_DIR DEFINITION [--tasks item=n,...]`: Print placeholder `thresholds` from the highest score for each item.

## Exit codes

Commands use these exit codes.

- `0`: A config was assigned (including after relaxation). `usage` returns 0 even when retrieval fails for some services.
- `1`: `route` has no config it can assign (for example, every service is exhausted).
- `2`: Missing or invalid definition, catalog or `pool.yaml`; unknown item or level; empty task; missing `TYPESAFE_API_KEY`; Jev HTTP error; or `log outcome` failure.

## Limitations

- When no config passes, requirements are lowered one item at a time and the result returns exit code 0. It may not meet the original requirements.
- When every service is exhausted, requirements are not relaxed and the command exits with code 1.
- When `--has-image` or input length excludes every config, all items are relaxed to `none`. The best config is returned with warnings.
- Only four service IDs are supported: `codex`, `claude`, `cursor`, `commandcode`.
- Services whose usage cannot be retrieved remain available. They are treated as being on pace (zero surplus).
- Allowance windows affecting only some models within a service are ignored.
- Cost and time are comparison values. Equal values across configs do not affect selection.
- Catalog times do not predict actual task duration.
- Stale `criteria.md` produces a warning but routing continues.
- Items absent from the definition are errors. Configs missing an item are excluded when that item is required.
- Judging prose quality requires an item defining prose quality.

For developers: [Specification](spec.md) and [design decisions](design.md).
