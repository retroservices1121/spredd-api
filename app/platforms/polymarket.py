"""
Polymarket platform adapter using CLOB API.
World's largest prediction market on Polygon.
"""

import json
import logging
import time
from decimal import Decimal
from typing import Any, Optional

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

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

EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
]


class PolymarketPlatform(BasePlatform):
    platform = PlatformSlug.POLYMARKET
    chain = ChainSlug.POLYGON
    name = "Polymarket"
    description = "World's largest prediction market on Polygon"
    collateral_symbol = "USDC"
    collateral_decimals = 6

    def __init__(self):
        self._clob: Optional[httpx.AsyncClient] = None
        self._gamma: Optional[httpx.AsyncClient] = None
        self._web3: Optional[AsyncWeb3] = None
        self._fee_account = settings.evm_fee_account
        self._fee_bps = settings.evm_fee_bps
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self._cache_ttl = 120

    async def initialize(self) -> None:
        self._clob = httpx.AsyncClient(
            base_url=settings.polymarket_api_url, timeout=30.0,
            headers={"Content-Type": "application/json"},
        )
        self._gamma = httpx.AsyncClient(
            base_url="https://gamma-api.polymarket.com", timeout=30.0,
            headers={"Content-Type": "application/json"},
        )
        self._web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(settings.polygon_rpc_url))

    async def close(self) -> None:
        if self._clob:
            await self._clob.aclose()
        if self._gamma:
            await self._gamma.aclose()

    async def _gamma_request(self, method: str, endpoint: str, **kwargs) -> Any:
        resp = await self._gamma.request(method, endpoint, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "polymarket", "429")
        resp.raise_for_status()
        return resp.json()

    async def _clob_request(self, method: str, endpoint: str, **kwargs) -> dict:
        resp = await self._clob.request(method, endpoint, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "polymarket", "429")
        resp.raise_for_status()
        return resp.json()

    def _parse_market(self, data: dict, market_data: dict = None) -> Market:
        event_markets = data.get("markets", [])
        is_multi = len(event_markets) > 1

        if market_data:
            m = market_data
            title = data.get("title") or m.get("question", "")
            outcome_name = m.get("groupItemTitle")
        else:
            m = event_markets[0] if event_markets else data
            title = data.get("title") or m.get("question", "")
            outcome_name = None

        # Parse prices
        prices_raw = m.get("outcomePrices", [])
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        yes_price = no_price = None
        if prices and len(prices) >= 2:
            try:
                yes_price = Decimal(str(prices[0]))
                no_price = Decimal(str(prices[1]))
            except Exception:
                pass
        if yes_price is None and m.get("lastTradePrice") is not None:
            yes_price = Decimal(str(m["lastTradePrice"]))
            no_price = Decimal("1") - yes_price

        # Parse tokens
        tokens_raw = m.get("clobTokenIds", [])
        tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
        yes_token = tokens[0] if len(tokens) > 0 else None
        no_token = tokens[1] if len(tokens) > 1 else None

        market_id = m.get("conditionId") or str(m.get("id") or data.get("id"))
        volume = m.get("volume") or m.get("volumeNum") or data.get("volume") or 0
        liquidity_val = m.get("liquidity") or data.get("liquidity") or 0

        return Market(
            platform=PlatformSlug.POLYMARKET,
            chain=ChainSlug.POLYGON,
            market_id=market_id,
            event_id=str(data.get("id") or data.get("slug", "")),
            title=title,
            description=m.get("description") or data.get("description"),
            category=(data.get("tags", [{}])[0].get("label") if data.get("tags") else None),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(volume)),
            liquidity=Decimal(str(liquidity_val)),
            is_active=m.get("active", True) and not m.get("closed", False),
            close_time=m.get("endDate") or data.get("endDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data={"event": data, "market": m},
            outcome_name=outcome_name,
            is_multi_outcome=is_multi,
            related_market_count=len(event_markets) if is_multi else 0,
            collateral_token="USDC.e",
            url=f"https://polymarket.com/event/{data.get('slug', '')}",
        )

    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[offset : offset + limit]

        params = {"limit": 2000, "order": "volume24hr", "ascending": "false"}
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"

        data = await self._gamma_request("GET", "/events", params=params)
        markets = []
        for event in (data if isinstance(data, list) else []):
            try:
                event_markets = event.get("markets", [])
                if len(event_markets) <= 1:
                    markets.append(self._parse_market(event))
                else:
                    active = [em for em in event_markets if em.get("active", True) and not em.get("closed", False)]
                    if active:
                        markets.append(self._parse_market(event, active[0]))
            except Exception:
                continue

        self._markets_cache = markets
        self._markets_cache_time = now
        return markets[offset : offset + limit]

    async def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        data = await self._gamma_request("GET", "/events", params={
            "active": "true", "closed": "false", "limit": 1000,
            "order": "volume24hr", "ascending": "false",
        })
        q = query.lower()
        results = []
        for event in (data if isinstance(data, list) else []):
            title = event.get("title", "").lower()
            desc = event.get("description", "").lower()
            if q in title or q in desc:
                try:
                    results.append(self._parse_market(event))
                except Exception:
                    continue
        return results[:limit]

    async def get_market(self, market_id: str) -> Optional[Market]:
        # Try cache first
        for m in self._markets_cache:
            if m.market_id == market_id:
                return m
        # Fetch by condition ID from gamma
        try:
            data = await self._gamma_request("GET", "/events", params={
                "limit": 10, "id": market_id,
            })
            if isinstance(data, list) and data:
                return self._parse_market(data[0])
        except Exception:
            pass
        return None

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> OrderBook:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "polymarket")

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token ID not found for {outcome.value}", "polymarket")

        data = await self._clob_request("GET", f"/book", params={"token_id": token_id})
        bids = [(Decimal(str(b["price"])), Decimal(str(b["size"]))) for b in data.get("bids", [])]
        asks = [(Decimal(str(a["price"])), Decimal(str(a["size"]))) for a in data.get("asks", [])]
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        return OrderBook(market_id=market_id, outcome=outcome, bids=bids, asks=asks)

    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "polymarket")

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", "polymarket")

        # Get orderbook for pricing
        ob = await self.get_orderbook(market_id, outcome)
        if side == "buy":
            price = ob.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price if price > 0 else Decimal(0)
        else:
            price = ob.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price

        return Quote(
            platform=PlatformSlug.POLYMARKET,
            chain=ChainSlug.POLYGON,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=USDC_POLYGON if side == "buy" else token_id,
            input_amount=amount,
            output_token=token_id if side == "buy" else USDC_POLYGON,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=ob.spread,
            platform_fee=amount * Decimal(self._fee_bps) / Decimal(10000),
            network_fee_estimate=Decimal("0.01"),
            expires_at=None,
            quote_data={"token_id": token_id, "neg_risk": market.raw_data.get("market", {}).get("negRisk", False)},
        )

    async def prepare_transaction(
        self, market_id: str, outcome: Outcome, side: str, amount: Decimal, wallet_address: str
    ) -> tuple[list[PreparedTransaction], Quote]:
        quote = await self.get_quote(market_id, outcome, side, amount)
        neg_risk = quote.quote_data.get("neg_risk", False)
        exchange = NEG_RISK_EXCHANGE if neg_risk else EXCHANGE

        txs = []
        # Approval transaction
        amount_raw = int(amount * Decimal(10**self.collateral_decimals))
        w3 = Web3()
        usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_POLYGON), abi=ERC20_ABI)
        approve_data = usdc.encode_abi("approve", args=[Web3.to_checksum_address(exchange), amount_raw])

        txs.append(PreparedTransaction(
            to=USDC_POLYGON, data=approve_data, value="0",
            gas="100000", chain_id=137, description="Approve USDC for Polymarket exchange",
        ))
        txs.append(PreparedTransaction(
            to=exchange,
            data=f"0x_trade_calldata_placeholder_{quote.quote_data.get('token_id', '')}",
            value="0", gas="300000", chain_id=137,
            description=f"{side.upper()} {outcome.value.upper()} on {market_id}",
        ))
        return txs, quote

    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        if not isinstance(private_key, LocalAccount):
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="Invalid key type, expected EVM LocalAccount", explorer_url=None,
            )

        try:
            neg_risk = quote.quote_data.get("neg_risk", False)
            exchange = Web3.to_checksum_address(NEG_RISK_EXCHANGE if neg_risk else EXCHANGE)
            usdc_addr = Web3.to_checksum_address(USDC_POLYGON)
            wallet = private_key.address

            w3_sync = Web3(Web3.HTTPProvider(settings.polygon_rpc_url))
            usdc = w3_sync.eth.contract(address=usdc_addr, abi=ERC20_ABI)

            # Check and approve
            amount_raw = int(quote.input_amount * Decimal(10**self.collateral_decimals))
            allowance = usdc.functions.allowance(wallet, exchange).call()
            if allowance < amount_raw:
                nonce = w3_sync.eth.get_transaction_count(wallet)
                approve_tx = usdc.functions.approve(exchange, 2**256 - 1).build_transaction({
                    "from": wallet, "nonce": nonce,
                    "gasPrice": int(w3_sync.eth.gas_price * 1.5),
                    "gas": 100000, "chainId": 137,
                })
                signed = w3_sync.eth.account.sign_transaction(approve_tx, private_key.key)
                tx_hash = w3_sync.eth.send_raw_transaction(signed.raw_transaction)
                w3_sync.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            # Build and send trade transaction
            # Using CLOB API for order placement
            token_id = quote.quote_data.get("token_id")
            order_data = {
                "tokenID": token_id,
                "price": str(quote.price_per_token),
                "size": str(quote.input_amount),
                "side": "BUY" if quote.side == "buy" else "SELL",
            }
            resp = await self._clob_request("POST", "/order", json=order_data)
            tx_hash = resp.get("transactionHash") or resp.get("orderID", "")

            return TradeResult(
                success=True, tx_hash=tx_hash, input_amount=quote.input_amount,
                output_amount=quote.expected_output, error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash.startswith("0x") else None,
            )
        except Exception as e:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message=str(e), explorer_url=None,
            )


polymarket_platform = PolymarketPlatform()
