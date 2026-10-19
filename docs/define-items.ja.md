# 能力項目を定義する

[English](define-items.md)

タスクの要求を見積もり、config の能力を測るための項目を `capabilities.yaml` に書きます。[項目を定義する理由](how-it-works.ja.md#items)と[インストール手順](start.ja.md)も参照してください。

## 手順

1. 次のコマンドで、項目を定義するためのテンプレートを既定の場所にコピーします。
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; mkdir -p "$d" && cp examples/capabilities.template.yaml "$d/capabilities.yaml"
   ```
2. `my_item` を自分の項目に置き換えます。各段に 4 問ほどのアンカー問題を付けます。項目名にはモデルやベンチマークの名前を使いません。次は SQL の項目の例です。
   ```yaml
   sql:
     measures: Writing correct SQL queries for a given schema.
     excludes: Database administration and tuning.
     levels: {none: No SQL is written., low: A single-table filter., mid: Joins and aggregation., high: Window functions that must be exactly right.}
     examples: {low: [Count rows in a date range.], mid: [Monthly revenue per customer.], high: [Retention cohorts.]}
   ```
3. 次のコマンドで基準を生成して開きます。タスクが 2 つの段に当てはまりそうなら、違いが分かるようにアンカー問題を直します。編集するたびに同じコマンドを実行します。
   ```sh
   less "$(capability-router criteria)"
   ```

## 条件ごとの書き方

- 提案書や報告書などの文章を任せられる config だけに割り当てたい場合：文章の項目を作り、各カタログファイルに手で `level` を書きます。任せない config には `'-'` を指定します。
- 公開ベンチマークを使う場合：難易度ごとの問題を各段のアンカー問題にします。全体の正答率しか分からなければ `score` を使います。詳しくは[項目の値の決め方](register-configs.ja.md#values)を参照してください。
