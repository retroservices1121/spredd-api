"""
Opinion Labs platform adapter.
AI-oracle powered prediction markets on BSC.
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

USDT_BSC = "0x55d398326f99059fF775485246999027B3197955"
CTF_EXCHANGE = "0x5F45344126D6488025B0b84A3A8189F2487a7246"
CONDITIONAL_TOKENS = "0xbB5f35D40132A0478f6aa91e79962e9F752167EA"

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


class OpinionPlatform(BasePlatform):
    platform = PlatformSlug.OPINION
    chain = ChainSlug.BSC
    name = "Opinion"
    description = "AI-oracle powered prediction markets on BSC"
    collateral_symbol = "USDT"
    collateral_decimals = 18

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._fee_bps = settings.evm_fee_bps
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self._cache_ttl = 300

    async def initialize(self) -> None:
        headers = {"Content-Type": "application/json"}
        if settings.opinion_api_key:
            headers["x-api-key"] = settings.opinion_api_key
        self._http = httpx.AsyncClient(
            base_url=settings.opinion_api_url, timeout=30.0, headers=headers,
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        resp = await self._http.request(method, endpoint, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "opinion", "429")
        resp.raise_for_status()
        return resp.json()

    def _parse_market(self, data: dict) -> Market:
        yes_price = no_price = None
        outcomes = data.get("outcomes", [])
        if len(outcomes) >= 2:
            yes_price = Decimal(str(outcomes[0].get("price", 0)))
            no_price = Decimal(str(outcomes[1].get("price", 0)))
        elif data.get("yes_price"):
            yes_price = Decimal(str(data["yes_price"]))
            no_price = Decimal(str(data.get("no_price", 1 - float(yes_price))))

        yes_token = outcomes[0].get("token_id") if len(outcomes) > 0 else None
        no_token = outcomes[1].get("token_id") if len(outcomes) > 1 else None

        return Market(
            platform=PlatformSlug.OPINION,
            chain=ChainSlug.BSC,
            market_id=str(data.get("id") or data.get("market_id")),
            event_id=data.get("category"),
            title=data.get("title") or data.get("question", ""),
            description=data.get("description"),
            category=data.get("category"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
            liquidity=Decimal(str(data.get("liquidity", 0))) if data.get("liquidity") else None,
            is_active=data.get("status") in ("active", "open", None),
            close_time=data.get("end_date") or data.get("endDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            collateral_token="USDT",
            url=f"https://opinion.trade/market/{data.get('id', '')}",
        )

    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[offset : offset + limit]

        data = await self._request("GET", "/markets", params={"limit": 200, "status": "active"})
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
            side = "yes" if outcome == Outcome.YES else "no"
            bids = [(Decimal(str(b["price"])), Decimal(str(b["size"]))) for b in data.get(f"{side}_bids", data.get("bids", []))]
            asks = [(Decimal(str(a["price"])), Decimal(str(a["size"]))) for a in data.get(f"{side}_asks", data.get("asks", []))]
        except Exception:
            bids, asks = [], []
        return OrderBook(market_id=market_id, outcome=outcome, bids=bids, asks=asks)

    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "opinion")

        # Get orderbook for live pricing
        ob = await self.get_orderbook(market_id, outcome)
        if side == "buy":
            price = ob.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price if price > 0 else Decimal(0)
        else:
            price = ob.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token

        return Quote(
            platform=PlatformSlug.OPINION,
            chain=ChainSlug.BSC,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=USDT_BSC if side == "buy" else (token_id or ""),
            input_amount=amount,
            output_token=(token_id or "") if side == "buy" else USDT_BSC,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=ob.spread,
            platform_fee=amount * Decimal(self._fee_bps) / Decimal(10000),
            network_fee_estimate=Decimal("0.001"),
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
        usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_BSC), abi=ERC20_ABI)

        # Approve USDT for CTF Exchange
        approve_data = usdt.encode_abi("approve", args=[Web3.to_checksum_address(CTF_EXCHANGE), amount_raw])
        txs.append(PreparedTransaction(
            to=USDT_BSC, data=approve_data, value="0",
            gas="100000", chain_id=56, description="Approve USDT for Opinion exchange",
        ))
        # Approve USDT for Conditional Tokens
        approve_ct = usdt.encode_abi("approve", args=[Web3.to_checksum_address(CONDITIONAL_TOKENS), amount_raw])
        txs.append(PreparedTransaction(
            to=USDT_BSC, data=approve_ct, value="0",
            gas="100000", chain_id=56, description="Approve USDT for Conditional Tokens",
        ))

        # Trade via SDK (placeholder calldata)
        txs.append(PreparedTransaction(
            to=CTF_EXCHANGE,
            data=f"0x_opinion_trade_{market_id}_{outcome.value}_{side}",
            value="0", gas="300000", chain_id=56,
            description=f"{side.upper()} {outcome.value.upper()} on {market_id}",
        ))

        # Fee transfer
        if self._fee_bps > 0 and settings.evm_fee_account:
            fee_raw = int(amount * Decimal(self._fee_bps) / Decimal(10000) * Decimal(10**self.collateral_decimals))
            fee_data = usdt.encode_abi("approve", args=[Web3.to_checksum_address(settings.evm_fee_account), fee_raw])
            txs.append(PreparedTransaction(
                to=USDT_BSC, data=fee_data, value="0",
                gas="60000", chain_id=56, description=f"Platform fee: {self._fee_bps/100}%",
            ))

        return txs, quote

    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        if not isinstance(private_key, LocalAccount):
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="Invalid key type, expected EVM LocalAccount", explorer_url=None,
            )

        try:
            w3 = Web3(Web3.HTTPProvider(settings.bsc_rpc_url))
            wallet = private_key.address

            # Enable trading EOA: approve USDT for both contracts
            usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_BSC), abi=ERC20_ABI)
            amount_raw = int(quote.input_amount * Decimal(10**self.collateral_decimals))

            for spender in [CTF_EXCHANGE, CONDITIONAL_TOKENS]:
                spender_addr = Web3.to_checksum_address(spender)
                allowance = usdt.functions.allowance(wallet, spender_addr).call()
                if allowance < amount_raw:
                    nonce = w3.eth.get_transaction_count(wallet)
                    approve_tx = usdt.functions.approve(spender_addr, 2**256 - 1).build_transaction({
                        "from": wallet, "nonce": nonce,
                        "gasPrice": int(w3.eth.gas_price * 1.1),
                        "gas": 100000, "chainId": 56,
                    })
                    signed = w3.eth.account.sign_transaction(approve_tx, private_key.key)
                    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            # Execute via Opinion CLOB SDK
            try:
                from opinion_clob_sdk import ClobClient, PlaceOrderDataInput
                sdk = ClobClient(
                    api_key=settings.opinion_api_key,
                    private_key=private_key.key.hex(),
                )
                order = PlaceOrderDataInput(
                    market_id=quote.market_id,
                    token_id=quote.quote_data.get("token_id"),
                    side="BUY" if quote.side == "buy" else "SELL",
                    order_type="market",
                    amount=str(quote.input_amount),
                )
                result = sdk.place_order(order)
                order_id = result.get("order_id") or result.get("id", "")

                return TradeResult(
                    success=True, tx_hash=order_id, input_amount=quote.input_amount,
                    output_amount=quote.expected_output, error_message=None,
                    explorer_url=self.get_explorer_url(order_id) if order_id.startswith("0x") else None,
                )
            except ImportError:
                return TradeResult(
                    success=False, tx_hash=None, input_amount=quote.input_amount,
                    output_amount=None, error_message="opinion_clob_sdk not installed", explorer_url=None,
                )
        except Exception as e:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message=str(e), explorer_url=None,
            )


opinion_platform = OpinionPlatform()
