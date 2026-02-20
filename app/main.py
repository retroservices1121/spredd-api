import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.platforms.registry import platform_registry
from app.routes.feed_ws import broadcast_loop
from app.services.canary import canary_generator


@asynccontextmanager
async def lifespan(app: FastAPI):
    await platform_registry.initialize_all()

    # Initialize canary with configured interval
    canary_generator._interval = settings.feed_canary_interval_seconds
    canary_generator.generate()

    # Start WebSocket broadcast loop
    task = asyncio.create_task(broadcast_loop(interval=settings.feed_ws_interval_seconds))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await platform_registry.close_all()


app = FastAPI(
    title="Spredd Developer API",
    description="Prediction market trading API — market data, quotes, trade execution, positions, and arbitrage across Kalshi, Polymarket, Myriad, Opinion, and Limitless.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routes import arbitrage, auth, feed, feed_ws, markets, positions, trading, usage  # noqa: E402

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(markets.router, prefix="/v1", tags=["Markets"])
app.include_router(trading.router, prefix="/v1/trading", tags=["Trading"])
app.include_router(positions.router, prefix="/v1", tags=["Positions"])
app.include_router(arbitrage.router, prefix="/v1", tags=["Arbitrage"])
app.include_router(usage.router, prefix="/v1", tags=["Usage"])
app.include_router(feed.router, prefix="/v1/feed", tags=["Feed"])
app.include_router(feed_ws.router, prefix="/v1/feed", tags=["Feed WebSocket"])


@app.get("/health")
async def health():
    return {"status": "ok"}
