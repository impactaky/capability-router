# capability-router design decisions

[日本語](design.ja.md)

These are the decisions still in effect and why they were made. See the [specification](spec.md) for behavior and formats.

## What is the goal?

Represent task requirements and config capabilities with the same items, then compare them. Routing code does not know model names, item names, or catalog values. Model-specific information lives in the user's catalog; item definitions live in the user's `capabilities.yaml`. The repository ships neither.

## What shape and scope does it have?

| Decision | Reason |
|---|---|
| Use a CLI and skill. Return one `<config id> <service id>` line; do not invoke a model. | The caller launches the model. Some configs run on several services, and shell `read` can split two columns. |
| Route a config, meaning a model and reasoning effort pair. | Reasoning effort changes a model's capability, cost, and latency, so they are routed separately. |
| For tasks primarily about polished prose, let the caller choose a writing config directly. | Whether a user's items cover prose style is the user's choice; no item has to. The caller can pick directly. |
| Ship no items, no catalog values, and no evaluation data. | The tool is useful only with the user's own notion of capability. Shipping one would tie it to one external source and its vocabulary. |

## How are items defined?

| Decision | Reason |
|---|---|
| The user defines every item in `capabilities.yaml`: its `measures`, `excludes`, level text, anchors, and thresholds. | Different users and tasks care about different capabilities. The router stays general. |
| Define a level by its anchor problems (`examples`); the level text is a short summary of them, and a level without anchors is judged from the text alone with a placeholder threshold. | A line of prose is easy to read differently; an anchor problem pins down what a level means. Marking anchorless levels as placeholders makes the weaker judgment explicit. |
| Let a catalog item be a `score` (0..1) or a `level` (`H`/`M`/`L`/`-`). | A user with measured scores writes scores; a user running anchors writes levels. Both end up on one scale. |
| Give every item a `cost_per_task` and a `time_per_task_s`, and keep them unitless. | Cost and time differ by item and by config, but the units differ by user; equal values across configs make the comparison inert without disabling it. |
| Do not ship a catalog or template with real values. `examples/` is clearly fictional and shows the shape only. | A shipped value would be read as a recommendation and would age. |

## Who estimates requirements?

| Decision | Reason |
|---|---|
| The calling LLM estimates levels and passes `--levels`. Jev remains a CLI fallback when `--levels` is omitted. | The caller knows the conversation and repository, not just task text. The skill keeps one estimation path. |
| Generate the LLM-facing criteria from the definition with `capability-router criteria`; the LLM reads that file. Jev reads the definition's `question` and `levels`. | One source of truth. The generated file carries the definition's hash so a stale copy is visible. |
| Answer with the lowest sufficient level, based on the deliverable, and do not count reading the task instructions as a requirement. | Vague degrees of specialist knowledge cluster at `mid`, and mere compliance would inflate every estimate. |
| Do not inspect catalog scores before estimation is complete. | Desired configs must not drive task requirements backward. |
| Ask Jev one four-level Score question per item and take the most probable level. Never ask it to select a model. | Jev suits small, clear questions. This keeps requirements separate from capabilities. |
| Do not use Jev Noul. | Metadata handles images and length, every config supports tool use, and mode expresses latency preference. |

## How are scores and thresholds set?

| Decision | Reason |
|---|---|
| Keep scores absolute: a catalog `score` is the value itself, and a catalog `level` maps to the item's threshold (or the fixed midpoints without thresholds). | A config's value must not move when the catalog or pool changes. Absolute values keep the user's thresholds meaningful. |
| Read thresholds from the user's definition; the router never derives them from the pool. | The user sets the pass mark. A pool-relative ladder moves under the user and hides the choice. `examples/thresholds.py` is an offline helper only: it proposes placeholder thresholds for an item without anchors, which the user pastes into the definition; the router neither runs it nor derives anything at run time. |
| Require `thresholds` for any item a catalog scores, and fail at load time otherwise. | A score without a pass mark cannot be turned into a decision, so silently guessing would be worse than an error. |
| Rank with a weighted geometric mean using requested levels. | A weighted sum masks weak items; a minimum is too extreme. |

## How is a config selected?

| Decision | Reason |
|---|---|
| Start with the cheapest config meeting all requirements. `balanced` trades up only for a clear ranking gain. | Once a config passes, extra capability is headroom; small differences do not justify extra cost. |
| Sum `cost_per_task` for the requested items, or for every item when nothing is requested. | The full catalog total would charge for items the task never runs. |
| Exclude a config with no value for a requested item from `cheap` and `balanced` comparisons, and a config with no time from `fast-balanced` trade-ups. | Do not compare a partial or made-up total. |
| Use `time_per_task_s` only in `fast-balanced`, trading up to the fastest config within `time_cost_band` and `time_ratio` limits. | The caller knows whether speed matters. Unbounded fastest selection can be costly. |
| If nothing passes, lower one level at a time for the item rejecting the most configs. | Preserve the shape of the request and expose what was relaxed. |

