"""DB 接続の設定。

接続先は環境変数 DATABASE_URL で指定する。
- 本番(Render): PostgreSQL。Render が渡す `postgres://...` 形式もそのまま使える。
- ローカル: 未設定なら SQLite ファイル(./warikan.db)を使うので、Postgres が無くても動く。
"""

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./warikan.db"


def normalize_url(url: str) -> str:
    """SQLAlchemy が psycopg(v3) ドライバを使うように URL のスキームを揃える。"""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        # SQLite は既定で外部キー制約を検査しないので、接続ごとに有効にする
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record) -> None:
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    # 無料プランの DB はアイドル時に接続が切られることがあるので、使う前に生存確認する
    return create_engine(url, pool_pre_ping=True)


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


engine = make_engine(database_url())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI の Depends 用。リクエストごとにセッションを開いて閉じる。"""
    with SessionLocal() as session:
        yield session
