# 委任の結果を記録する

[English](log-delegations.md)

委任ごとの config・サービス・結果を記録し、後で見直します。

## 前提

- `route` を実行できるように設定します。手順は[エージェントに config を選ばせて委任する](delegate-from-an-agent.ja.md)を参照してください。

## 手順

1. 次のコマンドで、タスクにラベルを付けて割り当てます。結果にはログ ID も含まれます。ID が `-` なら記録されていません。
   ```sh
   read config service log_id < <(capability-router route --levels "$LEVELS" --label "retry handling" --print-log-id "task text")
   ```
2. 委任した作業が終わったら、次のコマンドで結果を記録します。割り当て時に受け取ったログ ID を指定します。
   ```sh
   capability-router log outcome "$log_id" --status pass --rounds 1 --implementer "codex:exec" --note "needed one fix"
   ```
3. 次のコマンドで、直近 7 日間の記録を集計して確認します。
   ```sh
   capability-router log --since 7d
   ```
   config とサービスごとに、割り当て数、成功率、所要時間の中央値などが出ます。
