"""DB を使うテストの共通設定。

既定ではメモリ上の SQLite で実行する。環境変数 DATABASE_URL があればその DB を使う
(CI では PostgreSQL を指定して、本番と同じ DB でも通ることを確認している)。
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session, make_engine
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if url:
        eng = make_engine(url)
    else:
        # メモリ上の SQLite は接続ごとに別 DB になるので、1 本の接続を使い回す
        eng = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    # テストごとにテーブルを作り直して、前のテストのデータが残らないようにする
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override() -> Iterator[Session]:
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
