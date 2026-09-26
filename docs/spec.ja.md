# capability-router の仕様

[English](spec.md)

現在の動作とデータ形式を定めます。理由は[設計判断](design.ja.md)を参照してください。項目の定義・閾値・mode の設定値は `capabilities.yaml` が正本です。計算後の値は `capability-router models --detail` で確認できます。

## 用語は何を意味しますか

| 用語 | 意味 |
|---|---|
| config | model と reasoning effort の組。例は `example-small`。カタログの `<config-id>.yaml` 1 file に当たります。 |
| 項目 | 能力の軸です。利用者が `capabilities.yaml` で定義します。名前も数も利用者のものです。repo は項目を同梱しません。 |
| level | 項目ごとの要求またはカタログの段です。`none`、`low`、`mid`、`high` です。 |
| アンカー | 段を定義する短い例題です。`items.<item>.examples` に書きます。 |
| カタログ | config ごとに項目の値を持つ利用者の state です。動かすサービスは含みません。 |
| 項目の値 | config の 1 項目分の `score` (0..1) または `level` (`H`/`M`/`L`/`-`) と、`cost_per_task`、`time_per_task_s` です。 |
| 閾値 | `score` で書いた項目が段ごとに満たすべき score です。`items.<item>.thresholds` に利用者が書きます。 |
| pool | `pool.yaml` で有効にしたカタログの config です。候補になります。 |
| サービス | config の実行先です。`codex`、`claude`、`cursor`、`commandcode` に固定されます。id は `usage` の `services[].id` と同じです。一つの config が複数に属せます。 |
| 余り | 基準ペースに対する使用量の余裕です。単位は %pt です。 |
| サービスの段 | `normal`、`low_5h`、`exhausted` です。`exhausted` は選びません。 |
| 通過 | 要求した全項目の段を満たし、metadata filter も通ることです。 |

## route はどう処理しますか

0. **pool を作ります。** `pool.yaml` で有効な config と所属サービスを読みます。使用量からサービスの段と余りを求めます。
1. **metadata で絞ります。** `--has-image` があれば `vision: false` を外します。入力 token 数が `context_window_tokens` の 80% を超える config も外します。token 数は `--input-tokens` で渡すか、本文から ASCII 文字 ÷ 4 + その他 ÷ 1.5 で推定します。
2. **要求 level を決めます。** skill では呼び出し側の LLM が定義の全項目を見積もり、`--levels` で渡します。省略時は CLI が項目ごとの Score 質問を一度に Jev へ送り、項目ごとに最多確率の level を採ります。
3. **定義を適用します。** `none` 以外の項目で、config の値がその段を満たすかを見ます。`level` の値は要求段を覆う必要があります (`H` は `high` まで、`M` は `mid` まで、`L` は `low` まで、`-` は `none` だけ)。`score` の値はその段の閾値以上でなければなりません。要求項目に値の無い config は落ちます。所属サービスがすべて `exhausted` でも落ちます。
4. **必要なら緩めます。** 通過がゼロのときだけ、要求を 1 項目ずつ 1 段下げてやり直します。使用量で全候補が落ちた場合は緩めません。
5. **順位 score を付けます。** 要求 level を重みにした項目 score の加重幾何平均です。
6. **選びます。** 通過 config を持つサービスを段と余りで選び、その中で mode を適用します。

## 要求 level はどう入力しますか

| 経路 | 決める主体 |
|---|---|
| `--levels item=level,...` (skill) | 呼び出し側が生成済みの `criteria.md` を読み、全項目を見積もります。skill は常に渡します。 |
| `--levels` を省略 | CLI が項目ごとの Score 質問を Jev に送ります。`TYPESAFE_API_KEY` が必要です。 |

`--levels` は `item=level` を comma でつなぎます。書かなかった項目は `none` です。定義に無い項目名はエラーです。足切り以降の処理はどちらも同じです。

## 項目はどう定義しますか

