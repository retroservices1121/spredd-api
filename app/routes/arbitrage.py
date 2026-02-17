from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.db.models import APIKey
from app.dependencies import require_request_limit
from app.platforms.registry import platform_registry

router = APIRouter()


class ArbitrageOpportunity(BaseModel):
    market_title: str
    outcome: str
    buy_platform: str
    buy_price: float
    sell_platform: str
    sell_price: float
    spread: float
    spread_pct: float


@router.get("/arbitrage", response_model=list[ArbitrageOpportunity])
async def get_arbitrage_opportunities(
    min_spread: float = Query(default=0.02, description="Minimum spread to report (0-1 scale)"),
    limit: int = Query(default=20, le=50),
    api_key: APIKey = Depends(require_request_limit),
):
    """Find cross-platform spread opportunities by matching similar markets."""
    # Collect all markets across platforms
    all_markets: dict[str, list] = {}
    for slug, p in platform_registry.all().items():
        try:
            markets = await p.get_markets(limit=100)
            for m in markets:
                if m.yes_price and m.is_active:
                    all_markets.setdefault(m.title.lower().strip(), []).append(m)
        except Exception:
            continue

    opportunities = []
    for title, markets in all_markets.items():
        if len(markets) < 2:
            continue

        # Compare all pairs for YES price spread
        for i in range(len(markets)):
            for j in range(i + 1, len(markets)):
                m1, m2 = markets[i], markets[j]
                if m1.platform == m2.platform:
                    continue
                if not m1.yes_price or not m2.yes_price:
                    continue

                p1 = float(m1.yes_price)
                p2 = float(m2.yes_price)

                # Buy low, sell high
                if p1 < p2:
                    spread = p2 - p1
                    buy_p, sell_p = m1, m2
                else:
                    spread = p1 - p2
                    buy_p, sell_p = m2, m1

                if spread >= min_spread:
                    avg_price = (p1 + p2) / 2
                    opportunities.append(ArbitrageOpportunity(
                        market_title=m1.title,
                        outcome="YES",
                        buy_platform=buy_p.platform.value,
                        buy_price=float(buy_p.yes_price),
                        sell_platform=sell_p.platform.value,
                        sell_price=float(sell_p.yes_price),
                        spread=round(spread, 4),
                        spread_pct=round(spread / avg_price * 100, 2) if avg_price > 0 else 0,
                    ))

    # Sort by spread descending
    opportunities.sort(key=lambda x: x.spread, reverse=True)
    return opportunities[:limit]
