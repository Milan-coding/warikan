from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_トップページで画面を返す():
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "割り勘精算" in res.text


def test_精算プレビュー():
    res = client.post(
        "/settlements/preview",
        json=[
            {"payer_id": "alice", "amount": 3000, "split_among": ["alice", "bob", "carol"]},
        ],
    )
    assert res.status_code == 200
    body = res.json()
    assert body["balances"] == {"alice": 2000, "bob": -1000, "carol": -1000}
    assert body["transfers"] == [
        {"from_id": "bob", "to_id": "alice", "amount": 1000},
        {"from_id": "carol", "to_id": "alice", "amount": 1000},
    ]


def test_重複メンバーは422():
    res = client.post(
        "/settlements/preview",
        json=[{"payer_id": "alice", "amount": 1000, "split_among": ["bob", "bob"]}],
    )
    assert res.status_code == 422


def test_金額0は422():
    res = client.post(
        "/settlements/preview",
        json=[{"payer_id": "alice", "amount": 0, "split_among": ["bob"]}],
    )
    assert res.status_code == 422
