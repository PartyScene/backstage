import time
import logging
import hashlib
from functools import wraps
from typing import Optional, Callable

from quart import Quart, request, jsonify, current_app
from shared.utils import get_client_ip

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Atomic Lua script: INCR the counter, set EXPIRE on first write, return count.
# One round-trip — eliminates GET-then-SET and check-then-record race conditions.
# KEYS[1] : window key  |  ARGV[1] : TTL in seconds
# ---------------------------------------------------------------------------
_RATE_LIMIT_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


async def _ip_key() -> str:
    """Rate limit key derived from IP + User-Agent (SHA-256, 16 hex chars)."""
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    digest = hashlib.sha256(f"{ip}:{user_agent}".encode()).hexdigest()[:16]
    return f"rate_limit:{digest}"


async def _user_key() -> str:
    """Rate limit key from JWT user ID; falls back to IP key if unauthenticated."""
    try:
        from quart_jwt_extended import verify_jwt_in_request, get_jwt_identity
        await verify_jwt_in_request()
        user_id = get_jwt_identity()
        if user_id:
            return f"rate_limit:user:{user_id}"
    except Exception:
        pass
    return await _ip_key()


async def _run_windows(
    redis,
    key: str,
    per_minute: int,
    per_hour: int,
    per_day: int,
) -> tuple[bool, int]:
    """Atomically increment all three windows; return (is_limited, retry_after)."""
    current_time = int(time.time())
    windows = [
        (60,    per_minute, "minute"),
        (3600,  per_hour,   "hour"),
        (86400, per_day,    "day"),
    ]
    for window_size, limit, window_name in windows:
        window_key = f"{key}:{window_name}:{current_time // window_size}"
        try:
            count = int(await redis.eval(_RATE_LIMIT_LUA, 1, window_key, window_size * 2))
            if count > limit:
                retry_after = window_size - (current_time % window_size)
                return True, retry_after
        except Exception as exc:
            logger.error("Redis rate limit error (%s): %s", window_name, exc)
            return False, 0  # fail open when Redis is unavailable
    return False, 0


class RateLimitMiddleware:
    """Rate limiting middleware backed by Redis atomic Lua scripts."""

    def __init__(self, app: Quart):
        self.app = app

    def rate_limit(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        requests_per_day: int = 10000,
        key_func: Optional[Callable] = None,
        by_user: bool = False,
    ):
        """
        Rate limiting decorator (attached to middleware instance).

        Args:
            requests_per_minute: Max requests allowed per minute.
            requests_per_hour: Max requests allowed per hour.
            requests_per_day: Max requests allowed per day.
            key_func: Optional async callable returning a custom Redis key.
            by_user: When True, rate-limit by JWT user ID instead of IP.
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                if key_func:
                    key = await key_func()
                elif by_user:
                    key = await _user_key()
                else:
                    key = await _ip_key()

                is_limited, retry_after = await _run_windows(
                    self.app.redis,
                    key,
                    requests_per_minute,
                    requests_per_hour,
                    requests_per_day,
                )
                if is_limited:
                    logger.warning("Rate limit exceeded for key: %s", key)
                    return (
                        jsonify({"error": "Rate limit exceeded", "retry_after": retry_after}),
                        429,
                        {"Retry-After": str(retry_after)},
                    )
                return await f(*args, **kwargs)

            return decorated_function
        return decorator


def rate_limit(
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
    requests_per_day: int = 10000,
    by_user: bool = False,
    key_func: Optional[Callable] = None,
):
    """
    Standalone rate limit decorator for class-based views.
    Resolves ``current_app.redis`` at request time — no middleware instance needed.

    Args:
        requests_per_minute: Max requests allowed per minute.
        requests_per_hour: Max requests allowed per hour.
        requests_per_day: Max requests allowed per day.
        by_user: When True, rate-limit by JWT user ID instead of IP.
        key_func: Optional async callable returning a custom Redis key.
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            if key_func:
                key = await key_func()
            elif by_user:
                key = await _user_key()
            else:
                key = await _ip_key()

            is_limited, retry_after = await _run_windows(
                current_app.redis,
                key,
                requests_per_minute,
                requests_per_hour,
                requests_per_day,
            )
            if is_limited:
                logger.warning("Rate limit exceeded for key: %s", key)
                return (
                    jsonify({"error": "Rate limit exceeded", "retry_after": retry_after}),
                    429,
                    {"Retry-After": str(retry_after)},
                )
            return await f(*args, **kwargs)

        return decorated_function
    return decorator


class GlobalRateLimits:
    """Predefined rate limit tiers for different endpoint categories."""

    # OTP endpoints — very strict to prevent email bombing and brute force
    OTP_LIMITS = {
        "requests_per_minute": 3,
        "requests_per_hour": 10,
        "requests_per_day": 20,
    }

    # Authentication endpoints — strict
    AUTH_LIMITS = {
        "requests_per_minute": 10,
        "requests_per_hour": 100,
        "requests_per_day": 500,
    }

    # Media upload endpoints — moderate
    MEDIA_LIMITS = {
        "requests_per_minute": 30,
        "requests_per_hour": 500,
        "requests_per_day": 2000,
    }

    # General API endpoints — standard
    API_LIMITS = {
        "requests_per_minute": 60,
        "requests_per_hour": 1000,
        "requests_per_day": 10000,
    }

    # Public read endpoints — generous
    PUBLIC_LIMITS = {
        "requests_per_minute": 120,
        "requests_per_hour": 2000,
        "requests_per_day": 20000,
    }
