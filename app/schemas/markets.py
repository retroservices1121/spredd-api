from pydantic import BaseModel


class MarketResponse(BaseModel):
    platform: str
    market_id: str
    title: str
    description: str | None = None
    category: str | None = None
    yes_price: float | None = None
    no_price: float | None = None
    volume: float | None = None
    liquidity: float | None = None
    end_date: str | None = None
    is_active: bool = True
    chain: str | None = None
    collateral_token: str | None = None
    outcomes: list[str] | None = None
    url: str | None = None


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBookResponse(BaseModel):
    platform: str
    market_id: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    spread: float | None = None


class PlatformInfo(BaseModel):
    name: str
    slug: str
    chain: str
    collateral: str
    description: str | None = None
