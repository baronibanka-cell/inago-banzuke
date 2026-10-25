# イナゴ番付

ミームコイン界隈の有名人が「この銘柄」と流したあと、実際に値段がどう動いたかを自動で記録し、人ごとに成績をランキングする個人用ツールです。費用はかかりません（GitHubの無料枠だけで動きます）。

- **Telegram**：公開チャンネルの投稿からSolanaのトークンアドレスを拾います（ログイン不要）
- **ウォレット**：本人の財布の売買をブロックチェーンから読みます
- **価格**：GeckoTerminalの無料APIで、投稿5分以内の価格から1時間・24時間・7日後の変化を計算します
- **画面**：スマホで見られるページ（GitHub Pages）

## はじめの設定（1回だけ）

1. **リポジトリを公開（Public）にする**
   無料プランでは、公開リポジトリならGitHub Pagesと自動実行が無制限に使えます。非公開にする場合は下の「非公開で使う場合」を見てください。
2. **ページを有効にする**
   Settings → Pages → Branch を `main`、フォルダを `/docs` にして Save。数分後に `https://<ユーザー名>.github.io/<リポジトリ名>/` で見られます。
3. **監視する人を書く**
   `config.yaml` を開き、鉛筆アイコンで編集して保存（Commit）します。保存すると自動で1回実行されます。
   - Telegramのチャンネル：`t.me/xxxx` の `xxxx` 部分
   - ウォレット：KolscanやGMGNなどで公開されている、その人のSolanaアドレス
4. **動いているか確認**
   Actions タブの「track」に緑のチェックが付けばOKです。以後15分ごとに自動で動きます。

## よくある質問

**データが出るまでどのくらい？**
初回にさかのぼって過去の投稿・取引も読みます。24時間・7日の数字は、その時間が経過してから埋まります。ランキングの並び順は、1人あたり3件以上の評価がたまってから付きます。

**ウォレットの読み込みが失敗する**
無料の公開ノードは混雑しやすく、GitHubのサーバーからの接続を断ることがあります。Heliusなどの無料アカウントで発行したRPCのURLを、Settings → Secrets and variables → Actions → New repository secret に `SOLANA_RPC_URL` という名前で登録すると安定します。

**非公開で使う場合**
非公開リポジトリの無料枠は月2,000分です。`.github/workflows/track.yml` の `*/15` を `*/30` に変えると収まります。GitHub Pagesは非公開リポジトリだと有料プランが必要なので、そのときは `docs/data.json` を直接見るか、Claudeに表示方法を相談してください。

**拾えないもの**
- 非公開・招待制のTelegramチャンネル
- Solana以外のチェーン（Base、Ethereumなど）
- アドレスを書かずに `$ティッカー` だけで紹介した投稿

## 仕組み

| ファイル | 役割 |
|---|---|
| `tracker/telegram.py` | 公開チャンネルのWeb版から投稿を読み、トークンアドレスを抜き出す |
| `tracker/solana.py` | ウォレットの取引を読み、買い・売りに分類する |
| `tracker/prices.py` | GeckoTerminalから値動きを取得して変化率を記録 |
| `tracker/report.py` | 人ごとの成績、「投稿前に購入」「投稿後に売却」の判定 |
| `docs/index.html` | ランキング画面 |
| `data/events.json` | 集めた記録すべて |

手元で動かす場合：`pip install -r requirements.txt` → `python -m tracker.main`
テスト：`python -m unittest discover tests`

過去の成績は将来の値動きを保証しません。投資判断はご自身の責任で行ってください。
