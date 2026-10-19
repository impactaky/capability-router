# 割り当てを確かめる

[English](check-routing.md)

自分の定義・カタログ・`pool.yaml` を使い、タスクにどの config が選ばれるかを確かめます。選択の理由も確認します。設定の準備は[config を登録する](register-configs.ja.md)を参照してください。

## 手順

1. 次のコマンドで、自分で割り当ての良し悪しを判断できるケースを `sanity.yaml` に書きます。省略した項目は `none` になります。
   ```sh
   echo '{tasks: [{id: q1, label: simple count, levels: {sql: low}}, {id: q2, label: cohorts, levels: {sql: high}}]}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/sanity.yaml"
   ```
2. 次のコマンドで基準を作り直し、全ケースを割り当てます。使用量は考慮しません。割り当てが誤っていたら、アンカー問題・カタログの値・閾値のどれかを直して再実行します。
   ```sh
   capability-router criteria && capability-router sanity
   ```
3. 次のコマンドで、実際のタスクの要求を 1 件渡して割り当てます。判断の内容をすべて JSON で確認します。
   ```sh
   capability-router route --no-usage --no-log --explain --levels sql=mid "task text"
   ```

<a id="inspect"></a>
## 意外な選択の理由を知る

`--explain` の出力を、当てはまる状況に応じて確認します。

- `fallback: true` の場合：`relaxations` を確認します。通過する config が無いため、要求を 1 項目ずつ緩めています。選ばれた config は元の要求を満たさないことがあります。
- 想定より大きな config が選ばれる場合：`balanced` での乗り換えは `selection.traded_up` を確認します。サービスの選択は `selection.service` で確認します。[余りの大きいサービスを優先する仕組み](how-it-works.ja.md#service-first)も参照してください。
- 一度も選ばれない config がある場合：`ranking` 内の該当 config の `reasons` を確認します。スコアと閾値は `capability-router models --detail` で表示できます。
- 費用が選択に影響しない場合：`capability-router models --costs` で確かめます。費用が同じ config は金額では区別できません。項目が欠けた config は `cheap`/`balanced` の候補から外れます。
- 乗り換えが多すぎる、または少なすぎる場合：`capabilities.yaml` の `routing` を調整します。設定できるキーは[一覧](reference.ja.md#capabilities)を参照してください。
