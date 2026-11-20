from fastapi.testclient import TestClient


def make_group(client: TestClient, members=("alice", "bob", "carol")) -> dict:
    res = client.post("/groups", json={"name": "旅行", "members": list(members)})
    assert res.status_code == 201
    return res.json()


def ids(group: dict) -> dict[str, int]:
    return {m["name"]: m["id"] for m in group["members"]}


def add_payment(client: TestClient, group_id: str, **body) -> dict:
    res = client.post(f"/groups/{group_id}/payments", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------- グループ ----------
def test_グループを作って取得できる(client):
    group = make_group(client)
    assert len(group["id"]) >= 20  # 推測されにくい長さ
    assert [m["name"] for m in group["members"]] == ["alice", "bob", "carol"]

    res = client.get(f"/groups/{group['id']}")
    assert res.status_code == 200
    assert res.json() == group


def test_存在しないグループは404(client):
    assert client.get("/groups/nope").status_code == 404


def test_グループ作成時のメンバー重複は422(client):
    res = client.post("/groups", json={"name": "x", "members": ["alice", "alice"]})
    assert res.status_code == 422


def test_空白だけの名前は422(client):
    assert client.post("/groups", json={"name": "  "}).status_code == 422


# ---------- メンバー ----------
def test_メンバーを追加できる(client):
    group = make_group(client, members=["alice"])
    res = client.post(f"/groups/{group['id']}/members", json={"name": " bob "})
    assert res.status_code == 201
    assert res.json()["name"] == "bob"  # 前後の空白は除く


def test_同名メンバーの追加は409(client):
    group = make_group(client)
    res = client.post(f"/groups/{group['id']}/members", json={"name": "alice"})
    assert res.status_code == 409


def test_支払いに関わっていないメンバーは削除できる(client):
    group = make_group(client)
    m = ids(group)
    res = client.delete(f"/groups/{group['id']}/members/{m['carol']}")
    assert res.status_code == 204
    names = [x["name"] for x in client.get(f"/groups/{group['id']}").json()["members"]]
    assert names == ["alice", "bob"]


def test_支払いに関わるメンバーは削除できない(client):
    group = make_group(client)
    m = ids(group)
    add_payment(client, group["id"], payer_id=m["alice"], amount=1000, split_among=[m["bob"]])
    for name in ("alice", "bob"):
        res = client.delete(f"/groups/{group['id']}/members/{m[name]}")
        assert res.status_code == 409


def test_別グループのメンバーは削除できない(client):
    g1, g2 = make_group(client), make_group(client)
    res = client.delete(f"/groups/{g2['id']}/members/{ids(g1)['alice']}")
    assert res.status_code == 404


# ---------- 支払い ----------
def test_支払いを登録すると内訳が保存される(client):
    group = make_group(client)
    m = ids(group)
    p = add_payment(
        client,
        group["id"],
        payer_id=m["alice"],
        amount=1000,
        description="昼ごはん",
        split_among=[m["alice"], m["bob"], m["carol"]],
    )
    assert p["description"] == "昼ごはん"
    # 端数は先頭の人が負担する
    assert p["shares"] == [
        {"member_id": m["alice"], "amount": 334},
        {"member_id": m["bob"], "amount": 333},
        {"member_id": m["carol"], "amount": 333},
    ]
    saved = client.get(f"/groups/{group['id']}").json()["payments"]
    assert saved == [p]


def test_内訳の順番は入力どおりに保存される(client):
    group = make_group(client)
    m = ids(group)
    p = add_payment(
        client, group["id"], payer_id=m["alice"], amount=100, split_among=[m["carol"], m["bob"]]
    )
    assert [s["member_id"] for s in p["shares"]] == [m["carol"], m["bob"]]
    saved = client.get(f"/groups/{group['id']}").json()["payments"][0]
    assert [s["member_id"] for s in saved["shares"]] == [m["carol"], m["bob"]]


def test_グループ外のメンバーを含む支払いは422(client):
    g1, g2 = make_group(client), make_group(client)
    m1, m2 = ids(g1), ids(g2)
    url = f"/groups/{g1['id']}/payments"
    bad_payer = {"payer_id": m2["alice"], "amount": 100, "split_among": [m1["bob"]]}
    bad_split = {"payer_id": m1["alice"], "amount": 100, "split_among": [m2["bob"]]}
    assert client.post(url, json=bad_payer).status_code == 422
    assert client.post(url, json=bad_split).status_code == 422


def test_割る人の重複や金額0は422(client):
    group = make_group(client)
    m = ids(group)
    url = f"/groups/{group['id']}/payments"
    dup = {"payer_id": m["alice"], "amount": 100, "split_among": [m["bob"], m["bob"]]}
    zero = {"payer_id": m["alice"], "amount": 0, "split_among": [m["bob"]]}
    assert client.post(url, json=dup).status_code == 422
    assert client.post(url, json=zero).status_code == 422
    assert client.get(f"/groups/{group['id']}").json()["payments"] == []


def test_支払いを削除できる(client):
    group = make_group(client)
    m = ids(group)
    p = add_payment(client, group["id"], payer_id=m["alice"], amount=100, split_among=[m["bob"]])
    assert client.delete(f"/groups/{group['id']}/payments/{p['id']}").status_code == 204
    assert client.get(f"/groups/{group['id']}").json()["payments"] == []
    # 支払いが無くなればメンバーも削除できる
    assert client.delete(f"/groups/{group['id']}/members/{m['bob']}").status_code == 204


def test_別グループの支払いは削除できない(client):
    g1, g2 = make_group(client), make_group(client)
    m = ids(g1)
    p = add_payment(client, g1["id"], payer_id=m["alice"], amount=100, split_among=[m["bob"]])
    assert client.delete(f"/groups/{g2['id']}/payments/{p['id']}").status_code == 404


# ---------- 精算 ----------
def test_保存した支払いから精算できる(client):
    group = make_group(client)
    m = ids(group)
    everyone = [m["alice"], m["bob"], m["carol"]]
    add_payment(client, group["id"], payer_id=m["alice"], amount=3000, split_among=everyone)
    add_payment(client, group["id"], payer_id=m["bob"], amount=600, split_among=everyone)

    res = client.get(f"/groups/{group['id']}/settlement")
    assert res.status_code == 200
    body = res.json()
    assert body["balances"] == [
        {"member_id": m["alice"], "name": "alice", "balance": 1800},
        {"member_id": m["bob"], "name": "bob", "balance": -600},
        {"member_id": m["carol"], "name": "carol", "balance": -1200},
    ]
    assert body["transfers"] == [
        {"from_member_id": m["carol"], "to_member_id": m["alice"], "amount": 1200},
        {"from_member_id": m["bob"], "to_member_id": m["alice"], "amount": 600},
    ]


def test_支払いが無ければ全員0円で送金なし(client):
    group = make_group(client)
    body = client.get(f"/groups/{group['id']}/settlement").json()
    assert [b["balance"] for b in body["balances"]] == [0, 0, 0]
    assert body["transfers"] == []


def test_preview_APIと同じ結果になる(client):
    group = make_group(client)
    m = ids(group)
    add_payment(
        client,
        group["id"],
        payer_id=m["alice"],
        amount=1000,
        split_among=[m["alice"], m["bob"], m["carol"]],
    )
    preview = client.post(
        "/settlements/preview",
        json=[{"payer_id": "alice", "amount": 1000, "split_among": ["alice", "bob", "carol"]}],
    ).json()
    saved = client.get(f"/groups/{group['id']}/settlement").json()

    name_of = {v: k for k, v in m.items()}
    assert {b["name"]: b["balance"] for b in saved["balances"]} == preview["balances"]
    assert [
        {
            "from_id": name_of[t["from_member_id"]],
            "to_id": name_of[t["to_member_id"]],
            "amount": t["amount"],
        }
        for t in saved["transfers"]
    ] == preview["transfers"]