項目はすべて利用者のものです。`capabilities.yaml` の各項目に、`measures`（測るもの）、`excludes`（測らないもの）、`none`/`low`/`mid`/`high` の `levels` の説明、段ごとの任意の `examples`、任意の Jev `question`、任意の `thresholds` を書きます。

段はその段のアンカー問題（`examples`）で定義します。`levels` の文章はアンカー問題を要約した説明です。需要側はタスクがその段のアンカー問題と同程度かを判断し、供給側は config がその段のアンカー問題を一定割合以上解けるかで満たすかを決めます。アンカーの無い段は文章だけで判断し、閾値は仮置きになります。`examples` の key は `low`/`mid`/`high` だけで、値は空でない文字列のリストです。

`question` を省略すると、Jev には次の文が渡ります。

```text
How much does this task require the following capability: <measures> Choose the lowest level that is sufficient.
```

段に `examples` があれば、Jev の `criteria` のその段の文の後に ` Examples: <a>; <b>.` が付きます。

## 項目の値と閾値をどう読みますか

カタログの config は項目ごとに `score` か `level` のどちらか一方を書きます。

- `score` は 0..1 の数、または「score なし」を表す `null` です。どこかの config が score で書く項目には、定義の `thresholds` が必要です。無ければ項目名を示して読み込みに失敗します。要求された score の項目は、score がその段の閾値以上なら通過します。
- `level` は `H`、`M`、`L`、`-` です。要求段を直接満たします。`H` は `high` まで、`M` は `mid` まで、`L` は `low` まで、`-` は `none` だけです。数値 score が要る場面（順位の幾何平均、`best`、`balanced` の `score_margin`）では、その段の閾値（`-` は 0）を score として使います。`thresholds` が無ければ固定値 `H` = 1.0、`M` = 2/3、`L` = 1/3、`-` = 0 を使います。

`thresholds` は `0 <= low <= mid <= high <= 1` を満たす必要があります。全 config が `level` で書く項目では省略できます。どこかの config が score で書く項目では必須です。pool 相対の閾値はありません。利用者の値は絶対値なので、カタログが変わっても動きません。

項目を書かない config は、その項目に値を持ちません。その項目を要求されると落ち、全項目 `none` の要求では cost が比較できません（後述）。定義に無い項目がカタログにあれば、config 名と項目名を示すエラーです。`benchmarks`、`evaluations`、`cost`、`performance` などの古い key を持つカタログは、その key 名を示すエラーです。互換読み込みはしません。

`capability-router models` は、有効な config ごとに各項目の性能を `H`、`M`、`L`、`-`、`?` で示します。`level` の項目はカタログの記号をそのまま出します。`score` の項目は、score が超えている最も高い段（`score >= 閾値`、足切りと同じ比較）を `H` / `M` / `L` とし、`low` 未満なら `-`、値が無ければ `?` です。表の下の凡例に項目の略号と記号の意味を出します。続いて有効・無効な config の数とサービスの所属を表示します。`capability-router models --detail` は、各 config と項目の score の数値、閾値（level だけで決まる項目は `-`）、項目の種別（`score` か `level`）、凡例を表示します。`--detail` と `--costs` は同時に指定できません。項目の列名は項目名の頭文字の略号で、表の下に `items: 略号=項目名, ...` の凡例を出します。段落はまとめて折り返します。stdout が端末のときは、列を端末幅に詰め、数値の列を右寄せにし、自由文の列と長い文は折り返します。自由文の列には読める最小幅を保ちます。識別子と数値の列は折り返さず切り詰めないため、収まらない表は端末幅を超えます。端末でないときは、1 レコードを 1 行のまま、罫線も色も付けません。

## 順位 score をどう計算しますか

要求 level の `level_weight` を重みにして、項目 score の加重幾何平均を求めます。`none` の重みはゼロです。項目 score には順位計算用の正の下限を適用し、欠けた項目は平均から外します。全項目が `none` なら全項目を等重みにします。緩和後も元の要求の重みを使います。

## cost と時間をどう計算しますか

