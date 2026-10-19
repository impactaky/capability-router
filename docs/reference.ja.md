# リファレンス

## コマンド

`capability-router` のサブコマンドは次のとおりです。

- `route [options] ["task"]`：引数か標準入力で受け取るタスクに対して `<config id> <service id>` を出力します。委任ログを 1 件記録します。
- `models [--detail | --costs]`：config と項目ごとの `H`/`M`/`L`/`-`/`?`、費用と時間の合計、サービスを出力します。`--detail` ではスコアと閾値を、`--costs` では項目ごとの費用と時間を出力します。
- `sanity [--mode M] [--json]`：使用量と `services.yaml` を無視して、`sanity.yaml` の全ケースを割り当てます。
- `criteria [--output PATH]`：定義の隣に `criteria.md` を書き出します。保存先のパスを出力します。`--output -` なら標準出力に書き出します。
- `usage [--json]`：サービスごとの残量を取得してキャッシュを更新します。
- `log [--since 7d|24h|30m|YYYY-MM-DD] [--json]`：委任ログを config とサービスごとに集計します。
- `log outcome <id> --status pass|fail|abandoned [--duration S] [--rounds N] [--implementer TEXT] [--note TEXT]`：割り当ての記録に結果を追記します。`--duration` を省くと割り当てからの経過時間を使います。同じ ID に記録し直すと結果を置き換えます。
- `--version`：バージョンを出力します。

## `route` のオプション

`route` に付けられるオプションは次のとおりです。

