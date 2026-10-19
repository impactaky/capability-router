# Record delegation outcomes

[日本語](log-delegations.ja.md)

Record the config, service and outcome of each delegation for later review.

## Prerequisites

- A working `route` setup ([have an agent select a config and delegate](delegate-from-an-agent.md))

## Steps

1. Route a task with a label and receive its log ID too (`-` means it was not logged).
   ```sh
   read config service log_id < <(capability-router route --levels "$LEVELS" --label "retry handling" --print-log-id "task text")
   ```
2. Once the delegation finishes, record its outcome against the returned log ID.
   ```sh
   capability-router log outcome "$log_id" --status pass --rounds 1 --implementer "codex:exec" --note "needed one fix"
   ```
3. Summarize and check records from the last seven days.
   ```sh
   capability-router log --since 7d
   ```
   The summary shows assignment counts, pass rates, median duration and other measures by config and service.
