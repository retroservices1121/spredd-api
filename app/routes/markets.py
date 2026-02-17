from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.models import APIKey
from app.dependencies import require_request_limit
from app.platforms.base import Outcome
from app.platforms.registry import platform_registry
from app.schemas.markets import MarketResponse, OrderBookLevel, OrderBookResponse, PlatformInfo

router = APIRouter()


@router.get("/platforms", response_model=list[PlatformInfo])
async def list_platforms(api_key: APIKey = Depends(require_request_limit)):
    return platform_registry.list_platforms()


@router.get("/markets", response_model=list[MarketResponse])
async def list_markets(
    platform: str | None = None,
    search: str | None = None,
    category: str | None = None,
    active: bool = True,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    api_key: APIKey = Depends(require_request_limit),
):
    results = []
    platforms = [platform] if platform else list(platform_registry.all().keys())

    for slug in platforms:
        p = platform_registry.get(slug)
        if not p:
            continue
        try:
            if search:
                markets = await p.search_markets(search, limit=limit)
            else:
                markets = await p.get_markets(limit=limit, offset=offset, active_only=active)
        except Exception:
            continue

        for m in markets:
            results.append(MarketResponse(
                platform=m.platform.value,
                market_id=m.market_id,
                title=m.title,
                description=m.description,
                category=m.category or category,
                yes_price=float(m.yes_price) if m.yes_price else None,
                no_price=float(m.no_price) if m.no_price else None,
                volume=float(m.volume_24h) if m.volume_24h else None,
                liquidity=float(m.liquidity) if m.liquidity else None,
                end_date=m.close_time,
                is_active=m.is_active,
                chain=m.chain.value,
                collateral_token=m.collateral_token,
                outcomes=m.outcomes,
                url=m.url,
            ))

    return results[:limit]


@router.get("/markets/{platform}/{market_id}", response_model=MarketResponse)
async def get_market(
    platform: str,
    market_id: str,
    api_key: APIKey = Depends(require_request_limit),
):
    p = platform_registry.get(platform)
    if not p:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' not found")

    market = await p.get_market(market_id)
    if not market:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found on {platform}")

    return MarketResponse(
        platform=market.platform.value,
        market_id=market.market_id,
        title=market.title,
        description=market.description,
        category=market.category,
        yes_price=float(market.yes_price) if market.yes_price else None,
        no_price=float(market.no_price) if market.no_price else None,
        volume=float(market.volume_24h) if market.volume_24h else None,
        liquidity=float(market.liquidity) if market.liquidity else None,
        end_date=market.close_time,
        is_active=market.is_active,
        chain=market.chain.value,
        collateral_token=market.collateral_token,
        outcomes=market.outcomes,
        url=market.url,
    )


@router.get("/markets/{platform}/{market_id}/orderbook", response_model=OrderBookResponse)
async def get_orderbook(
    platform: str,
    market_id: str,
    outcome: str = "yes",
    api_key: APIKey = Depends(require_request_limit),
):
    p = platform_registry.get(platform)
    if not p:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' not found")

    oc = Outcome.YES if outcome.lower() == "yes" else Outcome.NO
    ob = await p.get_orderbook(market_id, oc)

    return OrderBookResponse(
        platform=platform,
        market_id=market_id,
        bids=[OrderBookLevel(price=float(b[0]), size=float(b[1])) for b in ob.bids],
        asks=[OrderBookLevel(price=float(a[0]), size=float(a[1])) for a in ob.asks],
        spread=float(ob.spread) if ob.spread else None,
    )
