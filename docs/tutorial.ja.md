# 手順: 自分の能力項目を作る

[English](tutorial.md)

capability-router は能力項目を同梱しません。この手順では、架空の `examples/` を完成形の見本として、1 から項目を作ります。これは手順書で、script ではありません。コマンドは自分で実行し、YAML は手で編集します。

`examples/` の定義・カタログ・アンカー・閾値は、すべて下と同じ形で書いています。値は架空で、測ったものではありません。

## 考え方: 段はアンカー問題で決まる

**段**は、その段で解けるアンカー問題で定義します。`capabilities.yaml` の `levels` の文章は、そのアンカー問題を要約した説明です。タスクの要求は、そのタスクが段のアンカー問題とどれくらい近いかで判断します。config は、その段のアンカー問題を一定割合以上解ければその段を満たします。

`examples` の無い段は文章だけで判断します。許されますが、その閾値は測定ではなく仮置きです。書けるところではアンカーを用意してください。

## 流れ A: アンカーから `level` へ

### 1. 項目を 1 つ決める

自分にとって重要で、文章だけでは読み方が割れる能力を 1 つ選びます。model 名や tool 名ではなく、測るものの名前を付けます。

### 2. アンカー問題を段ごとに 4 問ほど書き、段の札を付ける

段ごとに小さな問題を 4 問ほど、項目全体で 12 問ほど書き、それぞれに `low` / `mid` / `high` の札を付けます。

- `low`: 明らかな 1 手。答えの確認が簡単。
- `mid`: 複数手、または注意が要る 1 手。確認はできる。
- `high`: その項目の難しい端。正しく解くこと自体が成果物。

YAML に置けるよう、短い要約にします。段ごとに 4 問にすると正答率が 0.25 刻みになります。

### 3. 段の文章と `examples` を書く

要約を項目の `examples` に置き、`levels` の文章は各群の要約として書きます。例:

```yaml
items:
  coding:
    measures: 与えられた仕様やアルゴリズムを正確にコードとして実装すること。
    excludes: 文章成果物の仕上がり。
    levels:
      none: コードを書かない。
      low: 明らかな数行の変更。
      mid: 関数や module を仕様どおりに実装し、test で確かめる。
      high: 数値計算や複雑なアルゴリズムを仕様の細部まで正確に実装する。
    examples:
      low:
        - 既存のループの off-by-one エラーを直す。
        - 関数引数に不足した既定値を足す。
        - 空の入力リストでも例外を出さずに処理する。
        - 1 file 内で記号の名前を一貫させる。
      mid:
        - 検証と test を備えた設定 loader を実装する。
        - 再試行を備えたページ送り API client の method を足す。
        - 入力引数を key に計算結果を cache する。
        - 小さな CSV を型付き record に読み込み、誤りを報告する。
      high:
        - 数値的に安定な行列分解を仕様どおりに実装する。
        - 小さな文法の parser を誤り回復付きで実装する。
        - hunk の境界が正しい diff アルゴリズムを実装する。
        - backpressure 付きの並行 worker pool を実装する。
```

そのあと `capability-router criteria` を実行し、`criteria.md` を読んで、文章とアンカーが意図どおりかを確かめます。

### 4. 各 config に全アンカーを解かせ、正答率を記録する

各 config にアンカー問題を解かせ、段ごとの正答率を `examples/anchor-results.yaml` と同じ形の file に記録します。

```yaml
example-large:
  coding: {low: 1.0, mid: 0.75, high: 0.5}
example-mid:
  coding: {low: 1.0, mid: 0.5, high: 0.25}
```

### 5. カタログに `level` を書く

補助 script を実行するか、規則を手で適用します。

```sh
python examples/levels_from_anchors.py anchor-results.yaml --pass-rate 0.5
```

規則: `low` から順に見て、正答率が `--pass-rate` 以上で、かつ下の段も満たす最も高い段を採ります。`low` が未達なら `low` すら満たさないので `-` です。script は config の `items` に貼る行を出力します。

```yaml
items:
  coding: {level: H}
```

何も満たさない config は `-` です。block 記法では `'-'` と引用符で囲みます。引用符の無い dash は YAML の sequence の始まりとして読まれ、解析に失敗します。

```yaml
items:
  coding:
    level: '-'
```

### 6. cost と時間を手で記録する

全項目に `cost_per_task` と `time_per_task_s` を書きます。単位は自分で決めます。測れないときは全 config に同じ値を書きます。同じ値なら無効化せずに比較を実質無効にでき、後で実測値に差し替えられます。

## 流れ B: score と閾値

正答率を数値で測れるときは、`level` ではなく `score` で書きます。

1. 各 config に問題全体を解かせ、解けた割合を 0..1 で求めます。これがカタログの `score` です。
2. 定義のその項目に `thresholds` を書きます。手で決めるか、`examples/thresholds.py` の仮置きの規則を使います。

   ```sh
   python examples/thresholds.py models/ capabilities.yaml --tasks coding=10,long_context=10
   ```

   script はカタログの項目別最高 score から `low = best / 3`、`high = best - 2 × SE`（問題数が不明なら `best × 0.9`）、`mid` を中間点として提案します。問題数が 10 問程度では標準誤差が大きく、`high` は `low` の近くまで下がります。結果は仮置きとして扱います。

3. 要求された `score` の項目は、score が閾値以上なら通過します。`thresholds` のある `level` の項目は `H`/`M`/`L` を `high`/`mid`/`low` の値に対応させ、無ければ固定の `1.0` / `2/3` / `1/3` を使います。

## 公開 benchmark を使う

公開 benchmark からアンカーを作り、定義には benchmark 名を書かないこともできます。

- 難易度の分割（例: `easy` / `medium` / `hard`）があれば、各分割を 1 つのアンカー群として流れ A を使います。各分割から標本を選んで `low` / `mid` / `high` の札を付け、分割ごとの正答率を記録し、カタログに `level` を書きます。
- 全体の正答率しか無ければ、その正答率を `score` として流れ B を使います。難易度の分割が無いのでアンカーは無く、閾値は仮置きです。`examples/thresholds.py` の pool 相対の規則を出発点にします。

項目の `measures` と `excludes` は capability の言葉で書き、benchmark の言葉では書きません。benchmark は測定器であって、定義ではありません。

## sanity で確かめる

どちらの流れでも、段の文章と閾値、カタログの対応を `capability-router sanity` で確かめます。`sanity.yaml` に目で判断できるケースを数件書き、route して、割り当てと緩和が期待どおりに読めるかを見ます。納得するまでアンカー・段の文章・閾値を直します。sanity は読みであって、合否の test ではありません。

## 基準を最新に保つ

`capabilities.yaml` を変えたら `capability-router criteria` を実行します。定義の隣に `criteria.md` を書きます。一致しなくなると `route` が warning を 1 行出します。warning を出すだけで止めはしないので、見たら次の見積もりの前に `criteria.md` を作り直します。
