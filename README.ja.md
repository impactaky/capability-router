# capability-router

[English](README.md)

capability-router は、タスクを別の LLM に任せるための CLI です。呼び出し側の LLM が、利用者が定義した能力項目ごとに要求を `none` / `low` / `mid` / `high` で指定します。要求を満たす config と実行先のサービスを選びます。config は model と reasoning effort（推論の強さ）の組です。

能力項目は**利用者が定義**します。repo は項目も、カタログの値も、評価データも同梱しません。`capabilities.yaml` に項目・段・アンカー問題・閾値を書き、カタログに config ごとの score または level、cost、time を書きます。

## どう使うか

Python 3.11 以上と [uv](https://docs.astral.sh/uv/) を用意します。`--levels` に `項目=段階` を渡します。省いた項目は `none` です。次は `examples/` の架空の定義とカタログで試す例です。

```sh
CAPABILITY_ROUTER_CAPABILITIES=examples/capabilities.yaml \
CAPABILITY_ROUTER_MODELS=examples/models \
CAPABILITY_ROUTER_POOL=examples/pool.yaml \
  uv run capability-router route --no-usage --no-log --levels coding=low "x"
```

```text
example-small codex
```

`--no-usage` は使用量の取得を、`--no-log` は委任ログの記録を省くために付けています。`--levels` を省くと外部 API の Jev に推定を任せるため、`TYPESAFE_API_KEY` が必要です。

## 実際に使うまで

1. **前提を用意する。** Python 3.11 以上と uv をインストールします。実行方法は [setup.md](docs/setup.ja.md) を参照してください。
2. **項目を定義する。** `examples/capabilities.template.yaml` を `${XDG_CONFIG_HOME:-~/.config}/capability-router/capabilities.yaml` にコピーし、自分の項目を書きます。アンカー問題・段・閾値の作り方は [tutorial.md](docs/tutorial.ja.md) を参照してください。
3. **カタログを作る。** `${XDG_STATE_HOME:-~/.local/state}/capability-router/models/` に config ごとの YAML を作り、項目ごとに 1 つの値を書きます。形式は [spec.md](docs/spec.ja.md) を参照してください。
4. **`pool.yaml` を作る。** config をサービスに結び付けます。置き場は [setup.md](docs/setup.ja.md)、形式は [spec.md](docs/spec.ja.md) を参照してください。
5. **`criteria.md` を作る。** `capability-router criteria` を実行し、呼び出し側の LLM が読む基準を生成します。[SKILL.md](skills/capability-router/SKILL.md) (英語) を参照してください。
6. **使用量の取得を設定する（任意）。** [setup.md](docs/setup.ja.md) に前提と確認方法があります。サービス id は `codex` / `claude` / `cursor` / `commandcode` の 4 つに固定されています。取得ツールが 1 つも無くても `route` は動き、各サービスを余り 0 の `normal` として扱います。
7. **skill を使う。** [SKILL.md](skills/capability-router/SKILL.md) (英語) に配置方法と呼び出し方があります。

## 項目をどう定義するか

項目はアンカー問題で定義します。タスクがその項目の `low` のアンカー問題と同程度の要求なら `low`、というように判断します。config は、その段のアンカー問題を一定割合以上解ければその段を満たします。`levels` の文章はアンカー問題を要約した説明です。アンカー問題の無い段は文章だけで判断し、閾値は仮置きになります。詳しくは [tutorial.md](docs/tutorial.ja.md) を参照してください。

```yaml
items:
  coding:
    measures: 与えられた仕様やアルゴリズムを正確にコードとして実装すること。
    excludes: 文章成果物の仕上がり。
    levels: {none: ..., low: ..., mid: ..., high: ...}
    examples:
      low: [既存のループの off-by-one エラーを直す。]
      mid: [検証と test を備えた設定 loader を実装する。]
      high: [数値的に安定な行列分解を仕様どおりに実装する。]
    thresholds: {low: 0.3, mid: 0.5, high: 0.7}
```

カタログの config は、項目ごとに `score` (0..1) **または** `level` (`H`/`M`/`L`/`-`) を 1 つ書き、`cost_per_task` と `time_per_task_s` を必ず書きます。

```yaml
id: example-large
model: Example Large
effort: high
items:
  coding: {level: H, cost_per_task: 1.0, time_per_task_s: 30}
  long_context: {score: 0.8, cost_per_task: 1.0, time_per_task_s: 30}
```

## 候補からどうやって 1 つ選ぶか

```text
要求 + 利用できる config
  ↓
画像・入力長で候補を絞る
  ↓
足切り：要求に届かない config を除く
  ↓
サービスの使用量で実行先を選ぶ
  ↓
そのサービス内で --mode に従って config を選ぶ
  ↓
config id + サービス id
```

使用量以外で候補がなければ、要求を段階的に緩めます。`--mode` は足切りを通った config の選び方です。

| `--mode` | 選び方 |
|---|---|
| `balanced`（既定） | 最安を基準に、一定の費用内で能力が十分上がれば最高得点 |
| `cheap` | 費用が最も低い |
| `best` | 要求項目の総合点が最も高い |
| `fast-balanced` | 最安を基準に、一定の費用内で時間が十分縮めば最速 |

## 詳細はどこにあるか

- [自分の項目を作る手順](docs/tutorial.ja.md)
- [agent 向け手順](skills/capability-router/SKILL.md) (英語)
- [仕様](docs/spec.ja.md)
- [セットアップ](docs/setup.ja.md)
- [設計判断](docs/design.ja.md)