カタログの config は項目ごとに `cost_per_task`（単位なし）と `time_per_task_s`（秒）を書きます。

- 選択に使う cost は、元の要求が `none` 以外の項目の `cost_per_task` の合計です。level の高さでは変わりません。緩和しても元の要求で計算します。
- 全項目が `none` なら、定義の全項目の合計を使います。`--explain` の `cost_basis` は `requested_items` か `all_items` です。
- 要求項目（全項目 `none` ならどれか 1 項目）に値が無ければ、その config に比較可能な cost はありません。部分和では比べません。
- `time_per_task_s` も同じように合計します。選択に使うのは `fast-balanced` だけです。
- cost は単位を持ちません。全 config で同じ値を書けば、無効化せずに比較を実質無効にできます。

## mode はどう選びますか

どの mode も足切りは同じです。mode は通過 config の選び方だけを変えます。

| mode | 選び方 |
|---|---|
| `cheap` | cost が最小です。同額なら順位 score が高い方です。 |
| `balanced` (既定) | 最安通過を基準にします。cost がその値 × `cost_band` 以下、順位 score が基準 + `score_margin` 以上の候補があれば、その中の最高 score に乗り換えます。無ければ最安通過です。 |
| `best` | 順位 score が最高の候補です。cost は見ません。 |
| `fast-balanced` | 最安通過を基準にします。cost が基準 × `time_cost_band` 以下、時間が基準 × `time_ratio` 以下なら、その中の最速に乗り換えます。同じ時間なら cost、次に順位 score で決めます。無ければ最安通過です。 |

`cheap` と `balanced` は cost の無い config を比較から外し、warnings に id を出します。`best` は選べます。通過候補すべてに cost が無ければ、`cheap` と `balanced` は順位 score の最高を選び、警告します。`fast-balanced` も cost の欠損を同様に扱います。時間の無い config は乗り換え先にしません。

## サービスと使用量をどう扱いますか

`route` は `usage --json` と同じ形の snapshot を読みます。5 分キャッシュします。個人の調整は `services.yaml` に置きます。

`windows[]` の枠ごとに次を適用します。

- `scoped: true` はサービス内の一部の model にだけかかるため、読みません。
- 残り 0% の枠があれば、サービスは `exhausted` です。
- `period: "5h"` は余りに含めません。残りが `low_5h_percent` 以下なら `low_5h` です。
- `week` と `month` の余りは期待使用率 − 実使用率 (%pt) です。期待使用率は経過時間 ÷ 枠の長さ × 100 を 0..100 に収めます。週は `resetsAt` の 7 日前、月は一か月前に始まります。同じ日が無ければ月末です。`fetchedAt` を現在時刻とします。`resetsAt` が無ければ余りに含めません。
- `ticket: true` の週枠は期待使用率を使わず、残り%を余りにします。0% なら同じく `exhausted` です。
- `period` の無い枠は残り 0% の判定だけに使います。

サービスの余りは週・月枠の余りの最小値 + `offset` です。対象の枠が無ければ 0 + `offset` です。`status` が `ok` 以外、snapshot に無い、または `--no-usage` のサービスは `normal`、余り 0 + `offset` です。

通過 config を `exhausted` 以外の所属サービスごとに見ます。`normal`、`low_5h` の順、同じ段では余りの大きい順です。最初のサービス内で mode を適用します。段と余りが同じサービスは一組にして mode を適用します。選んだ config が組内の複数サービスに属すれば、`pool.yaml` で先に書いた方を返します。使用量が無ければ全サービスが同じ組です。

## 通過候補が無いときどう緩めますか

要求項目を一つ選び、level を 1 段下げて足切りをやり直します。通過まで繰り返します。最も多くの config を落とす項目を選びます。同数なら要求 level が高い方、それも同じなら定義で先の項目です。

