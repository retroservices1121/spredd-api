from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import APIKey, Position
from app.dependencies import require_request_limit

router = APIRouter()


class PositionResponse(BaseModel):
    id: str
    wallet_address: str
    platform: str
    market_id: str
    outcome: str
    token_amount: str
    avg_entry_price: float
    current_price: float | None
    status: str
    created_at: str
    updated_at: str


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(
    wallet_address: str | None = None,
    platform: str | None = None,
    status: str | None = "open",
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    api_key: APIKey = Depends(require_request_limit),
    db: AsyncSession = Depends(get_db),
):
    query = select(Position).where(Position.api_key_id == api_key.id)

    if wallet_address:
        query = query.where(Position.wallet_address == wallet_address)
    if platform:
        query = query.where(Position.platform == platform)
    if status:
        query = query.where(Position.status == status)

    query = query.order_by(Position.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    positions = result.scalars().all()

    return [
        PositionResponse(
            id=str(p.id),
            wallet_address=p.wallet_address,
            platform=p.platform,
            market_id=p.market_id,
            outcome=p.outcome,
            token_amount=p.token_amount,
            avg_entry_price=float(p.avg_entry_price),
            current_price=float(p.current_price) if p.current_price else None,
            status=p.status.value if hasattr(p.status, "value") else p.status,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
        )
        for p in positions
    ]
