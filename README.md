# warikan

友達グループの立て替えを記録し、**できるだけ少ない送金回数で精算する方法**を提示するWebアプリです。

- 公開URL: https://warikan-94kv.onrender.com/
- API ドキュメント: https://warikan-94kv.onrender.com/docs

> 無料プランで動かしているため、しばらくアクセスがないと停止します。最初の表示に 30 秒ほどかかることがあります。

## なぜ作るのか

友達と遊んだあと、誰がいくら立て替えたかを覚えておき、最後に精算するのが毎回面倒でした。人数や支払いの回数が増えるほど、誰が誰にいくら払えばよいかを計算するのが難しくなります。そこで、支払いを記録するだけで、できるだけ少ない送金回数で精算する方法が分かるアプリを作りました。グループの URL を送るだけで、アカウント登録なしにみんなで使えるようにしています。

## 技術スタック

| 役割 | 技術 | 選んだ理由 |
| --- | --- | --- |
| API | FastAPI (Python) | Flask の経験を活かしつつ、型ヒントによる入力検証と OpenAPI ドキュメント自動生成を使いたかったため |
| DB | PostgreSQL + SQLAlchemy 2.0 / Alembic | トランザクションと制約(CHECK・外部キー)で金額データの整合性を守るため。スキーマ変更は Alembic のマイグレーションで管理 |
| テスト | pytest | |
| CI | GitHub Actions | Lint とテストを PR ごとに自動実行 |
| 画面 | HTML + 素の JavaScript | ビルド不要で FastAPI からそのまま配信できるため |

## 設計メモ

### 金額の扱い
- 金額はすべて **円単位の int** で保持し、float は使わない(誤差防止)。
- 均等割りで割り切れない端数は、**対象メンバーの先頭から 1 円ずつ**多く負担する。
  - 例: 1000 円を 3 人 → 334 / 333 / 333

### データの保存
| テーブル | 内容 |
| --- | --- |
| `groups` | 友達グループ。ID は推測されにくいランダム文字列(22 文字) |
| `members` | グループのメンバー。グループ内で名前は一意 |
| `payments` | 立て替え 1 件(金額は `CHECK (amount > 0)`) |
| `payment_shares` | 誰がいくら負担するかの内訳。入力順(`position`)も保存 |

- 負担額の内訳は**登録時に確定して保存**する。端数ルールを後から変えても過去の支払いは変わらない。
- 支払いと内訳は 1 トランザクションで保存し、片方だけ残ることがないようにしている。
- 支払いに関わっているメンバーは削除できない(API は 409、DB も外部キー `RESTRICT` で拒否)。
- 認証はまだ無く、グループの URL を知っている人が読み書きできる「URL が合言葉」方式。

### API
| メソッド | パス | 内容 |
| --- | --- | --- |
| POST | `/groups` | グループ作成(メンバーも同時に登録可) |
| GET | `/groups/{id}` | グループ・メンバー・支払いの一覧 |
| POST / DELETE | `/groups/{id}/members[/{member_id}]` | メンバーの追加・削除 |
| POST / DELETE | `/groups/{id}/payments[/{payment_id}]` | 支払いの登録・削除 |
| GET | `/groups/{id}/settlement` | 保存済みの支払いから精算結果を計算 |
| POST | `/settlements/preview` | DB を使わず、送った支払いだけで精算 |

### 画面
- `/` でグループを作ると `/g/{グループID}` に移動する。この URL を友達に送って共有する。
- 支払いは記録した時点で保存され、精算結果は変更のたびに自動で計算し直す。
- 他の人の更新は、タブに戻ってきたとき(`visibilitychange`)に読み直して反映する。
- 最近開いたグループはブラウザ(localStorage)に記録。DB 導入前にブラウザに保存していた入力は、トップの「この内容でグループを作る」で移行できる。

### 精算アルゴリズム
1. 各支払いから、メンバーごとの残高(立て替えた額 − 負担すべき額)を出す。全員の合計は必ず 0。
2. **貪欲法**: 一番多く借りている人から一番多く貸している人へ送金、を残高が 0 になるまで繰り返す。

送金回数を厳密に最小化する問題は NP 困難なため、近似の貪欲法を採用。
この方法でも送金回数は最大で「残高が 0 でない人数 − 1」回に収まる。

