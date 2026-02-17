"""Platform registry — singleton that manages all platform adapters."""

import logging
from typing import Optional

from app.platforms.base import BasePlatform, PlatformSlug
from app.platforms.kalshi import kalshi_platform
from app.platforms.limitless import limitless_platform
from app.platforms.myriad import myriad_platform
from app.platforms.opinion import opinion_platform
from app.platforms.polymarket import polymarket_platform

logger = logging.getLogger(__name__)


class PlatformRegistry:
    def __init__(self):
        self._platforms: dict[str, BasePlatform] = {
            PlatformSlug.KALSHI: kalshi_platform,
            PlatformSlug.POLYMARKET: polymarket_platform,
            PlatformSlug.MYRIAD: myriad_platform,
            PlatformSlug.OPINION: opinion_platform,
            PlatformSlug.LIMITLESS: limitless_platform,
        }

    def get(self, slug: str) -> Optional[BasePlatform]:
        return self._platforms.get(slug)

    def all(self) -> dict[str, BasePlatform]:
        return self._platforms

    def list_platforms(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "slug": slug,
                "chain": p.chain.value,
                "collateral": p.collateral_symbol,
                "description": p.description,
            }
            for slug, p in self._platforms.items()
        ]

    async def initialize_all(self) -> None:
        for slug, p in self._platforms.items():
            try:
                await p.initialize()
                logger.info(f"Initialized platform: {p.name}")
            except Exception as e:
                logger.warning(f"Failed to initialize {p.name}: {e}")

    async def close_all(self) -> None:
        for p in self._platforms.values():
            try:
                await p.close()
            except Exception:
                pass


platform_registry = PlatformRegistry()
