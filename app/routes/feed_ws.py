import asyncio
import json
import logging
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth.api_keys import hash_api_key, validate_key_format
from app.db.engine import async_session
from app.db.models import APIKey
from app.services.canary import canary_generator
from app.services.feed_service import sync_all_markets

logger = logging.getLogger(__name__)

router = APIRouter()

_clients: set[WebSocket] = set()
_broadcast_task: asyncio.Task | None = None


async def _authenticate_ws(api_key_raw: str) -> bool:
    if not validate_key_format(api_key_raw):
        return False
    key_hash = hash_api_key(api_key_raw)
    async with async_session() as session:
        result = await session.execute(
            select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
        )
        return result.scalar_one_or_none() is not None


async def broadcast_loop(interval: int = 5) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            if not _clients:
                continue

            markets = await sync_all_markets()
            canary = canary_generator.current
            now_ms = int(time.time() * 1000)

            payload = json.dumps(
                {
                    "type": "market_snapshot",
                    "data_timestamp": now_ms,
                    "markets": [m.model_dump() for m in markets],
                    "canary": canary.model_dump(),
                }
            )

            dead: list[WebSocket] = []
            for ws in _clients.copy():
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _clients.discard(ws)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Feed broadcast error: {e}")
            await asyncio.sleep(1)


@router.websocket("/ws")
async def feed_websocket(
    ws: WebSocket,
    api_key: str = Query(..., description="API key for authentication"),
) -> None:
    if not await _authenticate_ws(api_key):
        await ws.close(code=4001, reason="Invalid or revoked API key")
        return

    await ws.accept()
    _clients.add(ws)
    logger.info(f"Feed WS client connected (total: {len(_clients)})")

    try:
        while True:
            data = await ws.receive_text()
            if data.strip().lower() == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Feed WS error: {e}")
    finally:
        _clients.discard(ws)
        logger.info(f"Feed WS client disconnected (total: {len(_clients)})")
