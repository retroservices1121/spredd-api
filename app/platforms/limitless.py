"""
Limitless Exchange platform adapter.
Prediction markets on Base (Optimism L2).
"""

import logging
import time
from decimal import Decimal
from typing import Any, Optional

import httpx
from eth_account.signers.local import LocalAccount
from web3 import Web3

from app.config import settings
from app.platforms.base import (
    BasePlatform,
    ChainSlug,
    Market,
    MarketNotFoundError,
    OrderBook,
    Outcome,
    PlatformError,
    PlatformSlug,
    PreparedTransaction,
    Quote,
    TradeResult,
)

logger = logging.getLogger(__name__)

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

LIMITLESS_CATEGORIES = {
    "29": "Hourly", "30": "Daily", "31": "Weekly",
    "2": "Crypto", "1": "Sports", "49": "Football Matches",
    "23": "Economy", "43": "Pre-TGE", "19": "Company News",
}


class LimitlessPlatform(BasePlatform):
    platform = PlatformSlug.LIMITLESS
    chain = ChainSlug.BASE
    name = "Limitless"
    description = "Prediction markets on Base"
    collateral_symbol = "USDC"
    collateral_decimals = 6

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._fee_bps = settings.evm_fee_bps
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self._cache_ttl = 300

    async def initialize(self) -> None:
        headers = {"Content-Type": "application/json"}
        if settings.limitless_api_key:
            headers["Authorization"] = f"Bearer {settings.limitless_api_key}"
        self._http = httpx.AsyncClient(
            base_url=settings.limitless_api_url, timeout=30.0, headers=headers,
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        resp = await self._http.request(method, endpoint, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "limitless", "429")
        resp.raise_for_status()
        return resp.json()

    def _parse_market(self, data: dict) -> Market:
        yes_price = no_price = None
        outcomes = data.get("outcomes", [])
        if len(outcomes) >= 2:
            yes_price = Decimal(str(outcomes[0].get("price", 0)))
            no_price = Decimal(str(outcomes[1].get("price", 0)))
        elif data.get("yes_price") is not None:
            yes_price = Decimal(str(data["yes_price"]))
            no_price = Decimal("1") - yes_price

        yes_token = outcomes[0].get("token_id") if len(outcomes) > 0 else data.get("yes_token_id")
        no_token = outcomes[1].get("token_id") if len(outcomes) > 1 else data.get("no_token_id")

        slug = data.get("slug") or str(data.get("id"))
        category_id = str(data.get("category_id", ""))
        category = LIMITLESS_CATEGORIES.get(category_id, data.get("category"))

        return Market(
            platform=PlatformSlug.LIMITLESS,
            chain=ChainSlug.BASE,
            market_id=slug,
            event_id=data.get("event_slug") or category_id,
            title=data.get("title") or data.get("question", ""),
            description=data.get("description"),
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
            liquidity=Decimal(str(data.get("liquidity", 0))) if data.get("liquidity") else None,
            is_active=data.get("status") in ("active", "open", None),
            close_time=data.get("end_date") or data.get("endDate") or data.get("expirationDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            collateral_token="USDC",
            url=f"https://limitless.exchange/markets/{slug}",
        )

    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[offset : offset + limit]

        params = {"limit": 200, "status": "active" if active_only else "all"}
        data = await self._request("GET", "/markets", params=params)
        markets_list = data if isinstance(data, list) else data.get("markets", data.get("data", []))

        markets = []
        for item in markets_list:
            try:
                markets.append(self._parse_market(item))
            except Exception:
                continue

        self._markets_cache = markets
        self._markets_cache_time = now
        return markets[offset : offset + limit]

    async def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        all_markets = await self.get_markets(limit=200)
        q = query.lower()
        return [m for m in all_markets if q in m.title.lower() or (m.description and q in m.description.lower())][:limit]

    async def get_market(self, market_id: str) -> Optional[Market]:
        for m in self._markets_cache:
            if m.market_id == market_id:
                return m
        try:
            data = await self._request("GET", f"/markets/{market_id}")
            return self._parse_market(data)
        except Exception:
            return None

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> OrderBook:
        try:
            data = await self._request("GET", f"/markets/{market_id}/orderbook")
            bids = [(Decimal(str(b["price"])), Decimal(str(b["size"]))) for b in data.get("bids", [])]
            asks = [(Decimal(str(a["price"])), Decimal(str(a["size"]))) for a in data.get("asks", [])]
        except Exception:
            bids, asks = [], []
        return OrderBook(market_id=market_id, outcome=outcome, bids=bids, asks=asks)

    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "limitless")

        ob = await self.get_orderbook(market_id, outcome)
        if side == "buy":
            price = ob.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price if price > 0 else Decimal(0)
        else:
            price = ob.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token

        return Quote(
            platform=PlatformSlug.LIMITLESS,
            chain=ChainSlug.BASE,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=USDC_BASE if side == "buy" else (token_id or ""),
            input_amount=amount,
            output_token=(token_id or "") if side == "buy" else USDC_BASE,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=ob.spread,
            platform_fee=amount * Decimal(self._fee_bps) / Decimal(10000),
            network_fee_estimate=Decimal("0.0005"),
            expires_at=None,
            quote_data={"token_id": token_id, "market_id": market_id},
        )

    async def prepare_transaction(
        self, market_id: str, outcome: Outcome, side: str, amount: Decimal, wallet_address: str
    ) -> tuple[list[PreparedTransaction], Quote]:
        quote = await self.get_quote(market_id, outcome, side, amount)
        txs = []
        amount_raw = int(amount * Decimal(10**self.collateral_decimals))

        w3 = Web3()
        usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_BASE), abi=ERC20_ABI)

        # This is a placeholder — actual exchange contract would come from Limitless SDK
        exchange_addr = "0x0000000000000000000000000000000000000000"

        approve_data = usdc.encode_abi("approve", args=[Web3.to_checksum_address(exchange_addr), amount_raw])
        txs.append(PreparedTransaction(
            to=USDC_BASE, data=approve_data, value="0",
            gas="100000", chain_id=8453, description="Approve USDC for Limitless exchange",
        ))

        txs.append(PreparedTransaction(
            to=exchange_addr,
            data=f"0x_limitless_trade_{market_id}_{outcome.value}_{side}",
            value="0", gas="300000", chain_id=8453,
            description=f"{side.upper()} {outcome.value.upper()} on {market_id}",
        ))

        # Fee tx
        if self._fee_bps > 0 and settings.evm_fee_account:
            fee_raw = int(amount * Decimal(self._fee_bps) / Decimal(10000) * Decimal(10**self.collateral_decimals))
            fee_data = usdc.encode_abi("approve", args=[Web3.to_checksum_address(settings.evm_fee_account), fee_raw])
            txs.append(PreparedTransaction(
                to=USDC_BASE, data=fee_data, value="0",
                gas="60000", chain_id=8453, description=f"Platform fee: {self._fee_bps/100}%",
            ))

        return txs, quote

    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        if not isinstance(private_key, LocalAccount):
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="Invalid key type, expected EVM LocalAccount", explorer_url=None,
            )

        try:
            from limitless_sdk import LimitlessClient, OrderInput

            client = LimitlessClient(
                api_key=settings.limitless_api_key,
                private_key=private_key.key.hex(),
                chain="base",
            )
            order = OrderInput(
                market_id=quote.market_id,
                token_id=quote.quote_data.get("token_id"),
                side="BUY" if quote.side == "buy" else "SELL",
                order_type="MARKET",
                amount=str(quote.input_amount),
            )
            result = client.place_order(order)
            tx_hash = result.get("transaction_hash") or result.get("order_id", "")

            return TradeResult(
                success=True, tx_hash=tx_hash, input_amount=quote.input_amount,
                output_amount=quote.expected_output, error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash.startswith("0x") else None,
            )
        except ImportError:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="limitless_sdk not installed", explorer_url=None,
            )
        except Exception as e:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message=str(e), explorer_url=None,
            )


limitless_platform = LimitlessPlatform()
