"""DB のテーブル定義。

- groups:         精算する友達グループ。id は推測されにくいランダム文字列で、URL に載せて共有する
- members:        グループのメンバー。同じグループ内で名前は重複不可
- payments:       立て替え 1 件
- payment_shares: その立て替えを誰がいくら負担するか。合計は payments.amount と一致させる

金額はすべて円単位の整数。負担額の内訳は保存時に確定させるので、
後から端数ルールを変えても過去の支払いの内訳は変わらない。
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 制約名を固定しておくと、Alembic のマイグレーションが DB ごとに食い違わない
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator[datetime]):
    """タイムゾーン付きの日時。

    PostgreSQL は timestamptz で保存できるが、SQLite はタイムゾーンを捨てるので、
    読み出したときに UTC を付け直して、どちらの DB でも同じ値を返すようにする。
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _new_group_id() -> str:
    # 16 バイト = 22 文字。URL を知っている人だけがグループを見られる前提なので十分な長さにする
    return secrets.token_urlsafe(16)


def _now() -> datetime:
    return datetime.now(UTC)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_group_id)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)

    members: Mapped[list["Member"]] = relationship(
        back_populates="group", order_by="Member.id", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="group", order_by="Payment.id", cascade="all, delete-orphan"
    )


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("group_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))

    group: Mapped[Group] = relationship(back_populates="members")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    # 立て替えた人。支払いが残っているメンバーは削除できない(RESTRICT)
    payer_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"))
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)

    group: Mapped[Group] = relationship(back_populates="payments")
    shares: Mapped[list["PaymentShare"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", order_by="PaymentShare.position"
    )


class PaymentShare(Base):
    __tablename__ = "payment_shares"
    __table_args__ = (CheckConstraint("amount >= 0", name="amount_non_negative"),)

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), primary_key=True
    )
    amount: Mapped[int] = mapped_column(Integer)
    # 入力された「割る人」の順番。端数を誰が持ったかを後から再現できるように残す
    position: Mapped[int] = mapped_column(Integer)

    payment: Mapped[Payment] = relationship(back_populates="shares")
