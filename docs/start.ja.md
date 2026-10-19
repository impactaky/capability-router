# インストールして最初のタスクを割り当てる

capability-router を動かし、同梱の架空の例で最初のタスクを割り当てます。実際に使う定義やカタログを含めない理由は、[仕組み](how-it-works.ja.md#items)で説明しています。

## 前提

- Python 3.11 以上と [uv](https://docs.astral.sh/uv/) を用意します。`git clone https://github.com/impactaky/capability-router.git && cd capability-router` でリポジトリを取得し、そのディレクトリに移動します。

## 手順

1. 次のコマンドで、同梱の例を既定の場所にコピーします。続けて、見積もりの基準となる `criteria.md` を生成します。
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"
   mkdir -p "$d" "$m" && cp examples/{capabilities,sanity,pool}.yaml "$d/" && cp examples/models/*.yaml "$m/"
   uv run capability-router criteria
   ```
2. 次のコマンドで、要求の軽いタスクと重いタスクを 1 件ずつ割り当てます。使用量は取得せず、ログも記録しません。
   ```sh
   uv run capability-router route --no-usage --no-log --levels coding=low "Fix an off-by-one error"
   uv run capability-router route --no-usage --no-log --levels coding=high "Implement a diff algorithm"
   ```
   結果はそれぞれ `example-small codex` と `example-large claude` です。要求を満たす最安の config と実行先のサービスを表します。

<a id="path"></a>
## どこからでも実行する

1. 次のコマンドで `PATH` 上にインストールします。バージョンが表示されることを確かめます。コマンドが見つからなければ、`uv tool update-shell` を実行してシェルを開き直します。
   ```sh
   uv tool install -e . && capability-router --version
   ```