変更は `--explain` の `relaxations` と warnings に順に残り、`fallback: true` になります。通過後は通常どおり mode を使います。全項目が `none` でも通過しなければ、metadata filter で全員落ちた場合などを含め、`exhausted` 以外のサービスに属する全 config にサービス順と mode を適用し、警告します。全サービスが `exhausted` なら緩めず、選べる config はありません。

## route の option は何ですか

| option | 動作 |
|---|---|
| `--levels <item=level,...>` | 要求 level。省略時は Jev が推定します。 |
| `--mode <mode>` | `balanced` (既定)、`cheap`、`best`、`fast-balanced`。 |
| `--explain` | 判断全体を JSON で出します。 |
| `--has-image` | vision 非対応を外します。 |
| `--input-tokens <n>` | 入力長を明示します。省略時は本文から推定します。 |
| `--no-usage` / `--usage-file <path>` | 使用量の読み方を変えます。 |
| `--jev-fixture <file>` | 保存した Jev 応答を再生します。 |
| `--label <text>` / `--no-log` / `--print-log-id` | 委任の記録を制御します。 |

本文は引数か stdin で渡します。

## criteria コマンドは何をしますか

`capability-router criteria [--output PATH]` は、定義から LLM 向けの Markdown を生成します。既定では定義と同じ directory の `criteria.md` に書き、`--output -` は stdout、`--output PATH` はその path に書きます。

先頭行は `<!-- capability-router criteria: sha256=<定義 file の bytes の sha256> -->` です。本文は共通ルールに続けて、定義順に各項目を `### <項目>`、`Measures: ...`、`Excludes: ...`、`- none: ...` から `- high: ...` まで出します。`examples` のある段には、その段の行の下に `  - e.g. <例>` を 1 件 1 行で出します。

定義と同じ directory に `criteria.md` があり、その hash が定義と一致しなければ、`route` は stderr に warning を 1 行出します。route は止めません。`criteria.md` が無ければ何も出しません。

## route は何を出力しますか

- 通常は stdout に `<config id> <サービス id>` を 1 行出し、終了コードは 0 です。
- 選べる config が無ければ stderr に `error: no routable config` を出し、終了コードは 1 です。
- 本文が空、`--levels` の項目や level が不正、`TYPESAFE_API_KEY` が無い、Jev の HTTP エラーなどでは stderr に `error: ...` を出し、終了コードは 2 です。

| 使用量の option | 動作 |
|---|---|
| なし | 5 分以内の cache を読みます。無ければ 4 サービスから取得して更新します。 |
| `--usage-file <path>` | `usage --json` 形式の JSON を読みます。取得と cache は使いません。 |
| `--no-usage` | 使用量を読みません。全サービスが `normal`、余り 0 + `offset` です。 |

`--explain` は判断全体を JSON で出します。

| key | 内容 |
|---|---|
| `chosen` / `service` / `mode` / `fallback` | config とサービスの id、mode、緩和の有無。 |
| `levels` / `required` | 元の要求 level と緩和後に適用した level。 |
| `estimates` | 項目別の推定。Jev では level、確率分布、confidence、score。`--levels` では渡した level と確率 1.0 で、confidence と score はありません。 |
| `ranking` | 全 config を通過優先、順位 score 順に並べます。`score`、`cost`、`cost_items`、`time_per_task_s`、`passed`、`services`、`available_services`、`item_scores`、`reasons` が入ります。全サービスが `exhausted` なら `no service left (...)` です。 |
| `thresholds` | 定義の項目別閾値。level だけで決まる項目は `null` です。 |
| `relaxations` | 項目、元と先の level、その時点で落ちた config 数。 |
| `selection` | `balanced` では `cheapest_passing`、`chosen`、`score_delta`、`budget`、`traded_up`。`service` には選んだサービスの `chosen`、`tier`、`surplus`、`tied_services`。 |
| `services` | `status`、`tier`、offset 込みの `surplus`、適用前の `base`、`offset`、`ticket`、`windows` の `counted`、`expectedUsedPercent`、`surplus`、`reason`。段と余りの順に並びます。 |
| `usage_source` / `usage_fetched_at` | `cache`、`fetched`、`file`、`none` と snapshot の `fetchedAt`。 |
| `cost_basis` / `cost_items_requested` | `requested_items` か `all_items` と、cost の対象項目。 |
| `warnings` | 緩和、cost 欠損、balanced の予算など。 |
| `estimator` / `task_tokens_estimate` | `jev`、`fixed`、`fixture` と入力 token の推定値。 |

