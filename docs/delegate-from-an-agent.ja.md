# エージェントに config を選ばせて委任する

LLM エージェントに、委任ごとに config とサービスを選んで起動してもらいます。[エージェントが要求を見積もる理由](how-it-works.ja.md#caller-estimates)も参照してください。

## 前提

- [config を登録](register-configs.ja.md)し、`capability-router models` で一覧が出る状態にします。最新の `criteria.md` も用意します。`capability-router` が `PATH` 上に無ければ、[どこからでも実行する手順](start.ja.md#path)に従ってインストールします。
- エージェントに同梱のスキルを入れます。例えば `cp -r skills/capability-router ~/.claude/skills/` でコピーします。

## 手順

1. エージェントに「capability-router で次のタスクに使う config を選んで：<タスク>」と頼みます。エージェントは全項目の段を見積もります。`none` の項目も含めて次のコマンドに渡し、config とサービスを受け取ります。
   ```sh
   read config service < <(capability-router route --levels coding=mid,long_context=low,writing=none "<タスク>")
   ```
2. エージェントは、選ばれた config のカタログファイルから `model` と `effort` を読み、`$service` を起動します。[呼び出し側が起動する理由](how-it-works.ja.md#ids-only)も参照してください。選択が意外なら、[理由の調べ方](check-routing.ja.md#inspect)に沿って確かめます。

タスクに応じて、`route` に次のオプションを足します。

- 画像を含む場合は `--has-image` を付けます。
- 添付などで入力がタスクの文面より長くなる場合は、`--input-tokens <n>` を付けます。
- 費用・正しさ・待ち時間のどれかを重視する場合は、`--mode` を指定します。選び方は[モードの一覧](reference.ja.md#mode)を参照してください。

<a id="jev"></a>
## エージェントなしで割り当てる（Jev）

1. 次のコマンドでは `--levels` を省きます。外部 API の Jev が、タスクの文面だけから要求を見積もります。`--explain` の `estimator` は `jev` になります。
   ```sh
   export TYPESAFE_API_KEY=... && capability-router route --explain "<タスク>"
   ```
