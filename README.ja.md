# capability-router

- LLM エージェントや利用者が、タスクを任せるモデルと推論の強さの組（config）を自分の基準で選べます。
- 複数の定額 AI サブスクリプションを契約している人が、委任する作業を残量の多いサブスクリプションに振り分けられます。
- プロンプトルーター（RouteLLM、OpenRouter Auto など）と違い、利用者が定義した能力項目で選びます。学習済みの分類器は使いません。モデルは呼び出さず、ID だけを返します。

次のコマンドは、タスクに必要な段を渡して、使う config と実行先のサービスを1行で受け取る例です。

```sh
capability-router route --levels coding=mid,long_context=low "Add retry handling to the API client"
```

同梱の架空の例では、`example-mid cursor` のような1行が返ります。

## 仕組み

1. **物差しを利用者が作ります。** 能力項目とその段をアンカー問題で定め、タスクと config を同じ段で比べます。
2. **呼び出し側の LLM が要求を見積もります。** 会話やリポジトリを見ているエージェントが、全項目の段を決めて渡します。
3. **サブスクリプションの余りでサービスを先に選びます。** 各サブスクリプションを、枠の期間に合わせて均等なペースで使います。
4. **モデルを呼び出さず、選ぶだけにします。** 受け取った ID は、どんな起動方法でも使えます。

詳しく: [仕組み](docs/how-it-works.ja.md)

## 何をしたいですか？

**始める・自分の基準を書く**
- [インストールして最初のタスクを割り当てる](docs/start.ja.md)：同梱の架空の例で試します。
- [能力項目を定義する](docs/define-items.ja.md)：項目ごとに段とアンカー問題を決めます。
- [config を登録する](docs/register-configs.ja.md)：config ごとの能力・費用・実行先を書きます。
- [割り当てを確かめる](docs/check-routing.ja.md)：割り当てと、意外な選択の理由を見ます。

**タスクを委任する**
- [エージェントに config を選ばせて委任する](docs/delegate-from-an-agent.ja.md)：エージェントが要求を見積もり、選ばれた config で起動します。
- [エージェントなしで割り当てる](docs/delegate-from-an-agent.ja.md#jev)：スクリプトから、外部 API の Jev に見積もらせます。
- [サブスクリプションの使用量を均す](docs/balance-subscriptions.ja.md)：余りの大きいサービスを優先させます。
- [委任の結果を記録する](docs/log-delegations.ja.md)：委任ごとの担当と結果を後で見直せます。

リファレンス: [コマンド、オプション、ファイル、環境変数、終了コード、限界](docs/reference.ja.md)