## 開発

```bash
pip install -e ".[dev]"

# DB の作成・更新(DATABASE_URL 未設定ならカレントの warikan.db(SQLite)を使う)
alembic upgrade head

# テスト(既定はメモリ上の SQLite。PostgreSQL で試すなら DATABASE_URL を指定)
pytest -v
DATABASE_URL=postgresql://user:pass@localhost:5432/warikan pytest -v

# モデルを変更したらマイグレーションを作る
alembic revision --autogenerate -m "変更内容"

# Lint / フォーマット
ruff check .
ruff format .

# 起動 → http://localhost:8000/ で画面、/docs で API を試せる
uvicorn app.main:app --reload
```

## デプロイ

[Render](https://render.com) の無料プランで公開している。設定は `render.yaml`(Blueprint)。

- DB は Render の PostgreSQL(無料プラン)。起動時に `alembic upgrade head` を実行してから API を立ち上げる。
  - 無料の PostgreSQL は**作成から 30 日で期限切れ**になる。継続して使うなら有料プランか外部の DB(Neon など)に切り替える。
- CI では PostgreSQL のサービスコンテナを立て、マイグレーションの適用・巻き戻しとテストを本番と同じ DB で実行している。

- 公開URL: https://warikan-94kv.onrender.com/ (画面)
- API ドキュメント: https://warikan-94kv.onrender.com/docs

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Milan-coding/warikan)

- `main` に push して CI が通ると、GitHub Actions が Render の Deploy Hook を呼んでデプロイする
  (Secret `RENDER_DEPLOY_HOOK_URL` に Render の Settings → Deploy Hook の URL を登録しておく)。
- 無料プランは 15 分アクセスがないとスリープし、次のアクセス時の起動に数十秒かかる。

## ロードマップ

- [x] 精算ロジックとテスト
- [x] CI(Lint・テスト・マイグレーション検証)
- [x] Render へのデプロイ(CI 成功後に自動デプロイ)
- [x] PostgreSQL + SQLAlchemy でグループ・支払いを保存
- [x] グループ作成・支払い登録・精算結果の API
- [x] グループを URL で共有できる画面
- [ ] 期限のない DB(Neon など)への移行
- [ ] 友達に使ってもらい、意見をもとに改善する

## 工夫した点・苦労した点

### 工夫した点
- **金額の誤差を防ぐ**: 金額はすべて円単位の整数で扱い、小数は使わない。割り切れない端数は先頭の人から 1 円ずつ負担するルールにした。
- **過去の精算結果が変わらない設計**: 負担額の内訳は登録時に確定して保存し、端数のルールを後から変えても過去の支払いに影響しないようにした。
- **データの整合性**: 支払いと内訳は 1 回のトランザクションで保存する。支払いに関わったメンバーは、API と DB の外部キー制約の両方で削除できないようにした。
- **本番と同じ環境でのテスト**: CI で PostgreSQL のコンテナを立ち上げ、マイグレーションの適用・取り消しとテストを本番と同じ DB で実行している。
- **段階的な開発**: まず画面と精算 API だけで動く形を作り、入力はブラウザに保存した。DB を導入したあとは、それまでブラウザに保存していた入力をグループへ移行できるようにした。

### 苦労した点
- **自動デプロイが動かなかった**: Render の CI 連携による自動デプロイが一度も動かなかったため、GitHub Actions で CI が通ったあとに Deploy Hook を呼ぶ方式に切り替えた。
- **起動の確認でエラーになった**: Render が HEAD リクエストで起動を確認していたため、トップページを GET だけでなく HEAD でも返すようにした。
- **無料プランの制約**: 無料プランではデプロイ前にコマンドを実行できないため、アプリの起動時にマイグレーションを適用するようにした。
- **SQLite と PostgreSQL の違い**: 手元の SQLite では日時のタイムゾーンが保存されないため、独自の型(`UTCDateTime`)を用意して、どちらの DB でも同じ形式の日時を返すようにした。

## 開発の進め方

設計の方針は自分で決め、実装には Claude Code を使った。出力されたコードは読んで理解したうえで、テストと CI で動作を確かめてから取り込んでいる。
