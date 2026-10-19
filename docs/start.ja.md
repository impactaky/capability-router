# インストールして最初のタスクを割り当てる

capability-router を動かし、同梱の架空の例で最初のタスクを割り当てます（[実物を同梱しない理由](how-it-works.ja.md#items)）。

## 前提

- Python 3.11 以上、[uv](https://docs.astral.sh/uv/)、リポジトリのクローン（`git clone https://github.com/impactaky/capability-router.git && cd capability-router`）

## 手順

1. 次のコマンドで、同梱の例を既定の場所にコピーし、見積もりの基準（`criteria.md`）を生成します。
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; m="${XDG_STATE_HOME:-$HOME/.local/state}/capability-router/models"
   mkdir -p "$d" "$m" && cp examples/{capabilities,sanity,pool}.yaml "$d/" && cp examples/models/*.yaml "$m/"
   uv run capability-router criteria
   ```
2. 次の 2 つのコマンドで、要求の軽いタスクと重いタスクを、使用量の取得とログの記録を省いて割り当てます。
   ```sh
   uv run capability-router route --no-usage --no-log --levels coding=low "Fix an off-by-one error"
   uv run capability-router route --no-usage --no-log --levels coding=high "Implement a diff algorithm"
   ```
   要求を満たす最安の config と実行先として、`example-small codex` と `example-large claude` が出ます。

<a id="path"></a>
## どこからでも実行する

1. 次のコマンドで `PATH` 上にインストールします。バージョンが出ることを確かめます（見つからなければ `uv tool update-shell` のあとシェルを開き直します）。
   ```sh
   uv tool install -e . && capability-router --version
   ```
