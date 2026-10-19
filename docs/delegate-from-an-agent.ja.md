# エージェントに config を選ばせて委任する

LLM エージェントに、委任ごとに config とサービスを選ばせて起動させます（[エージェントが見積もる理由](how-it-works.ja.md#caller-estimates)）。

## 前提

- `capability-router models` で一覧が出る設定一式（[config を登録する](register-configs.ja.md)）と最新の `criteria.md`、`PATH` 上の `capability-router`（無ければ[どこからでも実行する](start.ja.md#path)）
- 同梱のスキルを置いたエージェント（例：`cp -r skills/capability-router ~/.claude/skills/`）

## 手順

1. エージェントに「capability-router で次のタスクに使う config を選んで：<タスク>」と頼みます。エージェントは `none` を含む全項目を見積もり、次のコマンドで config とサービスを受け取ります。
   ```sh
   read config service < <(capability-router route --levels coding=mid,long_context=low,writing=none "<タスク>")
   ```
2. エージェントは、選ばれた config のカタログファイルにある `model` と `effort` で `$service` を起動します（[自分で起動する理由](how-it-works.ja.md#ids-only)）。選択が意外なら、[意外な選択の理由を知る](check-routing.ja.md#inspect)で確かめます。

タスクに応じて、`route` に次のオプションを足します。

- 画像を含む：`--has-image`
- 添付などで、タスクの文面より入力が長い：`--input-tokens <n>`
- 費用・正しさ・待ち時間のどれかを重視する：`--mode`（[一覧](reference.ja.md#mode)）

<a id="jev"></a>
## エージェントなしで割り当てる（Jev）

1. 次のコマンドでは `--levels` を省いて、外部 API の Jev にタスクの文面だけから見積もらせます（`--explain` の `estimator` が `jev` になります）。
   ```sh
   export TYPESAFE_API_KEY=... && capability-router route --explain "<タスク>"
   ```
