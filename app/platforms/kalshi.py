"""
Kalshi platform adapter using DFlow API.
Trades Kalshi prediction markets on Solana.
"""

import base64
import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

import httpx
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

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

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
KALSHI_PUBLIC_API = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiPlatform(BasePlatform):
    platform = PlatformSlug.KALSHI
    chain = ChainSlug.SOLANA
    name = "Kalshi"
    description = "CFTC-regulated prediction markets on Solana"
    collateral_symbol = "USDC"
    collateral_decimals = 6

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._solana: Optional[SolanaClient] = None
        self._fee_account = settings.kalshi_fee_account
        self._fee_bps = settings.kalshi_fee_bps
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self._cache_ttl = 300

    async def initialize(self) -> None:
        headers = {"Content-Type": "application/json"}
        if settings.dflow_api_key:
            headers["x-api-key"] = settings.dflow_api_key
        self._http = httpx.AsyncClient(timeout=30.0, headers=headers)
        self._solana = SolanaClient(settings.solana_rpc_url)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
        if self._solana:
            await self._solana.close()

    async def _metadata_request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{settings.dflow_metadata_url}{endpoint}"
        resp = await self._http.request(method, url, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "kalshi", "429")
        resp.raise_for_status()
        return resp.json()

    async def _trading_request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{settings.dflow_api_base_url}{endpoint}"
        resp = await self._http.request(method, url, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "kalshi", "429")
        resp.raise_for_status()
        return resp.json()

    def _parse_market(self, data: dict) -> Market:
        yes_price = Decimal(str(data["yesAsk"])) if data.get("yesAsk") else None
        no_price = Decimal(str(data["noAsk"])) if data.get("noAsk") else None

        yes_token = no_token = None
        accounts = data.get("accounts", {})
        if USDC_MINT in accounts:
            yes_token = accounts[USDC_MINT].get("yesMint")
            no_token = accounts[USDC_MINT].get("noMint")

        return Market(
            platform=PlatformSlug.KALSHI,
            chain=ChainSlug.SOLANA,
            market_id=data.get("ticker") or data.get("market_ticker"),
            event_id=data.get("eventTicker") or data.get("event_ticker"),
            title=data.get("title") or data.get("question", ""),
            description=data.get("subtitle"),
            category=data.get("category"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
            liquidity=Decimal(str(data.get("openInterest", 0))) if data.get("openInterest") else None,
            is_active=data.get("status") == "active" or data.get("result") is None,
            close_time=data.get("closeTime") or data.get("close_time"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            collateral_token="USDC",
        )

    async def _fetch_all_markets(self) -> list[Market]:
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache

        all_markets = []
        cursor = None
        for _ in range(25):
            params = {"limit": 200, "status": "active"}
            if cursor:
                params["cursor"] = cursor
            try:
                data = await self._metadata_request("GET", "/api/v1/markets", params=params)
            except Exception:
                break
            page = data.get("markets", data.get("data", []))
            for item in page:
                try:
                    all_markets.append(self._parse_market(item))
                except Exception:
                    continue
            new_cursor = data.get("cursor")
            if not new_cursor or not page:
                break
            cursor = new_cursor

        # Detect multi-outcome events
        event_groups: dict[str, list[Market]] = defaultdict(list)
        for m in all_markets:
            if m.event_id:
                event_groups[m.event_id].append(m)

        for event_id, group in event_groups.items():
            if len(group) > 1:
                try:
                    names = await self._fetch_event_names(event_id)
                except Exception:
                    names = {}
                for m in group:
                    m.is_multi_outcome = True
                    m.related_market_count = len(group)
                    m.outcome_name = names.get(m.market_id)

        self._markets_cache = all_markets
        self._markets_cache_time = now
        return all_markets

    async def _fetch_event_names(self, event_id: str) -> dict[str, str]:
        names: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{KALSHI_PUBLIC_API}/events/{event_id}")
                if resp.status_code == 200:
                    for mkt in resp.json().get("markets", []):
                        ticker = mkt.get("ticker")
                        name = mkt.get("yes_sub_title") or mkt.get("subtitle")
                        if ticker and name:
                            names[ticker] = name
        except Exception:
            pass
        return names

    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        all_markets = await self._fetch_all_markets()
        return all_markets[offset : offset + limit]

    async def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        all_markets = await self._fetch_all_markets()
        q = query.lower()
        return [m for m in all_markets if q in m.title.lower() or (m.description and q in m.description.lower())][:limit]

    async def get_market(self, market_id: str) -> Optional[Market]:
        all_markets = await self._fetch_all_markets()
        for m in all_markets:
            if m.market_id == market_id:
                return m
        try:
            data = await self._metadata_request("GET", f"/api/v1/market/{market_id}")
            return self._parse_market(data.get("market", data))
        except Exception:
            return None

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> OrderBook:
        data = await self._metadata_request("GET", f"/api/v1/orderbook/{market_id}")
        bids, asks = [], []
        side_key = "yes" if outcome == Outcome.YES else "no"
        opposite_key = "no" if outcome == Outcome.YES else "yes"

        for price_str, qty in data.get(f"{side_key}_bids", {}).items():
            bids.append((Decimal(price_str), Decimal(str(qty))))
        bids.sort(key=lambda x: x[0], reverse=True)

        for price_str, qty in data.get(f"{opposite_key}_bids", {}).items():
            asks.append((Decimal("1") - Decimal(price_str), Decimal(str(qty))))
        asks.sort(key=lambda x: x[0])

        return OrderBook(market_id=market_id, outcome=outcome, bids=bids, asks=asks)

    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "kalshi")

        output_token = market.yes_token if outcome == Outcome.YES else market.no_token
        if not output_token:
            raise PlatformError(f"Token not found for {outcome.value}", "kalshi")

        input_token = USDC_MINT
        amount_raw = int(amount * Decimal(10**self.collateral_decimals))

        params = {
            "inputMint": input_token if side == "buy" else output_token,
            "outputMint": output_token if side == "buy" else input_token,
            "amount": str(amount_raw),
            "slippageBps": 100,
        }
        data = await self._trading_request("GET", "/order", params=params)

        in_raw = Decimal(str(data.get("inAmount", 0)))
        out_raw = Decimal(str(data.get("outAmount", 0)))
        actual_input = in_raw / Decimal(10**self.collateral_decimals)
        expected_output = out_raw / Decimal(10**self.collateral_decimals)
        price_per_token = actual_input / expected_output if expected_output > 0 else Decimal(0)

        pi = data.get("priceImpactPct")
        pf = data.get("platformFee")

        return Quote(
            platform=PlatformSlug.KALSHI,
            chain=ChainSlug.SOLANA,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token if side == "buy" else output_token,
            input_amount=actual_input,
            output_token=output_token if side == "buy" else input_token,
            expected_output=expected_output,
            price_per_token=price_per_token,
            price_impact=Decimal(str(pi)) if pi is not None else Decimal(0),
            platform_fee=Decimal(str(pf)) / Decimal(10**6) if pf is not None else Decimal(0),
            network_fee_estimate=Decimal("0.001"),
            expires_at=None,
            quote_data=data,
        )

    async def prepare_transaction(
        self, market_id: str, outcome: Outcome, side: str, amount: Decimal, wallet_address: str
    ) -> tuple[list[PreparedTransaction], Quote]:
        quote = await self.get_quote(market_id, outcome, side, amount)

        params = {
            "inputMint": quote.input_token,
            "outputMint": quote.output_token,
            "amount": str(int(quote.input_amount * Decimal(10**self.collateral_decimals))),
            "slippageBps": 100,
            "userPublicKey": wallet_address,
        }
        if self._fee_account and len(self._fee_account) >= 32:
            params["feeAccount"] = self._fee_account
            params["platformFeeScale"] = str(self._fee_bps // 2)

        data = await self._trading_request("GET", "/order", params=params)
        tx_b64 = data.get("transaction", "")

        txs = [
            PreparedTransaction(
                to="solana_program",
                data=tx_b64,
                value="0",
                gas=None,
                chain_id=0,  # Solana
                description=f"{side.upper()} {outcome.value.upper()} on {market_id}",
            )
        ]
        return txs, quote

    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        if not isinstance(private_key, Keypair):
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="Invalid key type, expected Solana Keypair", explorer_url=None,
            )

        try:
            params = {
                "inputMint": quote.input_token,
                "outputMint": quote.output_token,
                "amount": str(int(quote.input_amount * Decimal(10**self.collateral_decimals))),
                "slippageBps": 100,
                "userPublicKey": str(private_key.pubkey()),
            }
            if self._fee_account and len(self._fee_account) >= 32:
                params["feeAccount"] = self._fee_account
                params["platformFeeScale"] = str(self._fee_bps // 2)

            response = await self._trading_request("GET", "/order", params=params)
            tx_data = base64.b64decode(response["transaction"])
            tx = VersionedTransaction.from_bytes(tx_data)
            signed_tx = VersionedTransaction(tx.message, [private_key])

            result = await self._solana.send_transaction(
                signed_tx, opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            )
            tx_hash = str(result.value)

            return TradeResult(
                success=True, tx_hash=tx_hash, input_amount=quote.input_amount,
                output_amount=quote.expected_output, error_message=None,
                explorer_url=self.get_explorer_url(tx_hash),
            )
        except Exception as e:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message=str(e), explorer_url=None,
            )


kalshi_platform = KalshiPlatform()