## 委任をどう記録しますか

`route` のたびに route record を追記します。呼び出し側は `log outcome` で同じ id に結果を追記します。routing は log を選択に使いません。タスクに組織の情報が含まれ得るため、本文は既定では保存しません。

置き場と `CAPABILITY_ROUTER_LOG` は[setup](setup.ja.md)を参照してください。`off` なら書きません。directory が無ければ作ります。JSONL の 1 行 1 record で、追記は `fcntl.flock` で排他します。`CAPABILITY_ROUTER_LOG_TASK=1` のときだけ `task` を含めます。

route record の key は次のとおりです。

| key | 内容 |
|---|---|
| `type` / `version` | `"route"` / `1` |
| `id` | `uuid4().hex` の先頭 12 文字 |
| `ts` | UTC の ISO 8601 |
| `label` | `--label`。無ければ `null` |
| `task` | 本文。`CAPABILITY_ROUTER_LOG_TASK=1` のときだけ key を入れます。 |
| `mode` | route の mode |
| `levels` | 元の要求のうち `none` 以外。入力または推定値です。 |
| `chosen` / `service` | 選んだ id。無ければ `null` |
| `fallback` | 緩和して選べば `true` |
| `cost` / `time_per_task_s` | 見込みの cost (小数 6 桁) と時間 (小数 1 桁)。無ければ `null` |

サービスの余り、緩和の詳細、cost の内訳、token 推定は log に残しません。`--explain` で確認してください。

同じ id の outcome record は複数あってもよく、集計では最後を使います。

| key | 内容 |
|---|---|
| `type` / `version` | `"outcome"` / `1` |
| `id` | 対応する route record の id |
| `ts` | 記録時刻 (UTC ISO 8601) |
| `status` | `pass`、`fail`、`abandoned` |
| `duration_s` | `--duration`。省略時は route の `ts` からの秒数 |
| `rounds` | 整数の `--rounds`。省略時は `null` |
| `implementer` | `--implementer`。省略時は `null` |
| `note` | `--note`。省略時は `null` |

### log の CLI は何ですか

- `route` は既定で記録し、`--label <text>`、`--no-log`、`--print-log-id` を受けます。通常の stdout は `<config id> <サービス id>` です。`--print-log-id` では `<config id> <サービス id> <log-id>` です。書かなかった場合、log-id は `-` です。`--explain` には `log_id` が入り、書かなければ `null` です。書き込み失敗でも routing は続け、stderr に `warning: delegation log not written: <理由>` を出します。選べなかった route も記録します。
- `sanity`、`models`、`criteria`、`usage` は記録しません。
- `log outcome <id> --status pass|fail|abandoned [--duration <秒>] [--rounds <n>] [--implementer <text>] [--note <text>]` を使います。route record の無い id は `unknown delegation id: <id>`、log が `off` でもエラーです。どちらも終了コード 2 です。
- `log [--since 7d|24h|30m|YYYY-MM-DD] [--json]` は route の `ts` で絞ります。config とサービスの組ごとに route 件数、outcome 件数、pass 率、`duration_s` と `rounds` の中央値を出し、最後に合計を出します。outcome が無ければ率と中央値は `-` です。`--json` は同じ集計を JSON で出します。壊れた行は飛ばし、数を stderr に出します。file が無ければ 0 件です。`off` は終了コード 2 です。

## Jev をどう呼びますか

