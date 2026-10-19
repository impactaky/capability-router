# 割り当てを確かめる

自分の定義・カタログ・`pool.yaml`（[config を登録する](register-configs.ja.md)）で、どんなタスクにどの config が割り当たるかと、その理由を見ます。

## 手順

1. 次のコマンドで、自分で判断できるケースを `sanity.yaml` に書きます（書かない項目は `none`）。
   ```sh
   echo '{tasks: [{id: q1, label: simple count, levels: {sql: low}}, {id: q2, label: cohorts, levels: {sql: high}}]}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/sanity.yaml"
   ```
2. 次のコマンドで、基準を作り直してから、使用量を無視して全ケースを割り当てます。割り当てが誤っていたら、アンカー問題・カタログの値・閾値のどれかを直してやり直します。
   ```sh
   capability-router criteria && capability-router sanity
   ```
3. 次のコマンドで、実際の要求を 1 件渡して割り当てます。判断全体を JSON で見ます。
   ```sh
   capability-router route --no-usage --no-log --explain --levels sql=mid "task text"
   ```

<a id="inspect"></a>
## 意外な選択の理由を知る

`--explain` の出力を、当てはまる状況に応じて確認します。

- `fallback: true`：`relaxations` を見ます。通過する config が無いため、要求を 1 項目ずつ下げています。元の要求を満たさないことがあります。
- 想定より高い config：`selection.traded_up`（`balanced` の乗り換え）か、`selection.service`（[余りの大きいサービスが先](how-it-works.ja.md#service-first)）を見ます。
- 一度も選ばれない config：`ranking` 内の該当 config の `reasons` を見ます。スコアと閾値は `capability-router models --detail` で出ます。
- 費用が効かない：`capability-router models --costs` を見ます。費用が等しいと選択に差が付きません。項目が欠けた config は `cheap`/`balanced` で外されます。
- 乗り換えが多すぎる・少なすぎる：`capabilities.yaml` の `routing` のキー（[一覧](reference.ja.md#capabilities)）を調整します。
