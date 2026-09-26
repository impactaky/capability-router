# Set up capability-router

[日本語](setup.ja.md)

To run `models`, `sanity` and `route`, provide a capability definition, a catalog and `pool.yaml`. See the [tutorial](tutorial.md) to build the definition and the [specification](spec.md) for the file formats.

## Where do the files go?

| File | Default location | Override |
|---|---|---|
| `capabilities.yaml` (your items) | `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` | `CAPABILITY_ROUTER_CAPABILITIES` (file) |
| `sanity.yaml` (your cases) | `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml` | `CAPABILITY_ROUTER_SANITY` (file) |
| `criteria.md` (generated) | Beside `capabilities.yaml` | `capability-router criteria --output PATH` |
| Catalog (`*.yaml`) | `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` | `CAPABILITY_ROUTER_MODELS` (directory) |
| `pool.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml` | `CAPABILITY_ROUTER_POOL` (file) |
| `services.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/services.yaml` | `CAPABILITY_ROUTER_SERVICES` (file) |
| Delegation log | `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` | `CAPABILITY_ROUTER_LOG` (file; `off` disables it) |
| Usage cache | `${XDG_CACHE_HOME:-~/.cache}/capability-router/usage.json` | `XDG_CACHE_HOME` |

Everything is read from these paths. The repository ships a fictional set in `examples/`; it is not a default and is not read unless you point the environment variables at it.

If the definition, catalog directory or `pool.yaml` is missing, `route`, `models`, `sanity` and `criteria` report the searched path and override variable, then exit with code 2. `usage` does not read any of them.

To check an empty setup, copy the fictional example from `examples/`:

```sh
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"
catalog_dir="${CAPABILITY_ROUTER_MODELS:-${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models}"
mkdir -p "$config_dir" "$catalog_dir"
cp examples/capabilities.yaml "$config_dir/"
cp examples/sanity.yaml "$config_dir/"
cp examples/models/example-small.yaml "$catalog_dir/"
cat > "$config_dir/pool.yaml" <<'YAML'
configs:
  example-small: {services: [codex]}
YAML
uv run capability-router models
uv run capability-router criteria
uv run capability-router route --no-usage --no-log --levels coding=low "x"
```

If `CAPABILITY_ROUTER_CAPABILITIES`, `CAPABILITY_ROUTER_MODELS` or `CAPABILITY_ROUTER_POOL` is set, create those files instead. `pool.yaml` must list every catalog config.

## How do I set up usage retrieval?

`route` works without usage retrieval. If no retrieval tool is available, it treats every service as `normal` with zero surplus. `route --explain` reports retrieval failures in `services`.

The only service IDs are `codex`, `claude`, `cursor`, and `commandcode`. Other IDs cannot be added to `pool.yaml`.

| Service | Prerequisite | Check |
|---|---|---|
| Codex / Claude Code | Install `codexbar` and authenticate each CLI with OAuth. `CAPABILITY_ROUTER_CODEXBAR` can select the command. | `codexbar usage --provider codex --source oauth --json-only`; use `--provider claude` for Claude Code |
| Cursor Pro | Log in to `cursor-agent` to create its auth file. By default, the router reads `accessToken` from `${XDG_CONFIG_HOME:-$HOME/.config}/cursor/auth.json`. Set `CAPABILITY_ROUTER_CURSOR_AUTH` for another path. | `cursor` status in `capability-router usage` |
| Command Code | Put an API key from your Command Code account in `COMMAND_CODE_API_KEY`. | `commandcode` status in `capability-router usage` |

Run `capability-router usage` to check every service. The [specification](spec.md) details retrieval and authentication. Pass API keys through environment variables.

`services.yaml` is optional; defaults apply when it is absent. Create it only to adjust per-service `offset` and `ticket`, or shared `low_5h_percent`. See the [services settings](spec.md#what-do-services-settings-contain) for its format and meaning.

## How do I run it from PATH?

Run an editable installation at the repository root. `-e` keeps the source editable; nothing else is needed at runtime, because no configuration lives in the repository.

```sh
uv tool install -e .
capability-router route --no-usage --no-log --levels coding=low "x"
```

If the tool directory shown during installation is missing from PATH, run `uv tool update-shell` and reopen the shell. To run elsewhere, point the environment variables at your files, or use `uv run --project <repo> capability-router`.

```sh
config=/path/to/your/config
catalog=/path/to/your/catalog
CAPABILITY_ROUTER_CAPABILITIES="$config/capabilities.yaml" \
CAPABILITY_ROUTER_MODELS="$catalog" \
CAPABILITY_ROUTER_POOL="$config/pool.yaml" \
  capability-router models
```

## How do I omit `--levels`?

Without `--levels`, `route` asks the external Jev API to estimate required levels. Pass `TYPESAFE_API_KEY` as an environment variable. Set `TYPESAFE_BASE_URL` only to change the endpoint. The `--levels` path needs no Jev key.

## How do I keep the LLM criteria current?

Run `capability-router criteria` after every change to `capabilities.yaml`. It writes `criteria.md` beside the definition, headed by the definition's sha256. `route` warns once on stderr when that hash no longer matches, so a stale criteria file is visible without blocking routing. The calling LLM reads `criteria.md`; see [SKILL.md](../skills/capability-router/SKILL.md).
