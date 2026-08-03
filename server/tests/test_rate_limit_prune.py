"""P3: TokenRateLimiter prune key hết hạn."""
from __future__ import annotations

from rate_limit import TokenRateLimiter


def test_rate_limiter_prunes_expired_keys():
    lim = TokenRateLimiter()
    t0 = 1_000_000.0
    for i in range(40):
        lim.check("default", f"tok-{i}", max_hits=10, window_s=1.0, now=t0)
    assert lim.bucket_count() >= 40
    # Sau 120s + một check mới → prune bucket cũ
    lim.check("default", "fresh", max_hits=10, window_s=1.0, now=t0 + 200.0)
    assert lim.bucket_count() <= 2
