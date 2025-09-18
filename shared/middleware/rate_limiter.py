import time
import logging
from quart import Quart
from typing import Optional, Dict, Any
from quart import request, jsonify, current_app
from redis.asyncio import Redis
from functools import wraps
import hashlib

logger = logging.getLogger(__name__)

class RateLimitMiddleware:
    """Production-ready rate limiting middleware using Redis sliding window"""
    
    def __init__(self, app: Quart):
        self.app = app
        
    def rate_limit(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        requests_per_day: int = 10000,
        key_func: Optional[callable] = None,
        skip_successful_requests: bool = False
    ):
        """
        Rate limiting decorator with multiple time windows
        
        Args:
            requests_per_minute: Max requests per minute
            requests_per_hour: Max requests per hour  
            requests_per_day: Max requests per day
            key_func: Custom function to generate rate limit key
            skip_successful_requests: Only count failed requests
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                # Generate rate limit key
                if key_func:
                    key = await key_func()
                else:
                    key = await self._default_key_func()
                
                # Check rate limits
                is_limited, retry_after = await self._check_rate_limits(
                    key, requests_per_minute, requests_per_hour, requests_per_day
                )
                
                if is_limited:
                    logger.warning(f"Rate limit exceeded for key: {key}")
                    return jsonify({
                        "error": "Rate limit exceeded",
                        "retry_after": retry_after
                    }), 429, {"Retry-After": str(retry_after)}
                
                # Execute the function
                try:
                    result = await f(*args, **kwargs)
                    
                    # Record successful request
                    if not skip_successful_requests:
                        await self._record_request(key)
                    
                    return result
                    
                except Exception as e:
                    # Always record failed requests
                    await self._record_request(key)
                    raise e
                    
            return decorated_function
        return decorator
    
    async def _default_key_func(self) -> str:
        """Generate default rate limit key based on IP and user"""
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', '')
        
        # Create a hash for privacy
        key_data = f"{ip}:{user_agent}"
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        
        return f"rate_limit:{key_hash}"
    
    async def _check_rate_limits(
        self, 
        key: str, 
        per_minute: int, 
        per_hour: int, 
        per_day: int
    ) -> tuple[bool, int]:
        """Check if request exceeds any rate limit"""
        current_time = int(time.time())
        
        # Define time windows
        windows = [
            (60, per_minute, "minute"),
            (3600, per_hour, "hour"), 
            (86400, per_day, "day")
        ]
        
        for window_size, limit, window_name in windows:
            window_key = f"{key}:{window_name}:{current_time // window_size}"
            
            try:
                current_count = await self.app.redis.get(window_key)
                current_count = int(current_count) if current_count else 0
                
                if current_count >= limit:
                    # Calculate retry after
                    retry_after = window_size - (current_time % window_size)
                    return True, retry_after
                    
            except Exception as e:
                logger.error(f"Redis error in rate limiting: {e}")
                # Fail open - allow request if Redis is down
                return False, 0
        
        return False, 0
    
    async def _record_request(self, key: str):
        """Record a request in all time windows"""
        current_time = int(time.time())
        
        windows = [
            (60, "minute"),
            (3600, "hour"),
            (86400, "day")
        ]
        
        try:
            pipe = self.app.redis.pipeline()
            
            for window_size, window_name in windows:
                window_key = f"{key}:{window_name}:{current_time // window_size}"
                pipe.incr(window_key)
                pipe.expire(window_key, window_size * 2)  # Keep for 2 windows
            
            await pipe.execute()
            
        except Exception as e:
            logger.error(f"Failed to record request: {e}")

# Global rate limiting for different endpoint types
class GlobalRateLimits:
    """Predefined rate limits for different endpoint categories"""
    
    # Authentication endpoints - stricter limits
    AUTH_LIMITS = {
        "requests_per_minute": 10,
        "requests_per_hour": 100,
        "requests_per_day": 500
    }
    
    # Media upload endpoints - moderate limits
    MEDIA_LIMITS = {
        "requests_per_minute": 30,
        "requests_per_hour": 500,
        "requests_per_day": 2000
    }
    
    # General API endpoints - standard limits
    API_LIMITS = {
        "requests_per_minute": 60,
        "requests_per_hour": 1000,
        "requests_per_day": 10000
    }
    
    # Public read endpoints - generous limits
    PUBLIC_LIMITS = {
        "requests_per_minute": 120,
        "requests_per_hour": 2000,
        "requests_per_day": 20000
    }
