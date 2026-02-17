from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import APIKey, Trade, TradeMode, TradeStatus
from app.dependencies import require_trade_limit
from app.platforms.base import Outcome
from app.platforms.registry import platform_registry
from app.schemas.trading import (
    ExecuteRequest,
    ExecuteResponse,
    PrepareRequest,
    PrepareResponse,
    QuoteRequest,
    QuoteResponse,
    TransactionData,
)
from app.services.fee import calculate_fee, get_fee_bps
from app.services.position_tracker import upsert_position

router = APIRouter()


@router.post("/quote", response_model=QuoteResponse)
async def get_quote(
    req: QuoteRequest,
    api_key: APIKey = Depends(require_trade_limit),
):
    p = platform_registry.get(req.platform)
    if not p:
        raise HTTPException(status_code=404, detail=f"Platform '{req.platform}' not found")

    outcome = Outcome.YES if req.outcome.lower() == "yes" else Outcome.NO
    try:
        quote = await p.get_quote(req.market_id, outcome, req.side, Decimal(str(req.amount)))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    fee = calculate_fee(Decimal(str(req.amount)))

    return QuoteResponse(
        platform=req.platform,
        market_id=req.market_id,
        outcome=req.outcome,
        side=req.side,
        input_amount=float(quote.input_amount),
        expected_output=float(quote.expected_output),
        price_per_token=float(quote.price_per_token),
        price_impact=float(quote.price_impact) if quote.price_impact else None,
        fee_amount=float(fee),
        fee_bps=get_fee_bps(),
        expires_at=quote.expires_at,
        quote_data=quote.quote_data,
    )


@router.post("/prepare", response_model=PrepareResponse)
async def prepare_trade(
    req: PrepareRequest,
    api_key: APIKey = Depends(require_trade_limit),
    db: AsyncSession = Depends(get_db),
):
    p = platform_registry.get(req.platform)
    if not p:
        raise HTTPException(status_code=404, detail=f"Platform '{req.platform}' not found")

    outcome = Outcome.YES if req.outcome.lower() == "yes" else Outcome.NO
    try:
        txs, quote = await p.prepare_transaction(
            req.market_id, outcome, req.side, Decimal(str(req.amount)), req.wallet_address
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    fee = calculate_fee(Decimal(str(req.amount)))

    # Record trade as prepared
    trade = Trade(
        api_key_id=api_key.id,
        wallet_address=req.wallet_address,
        platform=req.platform,
        chain=p.chain.value,
        market_id=req.market_id,
        outcome=req.outcome,
        side=req.side,
        input_amount=str(req.amount),
        price=float(quote.price_per_token),
        fee_amount=str(fee),
        status=TradeStatus.PREPARED,
        mode=TradeMode.PREPARE,
    )
    db.add(trade)
    await db.commit()

    quote_resp = QuoteResponse(
        platform=req.platform,
        market_id=req.market_id,
        outcome=req.outcome,
        side=req.side,
        input_amount=float(quote.input_amount),
        expected_output=float(quote.expected_output),
        price_per_token=float(quote.price_per_token),
        price_impact=float(quote.price_impact) if quote.price_impact else None,
        fee_amount=float(fee),
        fee_bps=get_fee_bps(),
        expires_at=quote.expires_at,
    )

    return PrepareResponse(
        transactions=[
            TransactionData(
                to=tx.to, data=tx.data, value=tx.value,
                gas=tx.gas, chain_id=tx.chain_id, description=tx.description,
            )
            for tx in txs
        ],
        quote=quote_resp,
    )


@router.post("/execute", response_model=ExecuteResponse)
async def execute_trade(
    req: ExecuteRequest,
    api_key: APIKey = Depends(require_trade_limit),
    db: AsyncSession = Depends(get_db),
):
    p = platform_registry.get(req.platform)
    if not p:
        raise HTTPException(status_code=404, detail=f"Platform '{req.platform}' not found")

    outcome = Outcome.YES if req.outcome.lower() == "yes" else Outcome.NO
    fee = calculate_fee(Decimal(str(req.amount)))

    # Record trade
    trade = Trade(
        api_key_id=api_key.id,
        wallet_address=req.wallet_address,
        platform=req.platform,
        chain=p.chain.value,
        market_id=req.market_id,
        outcome=req.outcome,
        side=req.side,
        input_amount=str(req.amount),
        fee_amount=str(fee),
        status=TradeStatus.SUBMITTED,
        mode=TradeMode.EXECUTE,
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)

    # Get quote
    try:
        quote = await p.get_quote(req.market_id, outcome, req.side, Decimal(str(req.amount)))
    except Exception as e:
        trade.status = TradeStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # Convert private key to platform-specific format
    try:
        if p.chain.value == "solana":
            from solders.keypair import Keypair
            import base58
            key_bytes = base58.b58decode(req.private_key) if not req.private_key.startswith("0x") else bytes.fromhex(req.private_key[2:])
            private_key = Keypair.from_bytes(key_bytes)
        else:
            from eth_account import Account
            private_key = Account.from_key(req.private_key)
    except Exception as e:
        trade.status = TradeStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Invalid private key: {e}")

    # Execute trade — key is used in-memory only, never stored
    result = await p.execute_trade(quote, private_key)

    # Update trade record
    trade.tx_hash = result.tx_hash
    trade.output_amount = str(result.output_amount) if result.output_amount else None
    trade.price = float(quote.price_per_token)
    trade.status = TradeStatus.CONFIRMED if result.success else TradeStatus.FAILED
    await db.commit()

    # Track position on success
    if result.success and req.side == "buy":
        await upsert_position(
            db=db,
            api_key_id=api_key.id,
            wallet_address=req.wallet_address,
            platform=req.platform,
            market_id=req.market_id,
            outcome=req.outcome,
            token_amount=quote.expected_output,
            entry_price=quote.price_per_token,
            current_price=quote.price_per_token,
        )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error_message or "Trade execution failed")

    return ExecuteResponse(
        tx_hash=result.tx_hash or "",
        status="confirmed",
        platform=req.platform,
        market_id=req.market_id,
        input_amount=float(quote.input_amount),
        output_amount=float(result.output_amount) if result.output_amount else None,
        fee_amount=float(fee),
        explorer_url=result.explorer_url,
    )
