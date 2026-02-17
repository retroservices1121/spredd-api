"""Position tracker — upsert positions on trade execution."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Position, PositionStatus


async def upsert_position(
    db: AsyncSession,
    api_key_id: uuid.UUID,
    wallet_address: str,
    platform: str,
    market_id: str,
    outcome: str,
    token_amount: Decimal,
    entry_price: Decimal,
    current_price: Decimal | None = None,
) -> Position:
    """Create or update a position after a trade."""
    result = await db.execute(
        select(Position).where(
            Position.api_key_id == api_key_id,
            Position.wallet_address == wallet_address,
            Position.platform == platform,
            Position.market_id == market_id,
            Position.outcome == outcome,
        )
    )
    position = result.scalar_one_or_none()

    if position:
        # Update existing position
        old_amount = Decimal(position.token_amount)
        old_avg = Decimal(str(position.avg_entry_price))
        new_total = old_amount + token_amount
        if new_total > 0:
            position.avg_entry_price = float((old_avg * old_amount + entry_price * token_amount) / new_total)
            position.token_amount = str(new_total)
        else:
            position.token_amount = "0"
            position.status = PositionStatus.CLOSED
        if current_price is not None:
            position.current_price = float(current_price)
    else:
        position = Position(
            api_key_id=api_key_id,
            wallet_address=wallet_address,
            platform=platform,
            market_id=market_id,
            outcome=outcome,
            token_amount=str(token_amount),
            avg_entry_price=float(entry_price),
            current_price=float(current_price) if current_price else None,
        )
        db.add(position)

    await db.commit()
    await db.refresh(position)
    return position
