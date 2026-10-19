# capability-router

- LLM agents and users can choose a model and reasoning effort pair (config) for each task using their own criteria.
- People with several flat-rate AI subscriptions can delegate work to the subscription with more allowance to spare.
- Unlike prompt routers such as RouteLLM and OpenRouter Auto, selection uses user-defined capability items, without a trained classifier. It returns IDs without calling a model.

This command supplies the task's required levels and receives the config and service on one line.

```sh
capability-router route --levels coding=mid,long_context=low "Add retry handling to the API client"
```

The fictional examples shipped with the repository return a line such as `example-mid cursor`.

## How it works

1. **You define the yardstick.** Define capability items and levels through anchor problems, then compare tasks and configs on the same levels.
2. **The calling LLM estimates requirements.** The agent with access to the conversation and repository supplies a level for every item.
3. **Choose a service by subscription surplus first.** Use each subscription at an even pace over its allowance window.
4. **Select without calling a model.** Use the returned IDs with any launch method.

Details: [How it works](docs/how-it-works.md)

## What do you want to do?

**Get started and define your criteria**

- [Install and route your first task](docs/start.md): Try the fictional examples shipped with the repository.
- [Define capability items](docs/define-items.md): Set levels and anchor problems for each item.
- [Register configs](docs/register-configs.md): Record each config's capabilities, cost and services.
- [Check routing](docs/check-routing.md): Inspect assignments and investigate surprising choices.

**Delegate tasks**

- [Have an agent select a config and delegate](docs/delegate-from-an-agent.md): Let the agent estimate requirements and launch the selected config.
- [Route without an agent](docs/delegate-from-an-agent.md#jev): Have the external Jev API estimate requirements from a script.
- [Balance subscription usage](docs/balance-subscriptions.md): Prefer services with more surplus.
- [Record delegation outcomes](docs/log-delegations.md): Review assignments and outcomes later.

Reference: [Commands, options, files, environment variables, exit codes and limitations](docs/reference.md)
