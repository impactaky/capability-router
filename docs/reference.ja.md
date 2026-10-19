# リファレンス

[English](reference.md)

## コマンド

`capability-router` のサブコマンドは次のとおりです。

- `route [options] ["task"]`：引数か標準入力でタスクを受け取ります。結果は `<config id> <service id>` の形式で出力します。委任ログを 1 件記録します。
- `models [--detail | --costs]`：config ごとに、各項目の値を `H`/`M`/`L`/`-`/`?` で示します。費用と時間の合計、サービスも表示します。`--detail` ではスコアと閾値を、`--costs` では項目ごとの費用と時間を確認できます。
- `sanity [--mode M] [--json]`：使用量と `services.yaml` を無視して、`sanity.yaml` の全ケースを割り当てます。
- `criteria [--output PATH]`：能力の定義ファイルと同じディレクトリに `criteria.md` を生成します。保存先のパスを出力します。`--output -` なら内容を標準出力に書き出します。
- `usage [--json]`：サービスごとの残量を取得してキャッシュを更新します。
- `log [--since 7d|24h|30m|YYYY-MM-DD] [--json]`：委任ログを config とサービスごとに集計します。
- `log outcome <id> --status pass|fail|abandoned [--duration S] [--rounds N] [--implementer TEXT] [--note TEXT]`：割り当ての記録に結果を追記します。`--duration` を省くと割り当てからの経過時間を使います。同じ ID に記録し直すと結果を置き換えます。
- `--version`：バージョンを出力します。

## `route` のオプション

`route` に付けられるオプションは次のとおりです。