- `POST {TYPESAFE_BASE_URL}/v1/systemone` を呼びます。既定は `https://api.typesafe.ai` です。`Authorization: Bearer $TYPESAFE_API_KEY` を付けます。model は `TYPESAFE_DEFAULT_MODEL` (既定 `jev-latest`)、timeout は 15 秒です。
- body は `{"state": <タスク本文>, "model": ..., "questions": {<項目>: {"type": "score", "instructions": <question>, "criteria": [<none>, <low>, <mid>, <high>]}}}` です。質問文と段の説明は定義から組み立て、候補 config やその model 名は含めません。
- `answers.<項目>.probabilities` の最大の段を採ります。確率が無ければ `score` を丸めます。一項目でも答えが欠ければエラーです。

## usage は何を返しますか

`capability-router usage` は 4 サービスの上限の残りを取得し、正規化します。`capabilities.yaml` とカタログは読みません。取得した snapshot は `route` 用の cache に保存します。

- 4 サービスを並行に取得し、各サービスを 30 秒で打ち切ります。一つの失敗は他を止めません。
- 失敗はサービスの `status` に入れ、終了コードは 0 のままです。引数の誤りなど CLI 自体の失敗だけが非 0 です。
- `--json` は下の形式を stdout に出します。省略時は枠、残り%、補充時刻 (local time)、詳細を表にします。失敗したサービスは status と理由を示します。

### 出力 JSON はどんな形ですか


| key | 内容 |
|---|---|
| `fetchedAt` | 取得開始の UTC ISO 時刻。ミリ秒付きで全サービス共通です。 |
| `services[].id` / `name` | `codex` / Codex、`claude` / Claude Code、`cursor` / Cursor Pro、`commandcode` / Command Code。この順で必ず 4 件です。 |
| `services[].status` | `ok`、試行後に失敗した `error` (HTTP、認証切れ、timeout、JSON 不正)、前提の無い `unavailable` (コマンド、auth file、API key) です。 |
| `services[].message` | `error` / `unavailable` のサニタイズ済み理由です。 |
| `services[].plan` | 分かる場合のプラン名です。現在は Command Code の `planId` です。 |
| `services[].windows[]` | 枠の残りです。`ok` 以外では空です。label は `5h` (300 分)、`週` (10080 分)、`月`、その他は元の title や `<分>分` です。`remainingPercent` は 0..100 の四捨五入した整数、`resetsAt` は不明なら `null` です。長さが分かれば `period` は `5h`、`week`、`month` です。一部 model だけの枠は `scoped: true`、金額枠だけ `detail` を持ちます。 |
| `services[].credits` | Command Code の月枠を作れない場合だけ、月クレジットの残高 (USD、小数 2 桁) を出します。対象は未知の `planId` や inactive な契約です。 |

message は出力前にサニタイズします。制御文字を空白にし、メールアドレス、`sk-` などの token、`Bearer ...`、`token=`、`api_key=`、`secret=`、`password=`、`authorization=` の値、長い英数字列を `[redacted]` に置き換えます。内部の `/a/b` 形式の path は `[internal path]` にし、160 文字で切ります。空なら `取得に失敗しました` です。token、メールアドレス、account id は出しません。外部コマンドの stderr は捨て、log も書きません。

### 各サービスからどう取得しますか

| サービス | 取得 | 認証 |
|---|---|---|
| Codex / Claude Code | `codexbar usage --provider <codex または claude> --source oauth --json-only` を実行します。stdout で `[` から始まる最初の有効な JSON 行を使います。先頭要素の `usage.primary` / `secondary` / `tertiary` (`{usedPercent, windowMinutes, resetsAt}` または null) と `usage.extraRateWindows[]` (`{title, window}`。label は title の先頭 24 文字) を枠にします。`error` field や非 0 の終了コードなら `error` です。 | codexbar に任せます。 |
| Cursor Pro | `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage`、body `{}` です。`planUsage.remaining` / `limit` (セント) で月枠を作り、残り% = remaining / limit、`resetsAt` = `billingCycleEnd` (ms) です。`totalPercentUsed` は読みません。 | cursor-agent の `auth.json` の `accessToken` を Bearer で送ります。`refreshToken` は使いません。 |
| Command Code | `GET https://api.commandcode.ai/alpha/whoami?limits=1` で org id を取り、`/alpha/billing/credits?orgId=` と `/alpha/billing/subscriptions?orgId=` を並行に読みます。`credits.windowLimits.fiveHour` / `weekly` の `used` / `cap` (USD) と `resetAt` (ms) で短期・週枠を作ります。月枠は次の計算です。 | `COMMAND_CODE_API_KEY` を Bearer で送ります。 |

