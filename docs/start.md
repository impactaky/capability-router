# Install and route your first task

[日本語](start.ja.md)

Run capability-router and route your first task using the fictional examples shipped with it ([why real definitions are not included](how-it-works.md#items)).

## Prerequisites

- Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and a repository clone (`git clone https://github.com/impactaky/capability-router.git && cd capability-router`)

## Steps

1. Copy the examples to the default locations and generate the estimation criteria (`criteria.md`).
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"
   mkdir -p "$d" "$m" && cp examples/{capabilities,sanity,pool}.yaml "$d/" && cp examples/models/*.yaml "$m/"
   uv run capability-router criteria
   ```
2. Route a light task and a demanding task with these two commands, skipping usage retrieval and logging.
   ```sh
   uv run capability-router route --no-usage --no-log --levels coding=low "Fix an off-by-one error"
   uv run capability-router route --no-usage --no-log --levels coding=high "Implement a diff algorithm"
   ```
   The cheapest qualifying configs and their services are `example-small codex` and `example-large claude`.

<a id="path"></a>
## Run from anywhere

1. Install on `PATH` and check that the version appears (if the command is missing, run `uv tool update-shell` and reopen your shell).
   ```sh
   uv tool install -e . && capability-router --version
   ```
