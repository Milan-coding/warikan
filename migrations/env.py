"""Alembic の実行環境。接続先とテーブル定義はアプリと同じものを使う。"""

from logging.config import fileConfig

from alembic import context

from app.db import database_url, make_engine, normalize_url
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DB に接続せず SQL を出力する(alembic upgrade head --sql)。"""
    context.configure(
        url=normalize_url(database_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_url())
    with engine.connect() as connection:
        # SQLite は ALTER TABLE が弱いので、テーブル再作成方式(batch)で変更を書けるようにする
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
