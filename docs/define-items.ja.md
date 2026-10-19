# 能力項目を定義する

タスクの要求を見積もり、config の能力を測るための項目を `capabilities.yaml` に書きます（[理由](how-it-works.ja.md#items)、[インストール手順](start.ja.md)）。

## 手順

1. 次のコマンドで、項目定義のテンプレートを既定の場所にコピーします。
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; mkdir -p "$d" && cp examples/capabilities.template.yaml "$d/capabilities.yaml"
   ```
2. `my_item` を自分の項目に置き換え、段ごとに 4 問ほどのアンカー問題を付けます（項目名にモデル名やベンチマーク名は使いません）。次は SQL の項目を書いた例です。
   ```yaml
   sql:
     measures: Writing correct SQL queries for a given schema.
     excludes: Database administration and tuning.
     levels: {none: No SQL is written., low: A single-table filter., mid: Joins and aggregation., high: Window functions that must be exactly right.}
     examples: {low: [Count rows in a date range.], mid: [Monthly revenue per customer.], high: [Retention cohorts.]}
   ```
3. 次のコマンドで基準を生成して開きます。2 つの段に当てはまりそうなタスクがあれば、段の違いが明確になるようアンカー問題を直します（編集のたびに再実行します）。
   ```sh
   less "$(capability-router criteria)"
   ```

## 条件ごとの書き方

- 文章（提案書、報告書）を任せられる config だけに割り当てたい：文章の項目を作り、各カタログファイルに手で `level` を書きます（任せない config は `'-'`）。
- 公開ベンチマークから作る：難易度別の問題を各段のアンカー問題にし、全体の正答率だけなら `score` にします（[項目の値を決める](register-configs.ja.md#values)）。
