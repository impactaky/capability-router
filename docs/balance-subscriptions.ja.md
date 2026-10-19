# サブスクリプションの使用量をならす

`route` は、Codex、Claude Code、Cursor (Pro)、Command Code の中で枠の余りが最も大きいサービスを優先します。[余りでサービスを選ぶ理由](how-it-works.ja.md#service-first)も参照してください。

## 前提

- `pool.yaml` に config と実行先のサービスを書きます。手順は[config を登録する](register-configs.ja.md)を参照してください。
- `codex`、`claude` の使用量を取得するには、`codexbar` を入れて各 CLI で OAuth ログインします。
- `cursor` の使用量を取得するには、`cursor-agent` にログインします。
- `commandcode` の使用量を取得するには、`COMMAND_CODE_API_KEY` を設定します。

## 手順

1. 次のコマンドで、サービスごとに取得できる使用量を確かめます。
   ```sh
   capability-router usage
   ```
   サービスごとに枠の残量が % で表示されます。取得できなければ `unavailable`/`error` と理由が出ます。使用量が分からないサービスは、基準ペースどおりに使っているものとして扱います。
2. 次のコマンドで、使用量を取得してタスクを割り当てます。出力されたサービスの順位を確認します。
   ```sh
   capability-router route --no-log --explain --levels "$LEVELS" "task text"
   ```
   `services` に各サービスの `tier` と `surplus`、`selection.service.chosen` に選ばれたサービスが出ます。

## 優先度を調整する

1. 次のコマンドは、`services.yaml` で `cursor` の余りに 20 点を足す例です。設定後に手順 2 をもう一度実行します。
   ```sh
   echo '{services: {cursor: {offset: 20}}}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/services.yaml"
   ```
