"""API の入口。

DB を入れる前の段階として、支払いリストを受け取って精算結果を返すだけの
エンドポイントを用意している。`uvicorn app.main:app --reload` で起動し、
http://localhost:8000/ で画面、http://localhost:8000/docs で API を試せる。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.settlement import Payment, calculate_balances, settle, split_equally

app = FastAPI(title="割り勘API")

STATIC_DIR = Path(__file__).parent / "static"


class PaymentIn(BaseModel):
    payer_id: str = Field(examples=["alice"])
    amount: int = Field(gt=0, examples=[1000])
    # 均等割りする対象メンバー。端数は先頭の人から 1 円ずつ負担する。
    split_among: list[str] = Field(min_length=1, examples=[["alice", "bob", "carol"]])


class TransferOut(BaseModel):
    from_id: str
    to_id: str
    amount: int


class SettlementOut(BaseModel):
    balances: dict[str, int]
    transfers: list[TransferOut]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    # 画面は HTML 1 枚で、入力の保持と表示はブラウザ側で行う
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/settlements/preview", response_model=SettlementOut)
def preview_settlement(payments: list[PaymentIn]) -> SettlementOut:
    try:
        domain_payments = [
            Payment(p.payer_id, p.amount, split_equally(p.amount, p.split_among)) for p in payments
        ]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    balances = calculate_balances(domain_payments)
    transfers = settle(balances)
    return SettlementOut(
        balances=balances,
        transfers=[TransferOut(**t.__dict__) for t in transfers],
    )