- `--levels item=level,...`：要求する段（`none`/`low`/`mid`/`high`）を指定します。省略した項目は `none` になります。`--levels` 自体を省くと Jev が要求を見積もります。
- `--mode cheap|balanced|best|fast-balanced`：選ばれたサービス内で、全項目の要求を満たす（通過する）config から選ぶ方法を指定します。詳しくは[モードの表](#mode)を参照してください。
- `--explain`：判断の内容をすべて JSON で出力します。
- `--has-image`：`vision: false` の config を外します。
- `--input-tokens N`：N が `context_window_tokens` の 80% を超える config を外します。省略すると、入力のトークン数をタスクの文面から推定します。
- `--no-usage`：使用量を取得しません。全サービスの余りは 0 + `offset` になります。
- `--usage-file PATH`：`usage --json` のスナップショットを読み込みます。使用量の取得もキャッシュの保存もしません。
- `--jev-fixture PATH`：記録した Jev の応答を再生します。
- `--label TEXT`：ログにラベルを保存します。
- `--no-log`：ログを記録しません。
- `--print-log-id`：`<config> <service> <log-id>` を出力します。記録しなかったときの ID は `-` です。

<a id="mode"></a>
## `--mode`

次の表で、4 つのモードが config を選ぶ方法と、使いどころを比べます。

| モード | 選び方 | 使いどころ |
|---|---|---|
| `balanced`（既定） | 最安の config を選びます。費用が 1.25 倍以内で順位スコアが 0.05 以上高ければ乗り換えます | モード選びに迷ったときに使います |
| `cheap` | 最安の config を選びます | 短く軽い作業に向きます |
| `best` | 順位スコアが最高の config を選びます | 設計、難しい推論、調査に向きます |
| `fast-balanced` | 費用が 2.5 倍以内で、所要時間が半分以下の候補から最速の config に乗り換えます | 人が待っていて、多少の費用増は構わないときに使います |

表の用語の意味は次のとおりです。

- 費用：要求された項目の `cost_per_task` の合計です。すべての段が `none` なら全項目を合計します。
- 順位スコア：各項目のスコアの加重幾何平均です。重みには、要求する段に応じた `routing.level_weight` を使います。
- `level` で書いた項目のスコア：指定した段の閾値です。閾値が無ければ `H`/`M`/`L` = 1.0 / 2/3 / 1/3、`-` は 0 です。

## `--explain` のキー

`--explain` が出す JSON のキーは次のとおりです。

- `chosen`、`service`、`mode`、`fallback`：結果です。`fallback: true` は要求を緩めたことを示します。
- `levels` / `required`：`levels` は渡された段です。`required` は要求を緩めた後に適用した段です。
- `estimates`、`estimator`：項目ごとの見積もりと、その方法を示します。見積もりの方法は `fixed`、`jev`、`fixture` のいずれかです。
- `ranking`：全 config の `score`、`cost`、`passed`、`services`、`item_scores` などが入ります。候補から外れた理由は `reasons` で分かります。
- `thresholds`：項目ごとの閾値です。`level` だけで扱う項目は `null` です。
- `relaxations`：要求を下げた項目と変更前後の段を示します。緩和の各段階で落ちた config も入ります。
- `selection`：`cheapest_passing`、`chosen`、`score_delta`、`budget`、`traded_up`、`service` が入ります。`service` の中には `chosen`、`tier`、`surplus`、`tied_services` があります。
- `services`：各サービスの `status`、`tier`、`surplus`、`base`、`offset`、`ticket`、枠が入ります。`tier` は `normal`/`low_5h`/`exhausted` のいずれかです。
- `cost_basis`：通常は `requested_items` です。全項目の段が `none` なら `all_items` になります。
- `cost_items_requested`：段が `none` 以外の項目名のリストです。
- `usage_source`、`usage_fetched_at`：使用量の取得元と取得時刻です。取得元は `cache`、`fetched`、`file`、`none` のいずれかです。
- `task_tokens_estimate`、`warnings`、`log_id`：推定した入力の長さ、警告、ログ ID です。

## ファイル

次の表に、各ファイルの既定の場所と、保存先を変える方法を示します。

| ファイル | 既定の場所 | 上書き |
|---|---|---|
| 能力の定義 | `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` | `CAPABILITY_ROUTER_CAPABILITIES` |
| 生成される `criteria.md` | 定義ファイルと同じディレクトリ | `criteria --output` |
| カタログの各 `<config-id>.yaml` | `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` | `CAPABILITY_ROUTER_MODELS` |
| `pool.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml` | `CAPABILITY_ROUTER_POOL` |
| `services.yaml`（任意） | `${XDG_CONFIG_HOME:-~/.config}/capability-router/services.yaml` | `CAPABILITY_ROUTER_SERVICES` |
| `sanity.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml` | `CAPABILITY_ROUTER_SANITY` |
| 委任ログ | `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` | `CAPABILITY_ROUTER_LOG` で指定します。`off` なら記録しません |
| 使用量のキャッシュ（5 分） | `${XDG_CACHE_HOME:-~/.cache}/capability-router/usage.json` | `XDG_CACHE_HOME` |

<a id="capabilities"></a>
### `capabilities.yaml`

能力の定義に書くキーは次のとおりです。

- `version`：`3` です。
- `items.<item>.measures`：何を測るかを書きます。必須です。Jev の既定の質問にも使います。
- `items.<item>.excludes`：何を測らないかを書きます。必須です。
- `items.<item>.levels`：`none`/`low`/`mid`/`high` の説明文です。必須です。
- `items.<item>.examples`：`low`/`mid`/`high` ごとのアンカー問題のリストです。任意です。
- `items.<item>.question`：Jev の質問です。任意です。
- `items.<item>.thresholds`：`{low, mid, high}` の値を指定します。`0 <= low <= mid <= high <= 1` を満たす必要があります。いずれかの config が該当項目に `score` を使う場合は必須です。
- `routing.level_weight`：既定値は `{none: 0, low: 1, mid: 2, high: 3}` です。
- `routing.cost_band`、`routing.score_margin`：`balanced` の乗り換え条件です。既定値は 1.25、0.05 です。
- `routing.time_cost_band`、`routing.time_ratio`：`fast-balanced` の乗り換え条件です。既定値は 2.5、0.5 です。

### カタログファイル

1 つの config を表すカタログファイルのキーは次のとおりです。

- `id`、`model`：必須です。
- `effort`、`snapshot`：任意の自由記述です。
- `context_window_tokens`、`vision`：任意です。`--input-tokens`、`--has-image` の絞り込みに使います。
- `items.<item>.score` または `.level`：どちらか 1 つを書きます。`score` は 0..1 の数か `null` です。`level` は `H`/`M`/`L`/`'-'` です。`'-'` は引用符で囲みます。
- `items.<item>.cost_per_task`、`.time_per_task_s`：必須です。0 以上の値を書きます。単位は利用者が決めます。

### `pool.yaml`

config の実行先を書く `pool.yaml` のキーは次のとおりです。

- `configs.<id>.services`：`codex`/`claude`/`cursor`/`commandcode` から 1 つ以上をリストに書きます。カタログの全 config に必須です。同点なら先に書いたサービスを選びます。
- `configs.<id>.enabled`：既定値は `true` です。`false` ならファイルを消さずに config を外します。

### `services.yaml`

サービスの優先度を調整する `services.yaml` のキーは次のとおりです。

- `low_5h_percent`：既定値は 5 です。5 時間枠の残量を % で比べます。設定値以下のサービスは `low_5h` として後回しにします。
- `services.<id>.offset`：余りに足す点数です。
- `services.<id>.ticket`：`true` なら週枠の残量を % で表し、余りとして使います。

### `sanity.yaml`

`sanity` が読む `sanity.yaml` のキーは次のとおりです。

- `tasks`：`{id, label, levels}` のリストです。`levels` に書かない項目は `none` になります。

## 環境変数

`capability-router` が読み込む環境変数は次のとおりです。

- `CAPABILITY_ROUTER_CAPABILITIES`、`_MODELS`、`_POOL`、`_SERVICES`、`_SANITY`、`_LOG`：ファイルの場所を指定します。対象は「ファイル」の表で確認できます。
- `CAPABILITY_ROUTER_LOG_TASK=1`：タスクの文面をログに保存します。既定では保存しません。
- `CAPABILITY_ROUTER_CODEXBAR`：codexbar のコマンドを指定します。既定は `codexbar` です。
- `CAPABILITY_ROUTER_CURSOR_AUTH`：cursor-agent の認証ファイルを指定します。既定は `${XDG_CONFIG_HOME:-~/.config}/cursor/auth.json` です。
- `COMMAND_CODE_API_KEY`：Command Code の使用量の取得に使います。
- `TYPESAFE_API_KEY`：`--levels` を省いたときに、Jev の呼び出しに使います。
- `TYPESAFE_BASE_URL`、`TYPESAFE_DEFAULT_MODEL`：Jev の接続先とモデルを指定します。既定はそれぞれ `https://api.typesafe.ai` と `jev-latest` です。

## 補助スクリプト

`examples/` にある補助スクリプトは次のとおりです。

- `examples/levels_from_anchors.py RESULTS.yaml [--pass-rate 0.5]`：段ごとの正答率を `big-high: {sql: {low: 1.0, mid: 1.0, high: 0.75}}` の形式で渡します。カタログに書く `level` の行が出力されます。
- `examples/thresholds.py CATALOG_DIR DEFINITION [--tasks item=n,...]`：項目ごとの最高スコアから、仮置きの `thresholds` を出力します。

## 終了コード

終了コードは次のとおりです。

- `0`：タスクを割り当てられたときに返ります。要求を緩めて割り当てた場合も含みます。`usage` は取得に失敗したサービスがあっても 0 です。
- `1`：`route` で割り当てられる config が無いときに返ります。例えば、全サービスの枠を使い切った場合です。
- `2`：定義・カタログ・`pool.yaml` が無いか、正しく書かれていない場合に返ります。未知の項目や段、空のタスクも該当します。`TYPESAFE_API_KEY` が無い場合、Jev の HTTP エラー、`log outcome` の失敗でも返ります。

## 限界

- 通過する config が無ければ、要求を 1 項目ずつ下げます。割り当て後は終了コード 0 で返します。選ばれた config は元の要求を満たさないことがあります。
- 全サービスの枠が尽きたときは、要求を緩めず終了コード 1 で終わります。
- `--has-image` や入力長で全 config が外れると、全項目を `none` まで緩めます。警告付きで最良の config を返します。
- サービス ID は `codex`、`claude`、`cursor`、`commandcode` の 4 つだけです。
- 使用量を取得できないサービスも使えます。基準ペースどおりに使っているものとして、余りを 0 とします。
- サービス内の一部のモデルだけに適用される枠は無視します。
- 費用と時間は比較用の値です。全 config で同じなら選択に影響しません。
- カタログの時間から実際の所要時間は予測しません。
- `criteria.md` が古い場合は警告を出しますが、割り当ては続けます。
- 定義に無い項目はエラーになります。カタログに記載のない項目を要求されると、その config は候補から外れます。
- 文章の質を判断したい場合は、専用の項目を定義する必要があります。

開発者向け: [仕様](spec.ja.md)と[設計判断](design.ja.md)を参照してください。