## How are pool and data managed?

| Decision | Reason |
|---|---|
| Keep the item values in the catalog and enabled state plus service membership in `pool.yaml`. Key every catalog config with `services` and `enabled`. See [setup](setup.md). | The values and the operational assignment change for different reasons. Complete listing prevents silent disablement. Values stay in user XDG state. |
| Keep the catalog item-unit: one file per config, one `score`/`level`, cost and time per item. | The routing code and the user's item names stay decoupled, and pricing one item does not drag in unrelated numbers. |
| Let `sanity.yaml` display assignments for fixed levels without expected-answer checks or task text. | Routing takes levels, and an expected table ages poorly as the pool changes. |
| Record delegations and let callers append `log outcome`; do not read logs during routing. | Later review of speed and outcomes remains possible without feedback-based selection. |

## How is usage retrieved?

| Decision | Reason |
|---|---|
| `usage` returns every service's allowance and status, also as JSON. | Users and `route` can inspect the same snapshot. |
| Keep service fetchers and `SERVICE_IDS` in `usage.py`; `availability.py` and `scoring.py` read only snapshot values and IDs. | Routing need not know model names or retrieval providers. |
| Fetch four services concurrently with a 30-second limit each. Put failures in `status` and keep exit code 0. | One failure must not hide the others. |
| Distinguish `unavailable` from `error`. | Missing prerequisites differ from failed retrieval. |
| Explicitly use codexbar's OAuth source for Codex and Claude Code. | It uses saved credentials; the default `auto` path is slower. |
| Use cursor-agent's `auth.json` `accessToken` for Cursor Pro `GetCurrentPeriodUsage`. Derive remaining percentage from `remaining` / `limit`, not `totalPercentUsed`; never use `refreshToken`. | Refresh could invalidate the existing session, and `totalPercentUsed` has unclear units. |
| Use `COMMAND_CODE_API_KEY` with the CLI's `/alpha` APIs. Build the monthly window using its plan table, or show credits alone. | The API omits the monthly grant. `usage.py` comments identify `dist/cli.mjs` and `getPlanTotalCredits` as the transcribed source. |
| Supply personal paths and API keys through environment variables. Sanitize messages and discard external stderr. | Keep secrets and account details out of the repository and output. |

## How does usage affect selection?

| Decision | Reason |
|---|---|
| Choose by service tier and surplus first, then apply mode within a service. | On flat-rate subscriptions, spare allowance matters. |
| Surplus is expected usage from elapsed time minus actual usage. Use the minimum among weekly and monthly windows. | Remaining allowance means different things at different reset times. Apply one pace formula to every service. |
| Exclude short windows from surplus; deprioritize one as `low_5h` at or below `low_5h_percent`. Never select a service with any empty window. | Short windows reset soon, but a nearly exhausted one should reliably move back. |
| Put `offset` in personal services settings. | Contract and use priorities differ by user. |
| Do not count reset tickets. With `ticket: true`, use remaining weekly percentage as surplus, and still exclude zero. | A used ticket appears in the next snapshot. |
| Ignore `scoped` windows. | Their affected configs are unknown; treating them as service-wide could block unrelated configs. |
| If usage cannot be retrieved, treat the service as `normal` with zero plus `offset`. | Retrieval failure alone should not block a service; `--explain` shows why. |
| Cache `route` usage for five minutes. `sanity` reads neither usage nor services settings. | Avoid repeated retrieval and keep sanity independent of time and personal settings. |
| Do not relax requirements when usage excludes every config. | Relaxation cannot create an available service. |

## Which options were rejected?

- **Classify a prompt directly to a model name:** Every lineup change would require a new classifier.
- **Ship a default capability definition:** One user's items would become everyone's, and the tool would be tied to one notion of capability.
- **Derive thresholds from the pool at run time:** The user's pass mark would move with the catalog, and the choice would be hidden. The offline helper only proposes a starting point for an item without anchors; the user accepts or edits it in the definition.
- **Set thresholds by rank or candidate count:** This loses the meaning of a level.
- **Use a weighted sum:** It hides weak items.
- **Ask Jev to select a model:** Long reasoning is outside its intended role and mixes requirements with capabilities.
- **Add surplus to cost or score:** Units differ and absolute scores would be lost.
- **Read browser cookies for usage:** Those cookies grant broad account access. CLI credentials and service API keys suffice.
