import time
from collections import defaultdict


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: int, period: float = 60.0):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.period))
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    @property
    def remaining(self) -> int:
        return int(self.tokens)

    @property
    def reset_in(self) -> float:
        if self.tokens >= 1:
            return 0.0
        needed = 1 - self.tokens
        return needed / (self.rate / self.period)


class RateLimiterStore:
    """In-memory rate limiter keyed by (key_id, bucket_type)."""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = defaultdict()

    def get_bucket(self, key_id: str, bucket_type: str, rate: int) -> TokenBucket:
        cache_key = f"{key_id}:{bucket_type}"
        if cache_key not in self._buckets:
            self._buckets[cache_key] = TokenBucket(rate=rate)
        return self._buckets[cache_key]

    def check_request_limit(self, key_id: str, rpm: int) -> TokenBucket:
        return self.get_bucket(key_id, "rpm", rpm)

    def check_trade_limit(self, key_id: str, tpm: int) -> TokenBucket:
        return self.get_bucket(key_id, "tpm", tpm)


rate_limiter_store = RateLimiterStore()
