# How it works

[日本語](how-it-works.ja.md)

capability-router serves these purposes.

- LLM agents and users can choose a model and reasoning effort pair (config) for a task using their own criteria.
- Delegated work can be spread across flat-rate AI subscriptions according to their remaining allowance.

Four ideas make this possible.

<a id="items"></a>
## 1. You define the yardstick

**Constraint**: Prompt routers and public leaderboards judge capability using someone else's training data or benchmarks.

**Approach**: Define capability items and their four levels (`none`/`low`/`mid`/`high`) through anchor problems. Express task requirements and config capabilities on the same levels and compare them with `route`.

**Limit**: Real definitions and catalogs are not included, so routing quality depends on your measurements.

<a id="caller-estimates"></a>
## 2. The calling LLM estimates requirements

**Constraint**: A router sees only the task text, without access to the conversation or repository available to the delegating agent.

**Approach**: Run `capability-router criteria` to generate criteria listing each level's anchor problems from the definition. The delegating agent reads them and follows the bundled [skill](../skills/capability-router/SKILL.md) to pass every item's level through `--levels`.

**Limit**: The external Jev API can estimate requirements without an agent, but this is not recommended because it sees only the task text.

<a id="service-first"></a>
## 3. Choose a service by subscription surplus first

**Constraint**: Choosing flat-rate subscriptions with weekly or monthly caps by price alone can exhaust one while others reset with unused allowance.

**Approach**: `route` first chooses a service with more allowance remaining than expected at an even pace (greater surplus). It then selects a config within that service.

**Limit**: Selecting a service first can assign a large config to a light task.

<a id="ids-only"></a>
## 4. Select without calling a model

**Constraint**: A proxy that calls models must support each service's launch methods, including CLIs, flags and reasoning effort names.

**Approach**: `route` only returns one line, `<config> <service>`, such as `example-mid cursor`. The caller launches the selected service using `model` and `effort` from the catalog file.

**Limit**: You write the mapping between config IDs and launch options.
