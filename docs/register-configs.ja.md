# config を登録する

config（モデルと推論の強さの組）ごとにカタログファイルを書き、実行先のサービスを `pool.yaml` に書きます。

## 前提

- 自分の `capabilities.yaml`（[能力項目を定義する](define-items.ja.md)）
- 各モデルにアンカー問題を解かせる手段

## 手順

1. 次のコマンドは、config `big-high` のカタログファイルと、実行先を書いた `pool.yaml` を作る例です（項目の値は[項目の値を決める](#values)に従って決めます）。
   ```sh
   m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"; mkdir -p "$m"
   echo '{id: big-high, model: Big Model, effort: high, items: {sql: {level: H, cost_per_task: 3, time_per_task_s: 60}}}' > "$m/big-high.yaml"
   echo '{configs: {big-high: {services: [claude]}}}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/pool.yaml"
   ```
2. 次のコマンドで、登録した config の一覧を確かめます。
   ```sh
   capability-router models
   ```
   有効な config ごとに、項目の `H`/`M`/`L`/`-`、費用と時間の合計、サービスが 1 行で出ます。

<a id="values"></a>
## 項目の値を決める

- 段ごとのアンカー問題の正答率がある：`level: H`/`M`/`L`/`'-'` を書きます。`python examples/levels_from_anchors.py anchor-results.yaml --pass-rate 0.5` で `level` 行を出力します。
- 項目ごとの 0..1 の数（問題集やベンチマークの正答率）がある：`score: 0.62` と、`capabilities.yaml` の該当項目の `thresholds` を書きます。`python examples/thresholds.py <カタログ> <capabilities.yaml> --tasks sql=10` で仮の `thresholds` を出力します。
- 費用や時間をまだ測っていない：全 config に同じ `cost_per_task`・`time_per_task_s` を書きます。
