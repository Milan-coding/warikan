"""グループ・メンバー・支払いを DB に保存して精算する API。

認証はまだ無い。グループ ID(ランダム文字列)を知っている人は誰でも読み書きできる、
「URL が合言葉」の方式にしている。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, settlement
from app.db import get_session

router = APIRouter(prefix="/groups", tags=["groups"])

SessionDep = Annotated[Session, Depends(get_session)]
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MemberName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


# ---------- 入出力の型 ----------
class GroupIn(BaseModel):
    name: GroupName = Field(examples=["箱根旅行"])
    members: list[MemberName] = Field(default=[], examples=[["alice", "bob", "carol"]])


class MemberIn(BaseModel):
    name: MemberName = Field(examples=["dave"])


class PaymentIn(BaseModel):
    payer_id: int
    amount: int = Field(gt=0, examples=[3000])
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    # 均等割りする対象のメンバー ID。端数は先頭の人から 1 円ずつ負担する。
    split_among: list[int] = Field(min_length=1)


class MemberOut(BaseModel):
    id: int
    name: str


class ShareOut(BaseModel):
    member_id: int
    amount: int


class PaymentOut(BaseModel):
    id: int
    payer_id: int
    amount: int
    description: str
    shares: list[ShareOut]
    created_at: datetime


class GroupOut(BaseModel):
    id: str
    name: str
    members: list[MemberOut]
    payments: list[PaymentOut]


class BalanceOut(BaseModel):
    member_id: int
    name: str
    balance: int


class TransferOut(BaseModel):
    from_member_id: int
    to_member_id: int
    amount: int


class GroupSettlementOut(BaseModel):
    balances: list[BalanceOut]
    transfers: list[TransferOut]


# ---------- 変換・取得の補助 ----------
def _payment_out(p: models.Payment) -> PaymentOut:
    return PaymentOut(
        id=p.id,
        payer_id=p.payer_id,
        amount=p.amount,
        description=p.description,
        shares=[ShareOut(member_id=s.member_id, amount=s.amount) for s in p.shares],
        created_at=p.created_at,
    )


def _group_out(g: models.Group) -> GroupOut:
    return GroupOut(
        id=g.id,
        name=g.name,
        members=[MemberOut(id=m.id, name=m.name) for m in g.members],
        payments=[_payment_out(p) for p in g.payments],
    )


def _get_group(session: Session, group_id: str) -> models.Group:
    group = session.scalar(
        select(models.Group)
        .where(models.Group.id == group_id)
        .options(
            selectinload(models.Group.members),
            selectinload(models.Group.payments).selectinload(models.Payment.shares),
        )
    )
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "グループが見つかりません")
    return group


def _duplicates(names: list[str]) -> bool:
    return len(set(names)) != len(names)


# ---------- グループ ----------
@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, session: SessionDep) -> GroupOut:
    if _duplicates(body.members):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "メンバー名が重複しています")
    group = models.Group(name=body.name, members=[models.Member(name=n) for n in body.members])
    session.add(group)
    session.commit()
    return _group_out(_get_group(session, group.id))


@router.get("/{group_id}", response_model=GroupOut)
def get_group(group_id: str, session: SessionDep) -> GroupOut:
    return _group_out(_get_group(session, group_id))


# ---------- メンバー ----------
@router.post("/{group_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(group_id: str, body: MemberIn, session: SessionDep) -> MemberOut:
    group = _get_group(session, group_id)
    if any(m.name == body.name for m in group.members):
        raise HTTPException(status.HTTP_409_CONFLICT, "同じ名前のメンバーがすでにいます")
    member = models.Member(group_id=group.id, name=body.name)
    session.add(member)
    try:
        session.commit()
    except IntegrityError as e:
        # 同時に同じ名前が追加された場合は一意制約で弾かれる
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "同じ名前のメンバーがすでにいます") from e
    return MemberOut(id=member.id, name=member.name)


@router.delete("/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(group_id: str, member_id: int, session: SessionDep) -> Response:
    member = session.get(models.Member, member_id)
    if member is None or member.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "メンバーが見つかりません")
    in_use = session.scalar(
        select(
            exists().where(models.Payment.payer_id == member_id)
            | exists().where(models.PaymentShare.member_id == member_id)
        )
    )
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "このメンバーが関わる支払いがあるため削除できません"
        )
    session.delete(member)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 支払い ----------
@router.post("/{group_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def add_payment(group_id: str, body: PaymentIn, session: SessionDep) -> PaymentOut:
    group = _get_group(session, group_id)
    member_ids = {m.id for m in group.members}
    if body.payer_id not in member_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "立て替えた人がグループにいません"
        )
    if not set(body.split_among) <= member_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "割る人にグループ外のメンバーがいます"
        )
    try:
        shares = settlement.split_equally(body.amount, body.split_among)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    # 支払いと内訳は 1 トランザクションでまとめて保存する(片方だけ残ることがない)
    payment = models.Payment(
        group_id=group.id,
        payer_id=body.payer_id,
        amount=body.amount,
        description=body.description,
        shares=[
            models.PaymentShare(member_id=mid, amount=amt, position=i)
            for i, (mid, amt) in enumerate(shares.items())
        ],
    )
    session.add(payment)
    session.commit()
    return _payment_out(payment)


@router.delete("/{group_id}/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(group_id: str, payment_id: int, session: SessionDep) -> Response:
    payment = session.get(models.Payment, payment_id)
    if payment is None or payment.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "支払いが見つかりません")
    session.delete(payment)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 精算 ----------
@router.get("/{group_id}/settlement", response_model=GroupSettlementOut)
def get_settlement(group_id: str, session: SessionDep) -> GroupSettlementOut:
    group = _get_group(session, group_id)
    # 精算ロジックには名前を渡す。同額のときの順番が名前順になり、
    # /settlements/preview と同じ結果になる(名前はグループ内で一意)。
    name_of = {m.id: m.name for m in group.members}
    id_of = {m.name: m.id for m in group.members}
    domain_payments = [
        settlement.Payment(
            payer_id=name_of[p.payer_id],
            amount=p.amount,
            shares={name_of[s.member_id]: s.amount for s in p.shares},
        )
        for p in group.payments
    ]
    balances = settlement.calculate_balances(domain_payments)
    transfers = settlement.settle(balances)
    return GroupSettlementOut(
        balances=[
            BalanceOut(member_id=m.id, name=m.name, balance=balances.get(m.name, 0))
            for m in group.members
        ],
        transfers=[
            TransferOut(
                from_member_id=id_of[t.from_id], to_member_id=id_of[t.to_id], amount=t.amount
            )
            for t in transfers
        ],
    )
