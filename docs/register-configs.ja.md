# config を登録する

config はモデルと推論の強さの組です。config ごとにカタログファイルを作ります。実行先のサービスは `pool.yaml` に書きます。

## 前提

- 自分の `capabilities.yaml` を用意します。作り方は[能力項目を定義する](define-items.ja.md)を参照してください。
- 各モデルにアンカー問題を解かせる手段を用意します。

## 手順

1. 次のコマンドは、config `big-high` のカタログファイルと、実行先を指定する `pool.yaml` を作る例です。項目の値は[値の決め方](#values)に従って記入します。
   ```sh
   m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"; mkdir -p "$m"
   echo '{id: big-high, model: Big Model, effort: high, items: {sql: {level: H, cost_per_task: 3, time_per_task_s: 60}}}' > "$m/big-high.yaml"
   echo '{configs: {big-high: {services: [claude]}}}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/pool.yaml"
   ```
2. 次のコマンドで、登録した config の一覧を確かめます。
   ```sh
   capability-router models
   ```
   有効な config ごとに 1 行ずつ表示されます。各行には項目の段を表す `H`/`M`/`L`/`-`、費用と時間の合計、サービスが並びます。

<a id="values"></a>
## 項目の値を決める

- 各段のアンカー問題の正答率が分かる場合：`level: H`/`M`/`L`/`'-'` を書きます。`python examples/levels_from_anchors.py anchor-results.yaml --pass-rate 0.5` を実行すると、`level` の行が出ます。
- 問題集やベンチマークの正答率が、項目ごとに 0..1 の数で分かる場合：`score: 0.62` のように書きます。`capabilities.yaml` の該当項目には `thresholds` が必要です。`python examples/thresholds.py <カタログ> <capabilities.yaml> --tasks sql=10` を実行すると、仮の `thresholds` が出ます。
- 費用や時間をまだ測っていない場合：全 config に同じ `cost_per_task`・`time_per_task_s` を書きます。
