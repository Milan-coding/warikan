import random

import pytest

from app.settlement import (
    Payment,
    Transfer,
    calculate_balances,
    settle,
    split_equally,
)

# ---------- split_equally ----------


def test_割り切れる金額は均等になる():
    assert split_equally(3000, ["a", "b", "c"]) == {"a": 1000, "b": 1000, "c": 1000}


def test_端数は先頭から1円ずつ負担する():
    assert split_equally(1000, ["a", "b", "c"]) == {"a": 334, "b": 333, "c": 333}
    assert split_equally(1001, ["a", "b", "c"]) == {"a": 334, "b": 334, "c": 333}


def test_均等割りの合計は元の金額と一致する():
    for amount in range(1, 500):
        for n in range(1, 8):
            members = [f"m{i}" for i in range(n)]
            assert sum(split_equally(amount, members).values()) == amount


def test_人数より少ない金額でも合計が合う():
    assert split_equally(2, ["a", "b", "c"]) == {"a": 1, "b": 1, "c": 0}


@pytest.mark.parametrize(
    "amount, members",
    [(0, ["a"]), (-100, ["a"]), (100, []), (100, ["a", "a"])],
)
def test_split_equally_不正な入力はエラー(amount, members):
    with pytest.raises(ValueError):
        split_equally(amount, members)


# ---------- Payment のバリデーション ----------


def test_負担額の合計が支払額と違うとエラー():
    with pytest.raises(ValueError):
        Payment(payer_id="a", amount=1000, shares={"a": 500, "b": 400})


@pytest.mark.parametrize("amount", [0, -1, 100.5])
def test_支払額が正の整数でないとエラー(amount):
    with pytest.raises(ValueError):
        Payment(payer_id="a", amount=amount, shares={"a": amount})


# ---------- calculate_balances ----------


def test_1人が全員分を立て替えた場合の残高():
    p = Payment("a", 3000, split_equally(3000, ["a", "b", "c"]))
    assert calculate_balances([p]) == {"a": 2000, "b": -1000, "c": -1000}


def test_自分は負担しない立て替えも扱える():
    # a が b と c の分だけ払った(a 自身は飲んでいない)
    p = Payment("a", 2000, {"b": 1000, "c": 1000})
    assert calculate_balances([p]) == {"a": 2000, "b": -1000, "c": -1000}


def test_複数の支払いが相殺される():
    payments = [
        Payment("a", 3000, split_equally(3000, ["a", "b", "c"])),
        Payment("b", 3000, split_equally(3000, ["a", "b", "c"])),
    ]
    assert calculate_balances(payments) == {"a": 1000, "b": 1000, "c": -2000}


# ---------- settle ----------


def _apply(balances, transfers):
    """送金を実行した後の残高を返す(全員 0 になれば精算完了)。"""
    after = dict(balances)
    for t in transfers:
        after[t.from_id] += t.amount
        after[t.to_id] -= t.amount
    return after


def test_シンプルな精算():
    balances = {"a": 2000, "b": -1000, "c": -1000}
    assert settle(balances) == [
        Transfer("b", "a", 1000),
        Transfer("c", "a", 1000),
    ]


def test_全員の残高が0なら送金なし():
    assert settle({"a": 0, "b": 0}) == []
    assert settle({}) == []


def test_合計が0でない残高はエラー():
    with pytest.raises(ValueError):
        settle({"a": 100, "b": -50})


def test_精算後は全員の残高が0になる_ランダム():
    rng = random.Random(42)
    for _ in range(300):
        members = [f"m{i}" for i in range(rng.randint(2, 10))]
        payments = []
        for _ in range(rng.randint(1, 15)):
            payer = rng.choice(members)
            targets = rng.sample(members, rng.randint(1, len(members)))
            amount = rng.randint(1, 50000)
            payments.append(Payment(payer, amount, split_equally(amount, targets)))

        balances = calculate_balances(payments)
        transfers = settle(balances)

        assert all(v == 0 for v in _apply(balances, transfers).values())
        assert all(t.amount > 0 for t in transfers)
        nonzero = sum(1 for v in balances.values() if v != 0)
        assert len(transfers) <= max(nonzero - 1, 0)
