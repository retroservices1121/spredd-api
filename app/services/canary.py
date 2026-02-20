import random
import time

from app.schemas.feed import CanaryMarket


class CanaryGenerator:
    def __init__(self, interval_seconds: int = 60):
        self._interval = interval_seconds
        self._current: CanaryMarket | None = None
        self._last_rotation: float = 0.0

    def generate(self) -> CanaryMarket:
        price = round(random.uniform(0.01, 0.99), 4)
        now_ms = int(time.time() * 1000)
        self._current = CanaryMarket(
            outcomes={"yes": price, "no": round(1.0 - price, 4)},
            expected_price=price,
            injected_at=now_ms,
        )
        self._last_rotation = time.monotonic()
        return self._current

    @property
    def current(self) -> CanaryMarket:
        if self._current is None or self.should_rotate():
            self.generate()
        return self._current  # type: ignore[return-value]

    def should_rotate(self) -> bool:
        if self._last_rotation == 0.0:
            return True
        return (time.monotonic() - self._last_rotation) >= self._interval


canary_generator = CanaryGenerator()
