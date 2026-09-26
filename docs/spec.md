# capability-router specification

[日本語](spec.ja.md)

This document defines current behavior and data formats. The [design decisions](design.md) explain why. `capabilities.yaml` is authoritative for the item definitions, thresholds and mode parameters; inspect computed values with `capability-router models --detail`.

## What do the terms mean?

| Term | Meaning |
|---|---|
| config | Routing unit: a model and reasoning effort pair, such as `example-small`. One catalog `<config-id>.yaml` file. |
| item | One capability axis, defined by the user in `capabilities.yaml`. Item names and count are the user's; the repository ships none. |
| level | Requirement or catalog step for an item: `none`, `low`, `mid`, `high`. |
| anchor | The short example problems a level is defined by, listed under `items.<item>.examples`. |
| catalog | User state with one value per item per config. It does not say where a config runs. |
| item value | A config's `score` (0..1) or `level` (`H`/`M`/`L`/`-`) for one item, plus its `cost_per_task` and `time_per_task_s`. |
| threshold | The score a `score`-written item must reach for a level, given by the user in `items.<item>.thresholds`. |
| pool | Catalog configs enabled by `pool.yaml`. These are the candidates. |
| service | Where a config runs: `codex`, `claude`, `cursor`, or `commandcode`. IDs match `usage`'s `services[].id`. A config may belong to several services. |
| surplus | Service usage left relative to an expected pace, in percentage points. |
| service tier | `normal`, `low_5h`, or `exhausted`. An `exhausted` service cannot be selected. |
| passing | Meeting every required level and the metadata filters. |

## How does `route` process a task?

0. **Build the pool.** Keep enabled configs from `pool.yaml` and their services. Read usage to compute each service's tier and surplus.
1. **Filter metadata.** With `--has-image`, exclude `vision: false`. Exclude a config when input tokens exceed 80% of `context_window_tokens`. Use `--input-tokens` or estimate from text as ASCII characters ÷ 4 plus other characters ÷ 1.5.
2. **Determine levels.** The skill's caller estimates a level for every item in the definition and supplies `--levels`. If omitted, the CLI sends one Score question per item to Jev in one request and takes each item's most probable level.
3. **Apply the definitions.** For each item above `none`, require the config's value to meet its level. A `level` value must cover the required level (`H` reaches `high`, `M` reaches `mid`, `L` reaches `low`, `-` only `none`). A `score` value must be at least the item's threshold for that level. A config with no value for a required item fails. Also exclude configs whose every service is `exhausted`.
4. **Relax if needed.** Only when nothing passes, lower one requirement by one level and repeat. Do not relax when usage has excluded every config.
5. **Rank.** Give all configs a weighted geometric mean of item scores using requested levels as weights.
6. **Select.** Among services with a passing config, choose the best tier and largest surplus; then apply `--mode` within that service.

## How are required levels supplied?

| Path | Estimator |
|---|---|
| `--levels item=level,...` (skill path) | The caller reads the generated `criteria.md` and estimates every item. The skill always passes `--levels`. |
| Omitted `--levels` | The CLI asks Jev one Score question per item. Requires `TYPESAFE_API_KEY`. |

`--levels` joins `item=level` pairs with commas. Unlisted items default to `none`, and an item name not in the definition is an error. Later routing steps are identical on both paths.

## How are items defined?

Items are entirely the user's. Each item in `capabilities.yaml` gives `measures` (what it measures), `excludes` (what it deliberately does not), a `levels` description for `none`/`low`/`mid`/`high`, optional per-level `examples`, an optional Jev `question`, and optional `thresholds`.

A level is defined by its anchor problems (`examples`): the level text is a short summary of them. A task is judged by how close it is to the level's anchors, and a config satisfies a level when it passes a large enough share of them. A level without anchors is judged from the text alone, and any threshold then is a placeholder. `examples` may key only `low`/`mid`/`high`, and each value is a non-empty list of non-empty strings.

When `question` is omitted, Jev receives:

```text
How much does this task require the following capability: <measures> Choose the lowest level that is sufficient.
```