- `--levels item=level,...`：要求する段（`none`/`low`/`mid`/`high`）を指定します。書かない項目は `none` です。オプションを省くと Jev に見積もらせます。
- `--mode cheap|balanced|best|fast-balanced`：選んだサービス内で、要求の全項目を満たす（通過する）config からの選び方を指定します（[下表](#mode)）。
- `--explain`：判断全体を JSON で出力します。
- `--has-image`：`vision: false` の config を外します。
- `--input-tokens N`：N が `context_window_tokens` の 80% を超える config を外します。オプションを省くとタスクの文面から推定します。
- `--no-usage`：使用量を取得しません。全サービスの余りは 0 + `offset` になります。
- `--usage-file PATH`：`usage --json` のスナップショットを読み込みます。使用量の取得もキャッシュの保存もしません。
- `--jev-fixture PATH`：記録した Jev の応答を再生します。
- `--label TEXT`：ログにラベルを保存します。
- `--no-log`：ログを記録しません。
- `--print-log-id`：`<config> <service> <log-id>` を出力します。記録しなかったときの ID は `-` です。

<a id="mode"></a>
## `--mode`

次の表は、4 つのモードの選び方と向く場面を比べたものです。

| モード | 選び方 | 向く場面 |
|---|---|---|
| `balanced`（既定） | 最安を選びます。費用が 1.25 倍以内で順位スコアが 0.05 以上高ければ乗り換えます | 選び方に迷ったときに使います |
| `cheap` | 最安を選びます | 短く軽い作業に向きます |
| `best` | 順位スコアが最高の config を選びます | 設計、難しい推論、調査に向きます |
| `fast-balanced` | 費用が 2.5 倍以内で時間が半分以下の最速の config に乗り換えます | 人が待っていて、多少の費用増は構わないときに使います |

表の用語の意味は次のとおりです。

- 費用：要求された項目の `cost_per_task` の合計です（全項目 `none` なら全項目を合計します）。
- 順位スコア：項目スコアの加重幾何平均です。重みは要求する段の `routing.level_weight` です。
- `level` で書いた項目のスコア：指定した段の閾値です。閾値が無ければ `H`/`M`/`L` = 1.0 / 2/3 / 1/3、`-` は 0 です。

## `--explain` のキー

`--explain` が出す JSON のキーは次のとおりです。

- `chosen`、`service`、`mode`、`fallback`：結果です。`fallback: true` は要求を緩めたことを示します。
- `levels` / `required`：渡された段 / 緩和後に適用した段です。
- `estimates`、`estimator`：項目ごとの見積もりと、見積もり元（`fixed`、`jev`、`fixture`）です。
- `ranking`：全 config の `score`、`cost`、`passed`、`services`、`item_scores`、落ちた理由の `reasons` などです。
- `thresholds`：項目ごとの閾値です。`level` だけで読む項目は `null` です。
- `relaxations`：下げた項目、変更前後の段、緩和の各段階で落ちた config です。
- `selection`：`cheapest_passing`、`chosen`、`score_delta`、`budget`、`traded_up`、`service`（`chosen`、`tier`、`surplus`、`tied_services`）です。
- `services`：サービスごとの `status`、`tier`（`normal`/`low_5h`/`exhausted`）、`surplus`、`base`、`offset`、`ticket`、枠です。
- `cost_basis`、`cost_items_requested`：`requested_items`、または全項目の段が `none` なら `all_items` です。
- `usage_source`、`usage_fetched_at`：`cache`、`fetched`、`file`、`none` のいずれかと、取得時刻です。
- `task_tokens_estimate`、`warnings`、`log_id`：推定入力長、警告、ログ ID です。

## ファイル

次の表は、各ファイルの既定の場所と、場所を変える方法です。

| ファイル | 既定の場所 | 上書き |
|---|---|---|
| 能力の定義 | `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` | `CAPABILITY_ROUTER_CAPABILITIES` |
| `criteria.md`（生成物） | 定義の隣 | `criteria --output` |
| カタログ（`<config-id>.yaml` 群） | `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` | `CAPABILITY_ROUTER_MODELS` |
| `pool.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/pool.yaml` | `CAPABILITY_ROUTER_POOL` |
| `services.yaml`（任意） | `${XDG_CONFIG_HOME:-~/.config}/capability-router/services.yaml` | `CAPABILITY_ROUTER_SERVICES` |
| `sanity.yaml` | `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml` | `CAPABILITY_ROUTER_SANITY` |
| 委任ログ | `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl` | `CAPABILITY_ROUTER_LOG`（`off` で無効） |
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
- `items.<item>.thresholds`：`{low, mid, high}` を `0 <= low <= mid <= high <= 1` で書きます。いずれかの config で該当項目を `score` で書くなら必須です。
- `routing.level_weight`：既定値は `{none: 0, low: 1, mid: 2, high: 3}` です。
- `routing.cost_band`、`routing.score_margin`：`balanced` の乗り換え条件です。既定値は 1.25、0.05 です。
- `routing.time_cost_band`、`routing.time_ratio`：`fast-balanced` の乗り換え条件です。既定値は 2.5、0.5 です。

### カタログファイル

1 つの config を表すカタログファイルのキーは次のとおりです。

- `id`、`model`：必須です。
- `effort`、`snapshot`：任意の自由記述です。
- `context_window_tokens`、`vision`：任意です。`--input-tokens`、`--has-image` の絞り込みに使います。
- `items.<item>.score` または `.level`：どちらか 1 つを書きます。0..1 の `score`（または `null`）か、`H`/`M`/`L`/`'-'`（引用符必須）の `level` です。
- `items.<item>.cost_per_task`、`.time_per_task_s`：必須です。0 以上の値を書きます。単位は利用者が決めます。

### `pool.yaml`

config の実行先を書く `pool.yaml` のキーは次のとおりです。

- `configs.<id>.services`：`codex`/`claude`/`cursor`/`commandcode` の空でないリストです。カタログの全 config に必須です。同点なら先に書いたサービスを選びます。
- `configs.<id>.enabled`：既定値は `true` です。`false` ならファイルを消さずに config を外します。

### `services.yaml`

サービスの優先度を調整する `services.yaml` のキーは次のとおりです。

- `low_5h_percent`：既定値は 5 です。5 時間枠の残り% が設定値以下のサービスを後回しにします（`low_5h`）。
- `services.<id>.offset`：余りに足す点数です。
- `services.<id>.ticket`：`true` なら週枠の残り% を余りとして使います。

### `sanity.yaml`

`sanity` が読む `sanity.yaml` のキーは次のとおりです。

- `tasks`：`{id, label, levels}` のリストです。書かない項目は `none` です。

## 環境変数

読む環境変数は次のとおりです。

- `CAPABILITY_ROUTER_CAPABILITIES`、`_MODELS`、`_POOL`、`_SERVICES`、`_SANITY`、`_LOG`：ファイルの場所を指定します（上記）。
- `CAPABILITY_ROUTER_LOG_TASK=1`：タスクの文面をログに保存します（既定では保存しません）。
- `CAPABILITY_ROUTER_CODEXBAR`：codexbar のコマンドを指定します（既定は `codexbar` です）。
- `CAPABILITY_ROUTER_CURSOR_AUTH`：cursor-agent の認証ファイルを指定します（既定は `${XDG_CONFIG_HOME:-~/.config}/cursor/auth.json` です）。
- `COMMAND_CODE_API_KEY`：Command Code の使用量の取得に使います。
- `TYPESAFE_API_KEY`：`--levels` を省いたときの Jev に使います。
- `TYPESAFE_BASE_URL`、`TYPESAFE_DEFAULT_MODEL`：Jev の接続先とモデルを指定します（既定は `https://api.typesafe.ai` と `jev-latest` です）。

## 補助スクリプト

`examples/` にある補助スクリプトは次のとおりです。

- `examples/levels_from_anchors.py RESULTS.yaml [--pass-rate 0.5]`：`big-high: {sql: {low: 1.0, mid: 1.0, high: 0.75}}` 形式の段ごとの正答率から、カタログの `level` 行を出力します。
- `examples/thresholds.py CATALOG_DIR DEFINITION [--tasks item=n,...]`：項目ごとの最高スコアから、仮置きの `thresholds` を出力します。

## 終了コード

終了コードは次のとおりです。

- `0`：割り当てができたときです（緩和後を含みます）。`usage` は取得に失敗したサービスがあっても 0 です。
- `1`：`route` で割り当てられる config が無いときです（例：全サービスの枠が尽きた）。
- `2`：定義・カタログ・`pool.yaml` が無いか不正、未知の項目や段、空のタスク、`TYPESAFE_API_KEY` が無い、Jev の HTTP エラー、`log outcome` の失敗の場合です。

## 限界

- 通過する config が無ければ要求を 1 項目ずつ下げ、終了コード 0 で返します。元の要求を満たさないことがあります。
- 全サービスの枠が尽きたときは、要求を緩めず終了コード 1 で終わります。
- `--has-image` や入力長で全 config が外れると、全項目を `none` まで緩めます。警告付きで最良の config を返します。
- サービス ID は `codex`、`claude`、`cursor`、`commandcode` の 4 つだけです。
- 使用量を取得できないサービスも使えます。基準ペースどおり（余り 0）として扱います。
- サービスの一部のモデルにだけかかる枠は無視します。
- 費用と時間は比較用の値です。全 config で同じなら選択に影響しません。
- カタログの時間から実際の所要時間は予測しません。
- `criteria.md` が古くても警告を出すだけで、割り当ては続けます。
- 定義に無い項目はエラーになります。項目を書かない config は、記載の無い項目を要求されると候補から外れます。
- 文章の質を判断するには、文章の質を測る項目の定義が必要です。

開発者向け: [仕様](spec.ja.md)と[設計判断](design.ja.md)を参照してください。
