# 委任の結果を記録する

委任ごとの config・サービス・結果を記録し、後で見直します。

## 前提

- `route` を実行できる設定（[エージェントに config を選ばせて委任する](delegate-from-an-agent.ja.md)）

## 手順

1. 次のコマンドで、ラベルを付けてタスクを割り当て、ログ ID も受け取ります（`-` なら記録されていません）。
   ```sh
   read config service log_id < <(capability-router route --levels "$LEVELS" --label "retry handling" --print-log-id "task text")
   ```
2. 委任が終わったら、次のコマンドで受け取ったログ ID に結果を記録します。
   ```sh
   capability-router log outcome "$log_id" --status pass --rounds 1 --implementer "codex:exec" --note "needed one fix"
   ```
3. 次のコマンドで、直近 7 日の記録を集計して確かめます。
   ```sh
   capability-router log --since 7d
   ```
   config とサービスごとに、割り当て数、成功率、所要時間の中央値などが出ます。
