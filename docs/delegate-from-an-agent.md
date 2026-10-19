# Have an agent select a config and delegate

Have an LLM agent select and launch a config and service for each delegation ([why the agent estimates requirements](how-it-works.md#caller-estimates)).

## Prerequisites

- A setup that lists configs with `capability-router models` ([register configs](register-configs.md)), current `criteria.md`, and `capability-router` on `PATH` (otherwise, [run from anywhere](start.md#path))
- An agent with the bundled skill installed (for example, `cp -r skills/capability-router ~/.claude/skills/`)

## Steps

1. Ask the agent: “Use capability-router to select a config for this task: <task>.” The agent estimates every item, including `none`, and receives a config and service with this command.
   ```sh
   read config service < <(capability-router route --levels coding=mid,long_context=low,writing=none "<タスク>")
   ```
2. The agent launches `$service` using `model` and `effort` from the selected config's catalog file ([why the caller launches it](how-it-works.md#ids-only)). If the choice is surprising, [investigate it](check-routing.md#inspect).

Add these `route` options as needed for the task.

- Images included: `--has-image`
- Input longer than the task text, such as attachments: `--input-tokens <n>`
- Prioritize cost, correctness or waiting time: `--mode` ([list](reference.md#mode))

<a id="jev"></a>
## Route without an agent (Jev)

1. Omit `--levels` to have the external Jev API estimate requirements from the task text alone (`estimator` in `--explain` becomes `jev`).
   ```sh
   export TYPESAFE_API_KEY=... && capability-router route --explain "<タスク>"
   ```
