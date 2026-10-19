# Balance subscription usage

[日本語](balance-subscriptions.ja.md)

Have `route` prefer the service with the most surplus among Codex, Claude Code, Cursor (Pro) and Command Code ([why](how-it-works.md#service-first)).

## Prerequisites

- A `pool.yaml` assigning configs to the services you use ([register configs](register-configs.md))
- Usage for `codex` and `claude`: install `codexbar` and log in to each CLI with OAuth.
- Usage for `cursor`: log in to `cursor-agent`.
- Usage for `commandcode`: set `COMMAND_CODE_API_KEY`.

## Steps

1. Check which usage data can be retrieved for each service.
   ```sh
   capability-router usage
   ```
   Each service shows its remaining allowance percentage, or `unavailable`/`error` with a reason. Services whose usage cannot be retrieved are treated as being on pace.
2. Retrieve usage and route a task. Check the service ordering.
   ```sh
   capability-router route --no-log --explain --levels "$LEVELS" "task text"
   ```
   `services` shows each service's `tier` and `surplus`; `selection.service.chosen` shows the selected service.

## Adjust priorities

1. This command adds 20 points to Cursor's surplus in `services.yaml`. Repeat step 2 afterwards.
   ```sh
   echo '{services: {cursor: {offset: 20}}}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/services.yaml"
   ```