When a level has `examples`, they are appended to its Jev `criteria` entry as ` Examples: <a>; <b>.`.

## How are item values and thresholds read?

A catalog config gives each item exactly one of `score` or `level`.

- `score` is a number in 0..1, or `null` for "no score". An item any config scores must carry `thresholds` in the definition; loading fails with the item name otherwise. A required `score` item passes only when `score` is at least the threshold for the requested level.
- `level` is `H`, `M`, `L`, or `-`. It passes a requirement directly: `H` reaches `high`, `M` reaches `mid`, `L` reaches `low`, and `-` only satisfies `none`. Where a numeric score is needed (the ranking geometric mean, `best`, `balanced`'s `score_margin`), a level uses the item's threshold for that level (`-` is 0); without thresholds it uses the fixed values `H` = 1.0, `M` = 2/3, `L` = 1/3, `-` = 0.

`thresholds` must satisfy `0 <= low <= mid <= high <= 1`. It may be omitted for an item that is written as a `level` everywhere; it is required for an item any config scores. There is no pool-relative threshold: the user's numbers are absolute, so the catalog changing never moves them.

A config that omits an item has no value for it. Requiring that item fails, and an all-`none` request has no comparable cost for that config (see below). A catalog item not in the definition is an error naming the config and item. A catalog file that still carries `benchmarks`, `evaluations`, `cost`, `performance`, or another old key is an error naming the key; there is no compatibility reading.

`capability-router models` shows each config's performance per item as `H`, `M`, `L`, `-`, or `?`: a `level` item shows its catalog letter; a `score` item shows the highest level whose threshold it clears (`score >= threshold`, the same comparison the filter uses), `-` below `low`, and `?` when the config has no value. A legend below the table names the item abbreviations and the symbols. It then shows enabled and disabled config counts and service assignments. `capability-router models --detail` shows the numeric score of each config and item, the thresholds (with `-` for an item decided by level alone), each item's kind (`score` or `level`), and the legend. `--detail` and `--costs` cannot be combined. Item columns are abbreviated to the item's initials, with an `items: <initials>=<item>, ...` legend below the tables. A paragraph is wrapped as a whole. When stdout is a terminal, the columns pack to the terminal width, numeric columns are right-aligned, and free-text columns and long lines wrap; free-text columns keep a readable minimum width, and identifier and numeric columns are never wrapped or truncated, so a table that cannot fit is wider than the terminal. When stdout is not a terminal, each record stays on one line without border characters or color.

## How is the ranking score computed?

Use the requested `level_weight` for each item; `none` has no weight, and higher levels have greater weight. Take the weighted geometric mean of item scores with positive weight, clipping each score at the minimum defined for ranking and omitting items without scores. If every request is `none`, weight all items equally. Keep the original weights if thresholds are relaxed.

## How are cost and time computed?

A catalog config gives every item a `cost_per_task` (unitless) and a `time_per_task_s` (seconds).

- Selection cost is the sum of `cost_per_task` over the originally requested items (levels other than `none`). The level within an item does not alter cost. Relaxation does not make the task cheaper.
- If every level is `none`, use the sum over every item in the definition. `--explain` reports `cost_basis` as `requested_items` or `all_items`.
- If a requested item (or, for an all-`none` request, any item) has no value in a config, the config has no comparable cost; do not use a partial sum.
- Sum `time_per_task_s` the same way. Only `fast-balanced` uses time for selection.
- Costs are unitless. Give every config the same cost to make the comparison effectively meaningless without disabling it.

## How does mode affect selection?

Every mode uses the same requirement filter. Mode selects among passing configs within the chosen service.

| Mode | Selection |
|---|---|
| `cheap` | Lowest cost; break cost ties by higher ranking score. |
| `balanced` (default) | Start with the cheapest passing config. Among configs costing at most its cost × `cost_band` and scoring at least its score + `score_margin`, choose the highest ranking score. Otherwise keep the cheapest. |
| `best` | Highest ranking score; ignore cost. |
| `fast-balanced` | Start with the cheapest passing config. Among configs costing at most its cost × `time_cost_band` and taking at most its time × `time_ratio`, choose the fastest. Break ties by lower cost, then higher ranking score. Otherwise keep the cheapest. |

`cheap` and `balanced` exclude configs without cost and name them in warnings. `best` may select them. If every passing config lacks cost, `cheap` and `balanced` select the highest ranking score and warn. `fast-balanced` handles missing cost likewise; a config without time cannot be a trade-up target.

## How do services and usage affect selection?

`route` reads a usage snapshot in the same shape as `usage`'s JSON output. It caches snapshots for five minutes. Personal service adjustments live in `services.yaml`.

For each unscoped `windows[]` entry:

- Ignore `scoped: true` windows, which apply only to some models within a service.
- A window at zero remaining makes the service `exhausted`.
- A `period: "5h"` window does not contribute to surplus. If its remainder is at or below `low_5h_percent`, the service is `low_5h`.
- For `week` and `month`, surplus is expected usage minus actual usage in percentage points. Expected usage is elapsed window time divided by total length, clamped to 0..100. A week begins seven days before `resetsAt`; a month begins one calendar month before it, using month end if that date does not exist. Treat `fetchedAt` as current time. A window without `resetsAt` adds no surplus.
- For a service with `ticket: true`, use the weekly remaining percentage as its surplus instead of expected pace. Zero still means `exhausted`.
- A window without `period` is used only to detect zero remaining.

A service's surplus is the minimum surplus among its weekly and monthly windows, plus `offset`. With none, use zero plus `offset`. A service whose `status` is not `ok`, is absent from the snapshot, or is under `--no-usage` is `normal` with zero plus `offset`.

Group passing configs by non-exhausted service. Prefer `normal` over `low_5h`, then higher surplus. Apply mode within the first service with a passing config. Services tied on tier and surplus form one group for mode selection. If the chosen config belongs to several tied services, use the first one listed in `pool.yaml`. With no usage, all services form one group.

## What happens when nothing passes?

Lower one requested item by one level and retry until something passes. Choose the item that currently rejects the most configs; break ties by higher requested level, then earlier order in the definition.

Record each relaxation in `--explain`'s `relaxations` and warnings, and set `fallback: true`. Apply mode normally after a config passes. If all items reach `none` and still nothing passes, such as when metadata excludes everyone, apply service ordering and mode to all configs on non-exhausted services and warn. If all services are `exhausted`, do not relax and return no config.

## What options does `route` accept?

| Option | Effect |
|---|---|
| `--levels <item=level,...>` | Required levels; omit to estimate with Jev. |
| `--mode <mode>` | `balanced` (default), `cheap`, `best`, or `fast-balanced`. |
| `--explain` | Output full decision as JSON. |
| `--has-image` | Exclude configs without vision. |
| `--input-tokens <n>` | Set input length; otherwise estimate from text. |
| `--no-usage` / `--usage-file <path>` | Change how usage is read. |
| `--jev-fixture <file>` | Replay a recorded Jev response. |
| `--label <text>` / `--no-log` / `--print-log-id` | Control delegation logging. |

Pass task text as an argument or on stdin.

## What does the `criteria` command do?

`capability-router criteria [--output PATH]` generates the LLM-facing Markdown from the capability definition. The default output is `criteria.md` beside the definition; `--output -` writes to stdout and `--output PATH` writes elsewhere.

The first line is `<!-- capability-router criteria: sha256=<sha256 of the definition file's bytes> -->`. The body is the shared rules, then each item in definition order as `### <item>`, `Measures: ...`, `Excludes: ...`, and `- none: ...` through `- high: ...`. A level with `examples` gets one `  - e.g. <example>` line per anchor beneath its level line.

`route` prints one warning line to stderr when `criteria.md` exists beside the definition and its hash does not match the definition. It never stops the route. A missing `criteria.md` prints nothing.

## What does `route` output?

- Normally, stdout contains one `<config id> <service id>` line; exit code 0.
- If no config can be routed, stderr says `error: no routable config`; exit code 1.
- Empty task text, invalid item or level in `--levels`, missing `TYPESAFE_API_KEY`, and Jev HTTP errors produce `error: ...` on stderr; exit code 2.

| Usage option | Behavior |
|---|---|
| None | Read a cache younger than five minutes, or fetch four services and update it. |
| `--usage-file <path>` | Read a `usage --json` shape from that file; no fetching or caching. |
| `--no-usage` | Do not read usage; every service is `normal` with zero plus `offset`. |

`--explain` outputs the full decision as JSON:

| Key | Meaning |
|---|---|
| `chosen` / `service` / `mode` / `fallback` | Selected IDs, mode, and whether relaxation occurred. |
| `levels` / `required` | Estimated original levels / levels applied after relaxation. |
| `estimates` | Per-item estimate: level, probability distribution, confidence, and score from Jev; with `--levels`, supplied level and probability `1.0`, without confidence or score. |
| `ranking` | Every config, passing first and then ranking score descending. Rows contain `score`, `cost`, `cost_items`, `time_per_task_s`, `passed`, `services` in pool order, `available_services`, `item_scores`, and rejection `reasons` (including `no service left (...)`). |
| `thresholds` | The definition's thresholds by item, or `null` for an item decided by level alone. |
| `relaxations` | Item, old and new level, and number of configs rejected at that step. |
| `selection` | For `balanced`: `cheapest_passing`, `chosen`, `score_delta`, `budget`, `traded_up`. `service` adds selected service's `chosen`, `tier`, `surplus`, and `tied_services`. |
| `services` | Status, tier, offset adjusted `surplus`, pre-offset `base`, `offset`, `ticket`, windows with `counted`, `expectedUsedPercent`, `surplus`, and `reason`; ordered by tier and surplus. |
| `usage_source` / `usage_fetched_at` | `cache`, `fetched`, `file`, or `none`, and snapshot `fetchedAt`. |
| `cost_basis` / `cost_items_requested` | `requested_items` or `all_items`, and the items used to price the task. |
| `warnings` | Relaxation, missing cost, balanced budget, and other warnings. |
| `estimator` / `task_tokens_estimate` | `jev`, `fixed`, or `fixture`; estimated input tokens. |

## How is delegation logged?

Each `route` call appends one route record. The caller appends an outcome with the same ID using `log outcome`. Routing never reads these records to adjust selection. Task text is not stored by default because it may contain organizational information.

See [setup](setup.md) for the path and `CAPABILITY_ROUTER_LOG` override; `off` disables logging. Create missing directories. The log is JSONL, one record per line, with each append protected by `fcntl.flock`. Include `task` only with `CAPABILITY_ROUTER_LOG_TASK=1`.

A route record has these fields:

| Key | Meaning |
|---|---|
| `type` / `version` | `"route"` / `1` |
| `id` | New ID from the first 12 characters of `uuid4().hex` |
| `ts` | UTC ISO 8601 time |
| `label` | `--label`, or `null` |
| `task` | Task text; key exists only with `CAPABILITY_ROUTER_LOG_TASK=1` |
| `mode` | Routing mode |
| `levels` | Originally supplied or estimated non-`none` levels only |
| `chosen` / `service` | Chosen IDs, or `null` if none |
| `fallback` | `true` after requirement relaxation |
| `cost` / `time_per_task_s` | Estimated cost (six decimals) and time (one decimal), or `null` |

The log omits full decision details such as surplus, relaxation steps, item costs, and token estimates. Use `--explain` to inspect those.

An outcome record may be appended more than once for an ID; aggregation uses the last one:

| Key | Meaning |
|---|---|
| `type` / `version` | `"outcome"` / `1` |
| `id` | Corresponding route record ID |
| `ts` | UTC ISO 8601 recording time |
| `status` | `pass`, `fail`, or `abandoned` |
| `duration_s` | `--duration`, or seconds from route `ts` to now |
| `rounds` | Integer `--rounds`, or `null` |
| `implementer` | `--implementer` string, or `null` |
| `note` | `--note`, or `null` |

### What are the log CLI commands?

- `route` logs by default and accepts `--label <text>`, `--no-log`, and `--print-log-id`. Stdout normally stays `<config id> <service id>`. With `--print-log-id` it becomes `<config id> <service id> <log-id>`; the ID is `-` if no record was written, including `--no-log`, `off`, or a write failure. `--explain` adds `log_id`, or `null` when absent. A write failure does not fail routing; stderr reports `warning: delegation log not written: <reason>`. A route with no chosen config is logged too.
- `sanity`, `models`, `criteria`, and `usage` do not log.
- `log outcome <id> --status pass|fail|abandoned [--duration <seconds>] [--rounds <n>] [--implementer <text>] [--note <text>]` returns exit code 2 for an unknown route ID (`unknown delegation id: <id>`) or when logging is `off`.
- `log [--since 7d|24h|30m|YYYY-MM-DD] [--json]` filters by route `ts`. For each config and service pair it reports route count, outcome count, pass rate, median `duration_s`, and median `rounds`, followed by totals. Pairs without outcomes show `-` for rate and medians. `--json` outputs the same aggregate as JSON. Invalid lines (non-JSON or missing `type`) are skipped and counted on stderr. A missing log file gives zero results; `off` is an exit-code-2 error.

## How is Jev called?

- Send `POST {TYPESAFE_BASE_URL}/v1/systemone`, defaulting to `https://api.typesafe.ai`, with `Authorization: Bearer $TYPESAFE_API_KEY`. Use `TYPESAFE_DEFAULT_MODEL`, default `jev-latest`, and a 15-second timeout.
- Send `{"state": <task text>, "model": ..., "questions": {<item>: {"type": "score", "instructions": <question>, "criteria": [<none>, <low>, <mid>, <high>]}}}`. Build questions and criteria from the capability definition. Do not send candidate config or model names.
- Take the maximum probability in `answers.<item>.probabilities`. If probabilities are absent, round `score` to a level. Any missing item answer is an error.

## What does `usage` return?

`capability-router usage` fetches, normalizes, and outputs usage allowance for four AI services. It reads neither `capabilities.yaml` nor the catalog. Its snapshot updates the cache that `route` reads.

- Fetch all four concurrently, with a 30-second timeout per service. One timeout or failure does not stop the others.
- Put failures in that service's `status` and still exit 0. Nonzero exit means a CLI failure such as invalid arguments.
- `--json` prints the structure below. Otherwise print a readable table of windows, remaining percentages, local reset times, and details, or status and reason on failure.

### What is the JSON shape?


| Key | Meaning |
|---|---|
| `fetchedAt` | UTC ISO time with milliseconds when fetching began; shared by all services. |
| `services[].id` / `name` | `codex` / Codex, `claude` / Claude Code, `cursor` / Cursor Pro, `commandcode` / Command Code; always four in this order. |
| `services[].status` | `ok`, `error` after an attempted retrieval (HTTP, expired authentication, timeout, bad JSON), or `unavailable` when prerequisites are missing (command, auth file, API key). |
| `services[].message` | Sanitized reason for `error` or `unavailable`. |
| `services[].plan` | Known plan name, currently Command Code `planId`. |
| `services[].windows[]` | Each allowance's remaining percentage. Empty unless `ok`. Labels are `5h` for 300 minutes, `週` for 10080 minutes, `月`, or the source title/minutes. `remainingPercent` is a rounded integer in 0..100; `resetsAt` is a reset time or `null`; `period` is `5h`, `week`, or `month` when known; `scoped` is true only for a window affecting some models (`extraRateWindows`); `detail` applies to monetary windows only. |
| `services[].credits` | Monthly credit remainder (USD, two decimals) only if Command Code's monthly window cannot be built because `planId` is unknown or subscription inactive. |

Before output, sanitize messages: replace control characters with spaces; redact email addresses, `sk-` prefixed tokens, `Bearer ...`, values after `token=`, `api_key=`, `secret=`, `password=`, or `authorization=`, and long alphanumeric strings with `[redacted]`; replace internal `/a/b` paths with `[internal path]`; truncate to 160 characters. Use `取得に失敗しました` if empty. Do not output tokens, emails, or account IDs. Discard external commands' stderr and write no log.

### How is each service queried?

| Service | Retrieval | Authentication |
|---|---|---|
| Codex / Claude Code | Run `codexbar usage --provider <codex or claude> --source oauth --json-only`. Use the first stdout line starting with `[` that parses as JSON. From the first element, use `usage.primary`, `secondary`, and `tertiary` (`{usedPercent, windowMinutes, resetsAt}` or null), plus `usage.extraRateWindows[]` (`{title, window}`; label is first 24 title characters). An `error` field or nonzero exit gives `error`. | Handled by codexbar. |
| Cursor Pro | `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage` with body `{}`. Build one monthly window from `planUsage.remaining` / `limit` in cents; percentage is remaining / limit and `resetsAt` comes from `billingCycleEnd` in milliseconds. Ignore `totalPercentUsed`. | Send cursor-agent `auth.json`'s `accessToken` as a Bearer token; never use `refreshToken`. |
| Command Code | `GET https://api.commandcode.ai/alpha/whoami?limits=1` for org ID, then read `/alpha/billing/credits?orgId=` and `/alpha/billing/subscriptions?orgId=` concurrently. Use `credits.windowLimits.fiveHour` and `weekly` `used`, `cap` (USD), and millisecond `resetAt`; derive the monthly window below. | Send `COMMAND_CODE_API_KEY` as a Bearer token. |

The Command Code monthly window follows its CLI `/usage` calculation. Build it only if subscription `data.status` is `active` and `planId` matches `usage.py`'s `COMMAND_CODE_PLAN_CREDITS` table transcribed from the CLI. Lowercase `planId`, replace `_` with `-`, and match longest prefixes first. Limit = max(plan monthly grant, `monthlyCredits`) + `purchasedCredits` + `freeCredits`; remaining = `monthlyCredits` + `purchasedCredits` + `freeCredits`; reset = `currentPeriodEnd`.

### How is usage cached?

Store the last sanitized snapshot at `${XDG_CACHE_HOME:-$HOME/.cache}/capability-router/usage.json`, without tokens or email addresses. `route` uses it when `fetchedAt` is younger than five minutes; otherwise it fetches and overwrites. If writing fails, such as on a read-only filesystem, use the fresh result without warning. `usage` always fetches and overwrites the cache.

### Which environment variables matter?

See [setup](setup.md) for file paths and overrides. `CAPABILITY_ROUTER_CODEXBAR` selects the codexbar command (default `codexbar`); `CAPABILITY_ROUTER_CURSOR_AUTH` selects cursor-agent's auth file. Without `COMMAND_CODE_API_KEY`, Command Code is `unavailable`. Only `CAPABILITY_ROUTER_LOG_TASK=1` includes task text in a route record.

## What do the data files define?

### What does `capabilities.yaml` define?

| Key | Meaning |
|---|---|
| `version` | Must be `3`. |
| `levels` | Level order. May be omitted; must be exactly `[none, low, mid, high]`. |
| `items.<item>.measures` | What the item measures. Required, non-empty. Also the default Jev question. |
| `items.<item>.excludes` | What the item does not measure. Required, non-empty. |
| `items.<item>.levels` | A description for each of `none`, `low`, `mid`, `high`. Required. |
| `items.<item>.examples` | Optional anchors per `low`/`mid`/`high`, each a non-empty list of non-empty strings. |
| `items.<item>.question` | Optional Jev instructions; a default is built from `measures`. |
| `items.<item>.thresholds` | Optional `low`/`mid`/`high` numbers in 0..1 with `low <= mid <= high`. Required when any config scores the item. |
| `routing.level_weight` | Ranking weights per level. Defaults to `{none: 0, low: 1, mid: 2, high: 3}`. |
| `routing.cost_band` / `score_margin` | `balanced` trade-up conditions. Defaults 1.25 / 0.05. |
| `routing.time_cost_band` / `time_ratio` | `fast-balanced` trade-up conditions. Defaults 2.5 / 0.5. |

A file with `axes`, `benchmarks`, a top-level `thresholds`, or another old key fails to load with that key named. There is no compatibility reading. Add an item by adding it under `items` and every catalog config; no router code changes.

### What does the catalog contain (`<config-id>.yaml`)?

See [setup](setup.md) for the location and `CAPABILITY_ROUTER_MODELS` override. Keep it outside the repository (`/models/` is gitignored). Only the fictional configs in `examples/models/` are shipped. Missing directories cause `route`, `models`, and `sanity` to report the searched path and override, then exit 2.

| Key | Meaning |
|---|---|
| `id` / `model` | Config ID and model name. Required. |
| `effort` / `snapshot` | Free text. Optional. |
| `context_window_tokens` / `vision` | Metadata filters. Optional. |
| `items.<item>.score` | A number in 0..1 or `null`. Exactly one of `score`/`level`. |
| `items.<item>.level` | `H`, `M`, `L`, or `'-'`. Exactly one of `score`/`level`. |
| `items.<item>.cost_per_task` | Unitless, 0 or more. Required. |
| `items.<item>.time_per_task_s` | Seconds, 0 or more. Required. |

In block style, write the lowest level quoted as `'-'`, because an unquoted dash starts a YAML sequence and fails to parse:

```yaml
items:
  coding:
    level: '-'
```

Errors name the config and item: both `score` and `level`, neither, an out-of-range score, an unknown level symbol, a missing `cost_per_task` or `time_per_task_s`, or an item not in the definition. A catalog file with `benchmarks`, `evaluations`, `cost`, or another old key fails to load with that key named.

### What does `pool.yaml` contain?

`pool.yaml` enables catalog configs and assigns services. See [setup](setup.md) for the path and override. The repository root ignores `/pool.yaml`; `examples/pool.yaml` is fictional.

```yaml
configs:
  example-small: {services: [codex]}                 # Use [codex, cursor] for multiple services
  example-spare: {services: [commandcode], enabled: false}
```

| Key | Meaning |
|---|---|
| `configs.<config id>.services` | Service ID list. Empty, duplicate, or unknown IDs are errors. The first listed service wins a tie. |
| `configs.<config id>.enabled` | Defaults to `true`; `false` removes it from the pool. |

List every catalog config. Missing catalog entries, unknown configs, and extra keys are exit-code-2 errors. A missing `pool.yaml` also exits 2 and reports the searched path and `CAPABILITY_ROUTER_POOL`.

### What do services settings contain?

These personal adjustments are outside the repository. Defaults work without the file. Optional keys are `low_5h_percent` (remaining short-window percentage at which to deprioritize), `services.<service id>.offset` (added surplus), and `services.<service id>.ticket` (weekly pace handling). See [setup](setup.md) for its path. An unknown service ID, a service key besides `offset` or `ticket`, a nonnumeric offset, a nonboolean ticket, or `low_5h_percent` outside 0..100 is an exit-code-2 error.

### What does `sanity.yaml` contain?

It is the user's set of fixed-level cases. The default is `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml`, or `CAPABILITY_ROUTER_SANITY`. Each case has an `id`, a short `label`, and `levels` (item-to-level map). Unlisted items become `none`; no task text or expected config is stored. Referencing an item not in the definition, or an unknown level, is an error identifying the case and exit 2. The repository ships only `examples/sanity.yaml`, with cases for the example items.

`capability-router sanity` routes each fixed case. Options are `--mode` (default `balanced`) and `--json`. The table shows `id`, `label`, non-`none` abbreviated `levels` (for example, `coding: low` becomes `c=l`), `chosen`, `service`, `cost/task`, and fallback. It also reports the number of distinct chosen configs and relaxed cases with details. It does not compare to expected answers. It ignores usage and services settings, so services form one group; `service` is the chosen config's first `pool.yaml` service. `--json` outputs `{"mode": ..., "results": [{id, label, levels, chosen, service, cost_per_task, time_per_task_s, fallback, relaxations}]}`.