Command Code の月枠は CLI の `/usage` と同じ計算です。subscription の `data.status` が `active` で、`planId` が `usage.py` の `COMMAND_CODE_PLAN_CREDITS` にあるときだけ作ります。`planId` を小文字にし、`_` を `-` に変えて、長いキーから前方一致で探します。上限は max(プランの月付与, `monthlyCredits`) + `purchasedCredits` + `freeCredits` です。残りは `monthlyCredits` + `purchasedCredits` + `freeCredits`、補充は `currentPeriodEnd` です。

### キャッシュをどう使いますか

最後のサニタイズ済み snapshot を `${XDG_CACHE_HOME:-$HOME/.cache}/capability-router/usage.json` に置きます。token やメールアドレスは含みません。`route` は `fetchedAt` から 5 分未満なら読み、古いか読めなければ取得して上書きします。書けない場合は警告せず、取得結果だけ使います。`usage` は常に取得して上書きします。

### 環境変数で何を指定しますか

file の置き場と上書きは[setup](setup.ja.md)を参照してください。`CAPABILITY_ROUTER_CODEXBAR` は codexbar のコマンド (既定 `codexbar`) を、`CAPABILITY_ROUTER_CURSOR_AUTH` は cursor-agent の auth file を指定します。`COMMAND_CODE_API_KEY` が無ければ Command Code は `unavailable` です。`CAPABILITY_ROUTER_LOG_TASK=1` のときだけ route record に本文を入れます。

## data file は何を定義しますか

### `capabilities.yaml` は何を定義しますか

| key | 内容 |
|---|---|
| `version` | `3` である必要があります。 |
| `levels` | 低い順の level。省略できますが、書くなら `[none, low, mid, high]` ちょうどです。 |
| `items.<項目>.measures` | その項目が測るもの。必須で空不可。Jev 質問文の既定にもなります。 |
| `items.<項目>.excludes` | その項目が測らないもの。必須で空不可。 |
| `items.<項目>.levels` | `none`、`low`、`mid`、`high` の説明。必須です。 |
| `items.<項目>.examples` | 段ごとの任意のアンカーです。key は `low`/`mid`/`high` のみで、値は空でない文字列のリストです。 |
| `items.<項目>.question` | 任意の Jev 質問文。無ければ `measures` から既定文を作ります。 |
| `items.<項目>.thresholds` | 任意の `low`/`mid`/`high` の 0..1 の数で、`low <= mid <= high` です。どこかの config が score で書く項目では必須です。 |
| `routing.level_weight` | level ごとの順位の重み。既定は `{none: 0, low: 1, mid: 2, high: 3}` です。 |
| `routing.cost_band` / `score_margin` | `balanced` の乗り換え条件。既定は 1.25 / 0.05 です。 |
| `routing.time_cost_band` / `time_ratio` | `fast-balanced` の乗り換え条件。既定は 2.5 / 0.5 です。 |

`axes`、`benchmarks`、top-level の `thresholds` などの古い key を持つ file は、その key 名を示して読み込みに失敗します。互換読み込みはしません。項目を足すときは `items` とカタログの全 config を更新します。router コードの変更は要りません。

### カタログは何を持ちますか (`<config-id>.yaml`)

置き場と `CAPABILITY_ROUTER_MODELS` は[setup](setup.ja.md)を参照してください。repo には置かず、`/models/` は `.gitignore` に入っています。repo が配るのは `examples/models/` の架空の config だけです。directory が無ければ `route`、`models`、`sanity` が探した path と上書き変数を示し、終了コード 2 で終わります。

