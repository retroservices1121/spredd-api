"""
Platform abstraction layer for prediction markets.
All platforms implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class PlatformSlug(str, Enum):
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"
    MYRIAD = "myriad"
    OPINION = "opinion"
    LIMITLESS = "limitless"


class ChainSlug(str, Enum):
    SOLANA = "solana"
    POLYGON = "polygon"
    BSC = "bsc"
    BASE = "base"
    ABSTRACT = "abstract"
    LINEA = "linea"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Outcome(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass
class Market:
    platform: PlatformSlug
    chain: ChainSlug
    market_id: str
    event_id: Optional[str]
    title: str
    description: Optional[str]
    category: Optional[str]
    yes_price: Optional[Decimal]
    no_price: Optional[Decimal]
    volume_24h: Optional[Decimal]
    liquidity: Optional[Decimal]
    is_active: bool
    close_time: Optional[str]
    yes_token: Optional[str]
    no_token: Optional[str]
    raw_data: Optional[dict] = None
    outcome_name: Optional[str] = None
    is_multi_outcome: bool = False
    related_market_count: int = 0
    outcomes: list[str] = field(default_factory=lambda: ["Yes", "No"])
    url: Optional[str] = None
    collateral_token: Optional[str] = None


@dataclass
class Quote:
    platform: PlatformSlug
    chain: ChainSlug
    market_id: str
    outcome: Outcome
    side: str
    input_token: str
    input_amount: Decimal
    output_token: str
    expected_output: Decimal
    price_per_token: Decimal
    price_impact: Optional[Decimal]
    platform_fee: Optional[Decimal]
    network_fee_estimate: Optional[Decimal]
    expires_at: Optional[str]
    quote_data: Optional[dict] = None


@dataclass
class PreparedTransaction:
    to: str
    data: str
    value: str
    gas: Optional[str]
    chain_id: int
    description: str


@dataclass
class TradeResult:
    success: bool
    tx_hash: Optional[str]
    input_amount: Decimal
    output_amount: Optional[Decimal]
    error_message: Optional[str]
    explorer_url: Optional[str]


@dataclass
class OrderBook:
    market_id: str
    outcome: Outcome
    bids: list[tuple[Decimal, Decimal]]
    asks: list[tuple[Decimal, Decimal]]

    @property
    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0][0] if self.asks else None

    @property
    def spread(self) -> Optional[Decimal]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


class PlatformError(Exception):
    def __init__(self, message: str, platform: str, code: Optional[str] = None):
        self.message = message
        self.platform = platform
        self.code = code
        super().__init__(f"[{platform}] {message}")


class MarketNotFoundError(PlatformError):
    pass


EXPLORER_URLS = {
    ChainSlug.SOLANA: "https://solscan.io/tx/{}",
    ChainSlug.POLYGON: "https://polygonscan.com/tx/{}",
    ChainSlug.BSC: "https://bscscan.com/tx/{}",
    ChainSlug.BASE: "https://basescan.org/tx/{}",
    ChainSlug.ABSTRACT: "https://abscan.org/tx/{}",
    ChainSlug.LINEA: "https://lineascan.build/tx/{}",
}


class BasePlatform(ABC):
    platform: PlatformSlug
    chain: ChainSlug
    name: str
    description: str
    collateral_symbol: str
    collateral_decimals: int

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        pass

    @abstractmethod
    async def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        pass

    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[Market]:
        pass

    @abstractmethod
    async def get_orderbook(self, market_id: str, outcome: Outcome) -> OrderBook:
        pass

    @abstractmethod
    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        pass

    @abstractmethod
    async def prepare_transaction(
        self, market_id: str, outcome: Outcome, side: str, amount: Decimal, wallet_address: str
    ) -> tuple[list[PreparedTransaction], Quote]:
        pass

    @abstractmethod
    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        pass

    def get_explorer_url(self, tx_hash: str) -> str:
        template = EXPLORER_URLS.get(self.chain, "{}")
        return template.format(tx_hash)
