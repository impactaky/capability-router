# 自分の環境で使うには

[English](setup.md)

能力の定義、カタログ、`pool.yaml` を用意すると `models`、`sanity`、`route` を実行できます。定義の作り方は[手順](tutorial.ja.md)、形式は[仕様](spec.ja.md)を参照してください。

## 設定ファイルをどこに置きますか

| ファイル | 既定の場所 | 上書き |
|---|---|---|
| `capabilities.yaml`（自分の項目） | `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` | `CAPABILITY_ROUTER_CAPABILITIES` (file) |
| `sanity.yaml`（自分のケース） | `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml` | `CAPABILITY_ROUTER_SANITY` (file) |
| `criteria.md`（生成物） | `capabilities.yaml` の隣 | `capability-router criteria --output PATH` |
| カタログ (`*.yaml`) | `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` | `CAPABILITY_ROUTER_MODELS` (directory) |
| `pool.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml` | `CAPABILITY_ROUTER_POOL` (file) |
| `services.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/services.yaml` | `CAPABILITY_ROUTER_SERVICES` (file) |
| 委任の log | `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` | `CAPABILITY_ROUTER_LOG` (file。`off` で無効) |
| 使用量の cache | `${XDG_CACHE_HOME:-~/.cache}/capability-router/usage.json` | `XDG_CACHE_HOME` |

すべて上の path から読みます。repo は `examples/` に架空の一式を置きますが、これは既定値ではなく、環境変数で指さない限り読みません。

定義、カタログの directory、`pool.yaml` が無ければ、`route`、`models`、`sanity`、`criteria` は探した path と上書き用の環境変数を示し、終了コード 2 で終わります。`usage` はどれも読みません。

空の設定で試すには、`examples/` の架空の一式をコピーします。

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

`CAPABILITY_ROUTER_CAPABILITIES`、`CAPABILITY_ROUTER_MODELS`、`CAPABILITY_ROUTER_POOL` を設定している場合は、その file を作ってください。`pool.yaml` にはカタログの全 config が必要です。

## 使用量をどう取得しますか

使用量を取得できなくても `route` は動きます。取得ツールが一つも無ければ、各サービスを余り 0 の `normal` として扱います。取得できなかった理由は `route --explain` の `services` に出ます。

サービス id は `codex`、`claude`、`cursor`、`commandcode` の四つに固定されています。`pool.yaml` に他の id は追加できません。

| サービス | 用意するもの | 確認方法 |
|---|---|---|
| Codex / Claude Code | `codexbar` を入れ、各 CLI で OAuth 認証します。`CAPABILITY_ROUTER_CODEXBAR` でコマンドを変更できます。 | `codexbar usage --provider codex --source oauth --json-only`。Claude Code は `--provider claude`。 |
| Cursor Pro | `cursor-agent` にログインします。既定では `${XDG_CONFIG_HOME:-$HOME/.config}/cursor/auth.json` の `accessToken` を読みます。別の場所は `CAPABILITY_ROUTER_CURSOR_AUTH` に指定します。 | `capability-router usage` の `cursor` の `status` |
| Command Code | アカウントで発行した API key を `COMMAND_CODE_API_KEY` に渡します。 | `capability-router usage` の `commandcode` の `status` |

`capability-router usage` で各サービスを確認できます。取得元と認証は[仕様](spec.ja.md#各サービスからどう取得しますか)を参照してください。API key は環境変数で渡します。

`services.yaml` は任意です。無ければ既定値で動きます。サービスごとの `offset` と `ticket`、共通の `low_5h_percent` を調整するときだけ作ります。形式は[仕様](spec.ja.md#services-設定は何を持ちますか)を参照してください。

## PATH からどう呼びますか

repo の root で editable install します。実行時に repo 内の設定を読まないため、`-e` で source を編集可能にしておけば十分です。

```sh
uv tool install -e .
capability-router route --no-usage --no-log --levels coding=low "x"
```

install 時に示された tool directory が PATH に無ければ `uv tool update-shell` を実行し、shell を開き直します。別の場所から実行する場合は、環境変数で自分の file を指すか、`uv run --project <repo> capability-router` を使います。

```sh
config=/path/to/your/config
catalog=/path/to/your/catalog
CAPABILITY_ROUTER_CAPABILITIES="$config/capabilities.yaml" \
CAPABILITY_ROUTER_MODELS="$catalog" \
CAPABILITY_ROUTER_POOL="$config/pool.yaml" \
  capability-router models
```

## `--levels` を省くにはどうしますか

`--levels` を省くと、`route` は外部 API の Jev に level の推定を任せます。`TYPESAFE_API_KEY` を環境変数で渡してください。接続先を変えるときだけ `TYPESAFE_BASE_URL` を設定します。`--levels` を渡す場合、Jev の key は要りません。

## LLM 向けの基準をどう保ちますか

`capabilities.yaml` を変えたら `capability-router criteria` を実行します。定義の隣に `criteria.md` を書き、先頭に定義の sha256 を入れます。hash が一致しなくなると `route` が stderr に warning を 1 行出します。routing は止まりませんが、古い基準に気付けます。呼び出し側の LLM はこの `criteria.md` を読みます。[SKILL.md](../skills/capability-router/SKILL.md) (英語) を参照してください。