| key | 内容 |
|---|---|
| `id` / `model` | config id と model 名。必須です。 |
| `effort` / `snapshot` | 自由記述です。任意です。 |
| `context_window_tokens` / `vision` | metadata filter に使います。任意です。 |
| `items.<項目>.score` | 0..1 の数、または `null`。`score` か `level` のどちらか一方です。 |
| `items.<項目>.level` | `H`、`M`、`L`、`'-'`。`score` か `level` のどちらか一方です。 |
| `items.<項目>.cost_per_task` | 単位なし、0 以上。必須です。 |
| `items.<項目>.time_per_task_s` | 秒、0 以上。必須です。 |

block 記法では最下段を `'-'` と引用符で囲みます。引用符の無い dash は YAML の sequence の始まりとして読まれ、解析に失敗します。

```yaml
items:
  coding:
    level: '-'
```

エラーは config 名と項目名を示します。`score` と `level` の両方、どちらも無し、範囲外の score、未知の level 記号、`cost_per_task` や `time_per_task_s` の欠落、定義に無い項目です。`benchmarks`、`evaluations`、`cost` などの古い key を持つ file は、その key 名を示して読み込みに失敗します。

### `pool.yaml` は何を持ちますか

カタログの有効な config と所属サービスを指定します。置き場は[setup](setup.ja.md)を参照してください。repo の `/pool.yaml` は `.gitignore` に入っています。架空の例は `examples/pool.yaml` です。

```yaml
configs:
  example-small: {services: [codex]}                 # 複数なら [codex, cursor]
  example-spare: {services: [commandcode], enabled: false}
```

| key | 内容 |
|---|---|
| `configs.<config id>.services` | サービス id の list です。空、重複、未知の id はエラーです。同じ組なら先に書いたサービスを選びます。 |
| `configs.<config id>.enabled` | 省略時は `true` です。`false` は pool から外します。 |

カタログの全 config を書きます。書き漏れ、カタログに無い config、他の key は終了コード 2 のエラーです。`pool.yaml` が無くても終了コード 2 で、探した path と `CAPABILITY_ROUTER_POOL` を示します。

### services 設定は何を持ちますか

サービスごとの個人の調整で、repo には置きません。file が無ければ既定値です。`low_5h_percent` は短期枠を後回しにする残量、`services.<service id>.offset` は余りへの加算、`services.<service id>.ticket` は週枠の扱いです。置き場は[setup](setup.ja.md)を参照してください。

未知のサービス id、`offset` / `ticket` 以外の key、数値でない `offset`、真偽値でない `ticket`、0..100 の外の `low_5h_percent` は終了コード 2 のエラーです。

### `sanity.yaml` は何を持ちますか

利用者の固定 level のケース集です。既定は `${XDG_CONFIG_HOME:-~/.config}/capability-router/sanity.yaml`、または `CAPABILITY_ROUTER_SANITY` です。各ケースは `id`、短い `label`、項目名から level への map `levels` を持ちます。書かない項目は `none` です。本文や期待 config は持ちません。定義に無い項目や未知の level はケースを示して終了コード 2 です。repo が配るのは `examples/sanity.yaml` だけで、例の項目向けのケースを載せています。

`capability-router sanity` はその level で route します。option は `--mode` (既定 `balanced`) と `--json` です。表には `id`、`label`、`none` 以外を略した `levels` (例: `coding: low` は `c=l`)、`chosen`、`service`、`cost/task`、緩和の有無が出ます。下に選ばれた config の種類数、緩和したケース数と内容が出ます。期待値との照合はしません。使用量と services 設定を読まないため、全サービスが同じ組です。`service` は選んだ config の `pool.yaml` で先頭のものです。`--json` は `{"mode": ..., "results": [{id, label, levels, chosen, service, cost_per_task, time_per_task_s, fallback, relaxations}]}` を出します。
