"""精算ロジック。

DB や Web に依存しない純粋な関数だけを置く。
金額はすべて「円単位の int」で扱い、float は使わない。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

MemberId = str


@dataclass(frozen=True)
class Payment:
    """1回の支払い。

    payer_id: 立て替えた人
    amount:   支払った総額(円)
    shares:   誰がいくら負担するか {メンバーID: 負担額}。合計は amount と一致すること。
    """

    payer_id: MemberId
    amount: int
    shares: dict[MemberId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.amount, int) or self.amount <= 0:
            raise ValueError("amount は 1 以上の整数(円)で指定してください")
        if not self.shares:
            raise ValueError("shares が空です")
        if any(not isinstance(v, int) or v < 0 for v in self.shares.values()):
            raise ValueError("負担額は 0 以上の整数で指定してください")
        if sum(self.shares.values()) != self.amount:
            raise ValueError(
                f"負担額の合計({sum(self.shares.values())})が支払額({self.amount})と一致しません"
            )


@dataclass(frozen=True)
class Transfer:
    """精算のための送金1件: from_id が to_id に amount 円払う。"""

    from_id: MemberId
    to_id: MemberId
    amount: int


def split_equally(amount: int, member_ids: list[MemberId]) -> dict[MemberId, int]:
    """amount を均等割りする。

    端数ルール: 割り切れない分は member_ids の先頭から 1 円ずつ多く負担する。
    例) 1000 円を 3 人 → [334, 333, 333]
    呼び出し側が順番を決められるので、「立て替えた人を先頭にして端数を持ってもらう」
    などのルールにも対応できる。
    """
    if amount <= 0:
        raise ValueError("amount は 1 以上で指定してください")
    if not member_ids:
        raise ValueError("member_ids が空です")
    if len(set(member_ids)) != len(member_ids):
        raise ValueError("member_ids に重複があります")

    base, remainder = divmod(amount, len(member_ids))
    return {m: base + (1 if i < remainder else 0) for i, m in enumerate(member_ids)}


def calculate_balances(payments: list[Payment]) -> dict[MemberId, int]:
    """メンバーごとの貸し借り残高を計算する。

    正の値: 受け取る側(立て替えすぎている)
    負の値: 払う側
    全員の合計は必ず 0 になる。
    """
    balances: dict[MemberId, int] = {}
    for p in payments:
        balances[p.payer_id] = balances.get(p.payer_id, 0) + p.amount
        for member, share in p.shares.items():
            balances[member] = balances.get(member, 0) - share

    assert sum(balances.values()) == 0, "残高の合計が 0 になっていません"
    return balances


def settle(balances: dict[MemberId, int]) -> list[Transfer]:
    """残高から「誰が誰にいくら払うか」を求める(貪欲法)。

    一番多く借りている人 → 一番多く貸している人 の順に組み合わせて送金を決める。
    送金回数の厳密な最小化は NP 困難なので、実用上十分な近似を採用している。
    この方法だと送金回数は最大でも (残高が 0 でない人数 - 1) 回に収まる。

    同額のときはメンバーIDの昇順で処理し、結果が毎回同じになるようにしている。
    """
    if sum(balances.values()) != 0:
        raise ValueError("残高の合計が 0 ではありません")

    # heapq は最小ヒープなので、大きい順に取り出したい値は符号を反転して入れる
    creditors = [(-amt, m) for m, amt in balances.items() if amt > 0]
    debtors = [(amt, m) for m, amt in balances.items() if amt < 0]
    heapq.heapify(creditors)
    heapq.heapify(debtors)

    transfers: list[Transfer] = []
    while creditors and debtors:
        neg_credit, creditor = heapq.heappop(creditors)
        debt, debtor = heapq.heappop(debtors)
        credit, owe = -neg_credit, -debt

        pay = min(credit, owe)
        transfers.append(Transfer(from_id=debtor, to_id=creditor, amount=pay))

        if credit > pay:
            heapq.heappush(creditors, (-(credit - pay), creditor))
        if owe > pay:
            heapq.heappush(debtors, (-(owe - pay), debtor))

    return transfers
