import time
import logging
from quart import Quart
from typing import Optional, Dict, Any
from quart import request, jsonify, current_app
from redis.asyncio import Redis
from functools import wraps
import hashlib
from shared.utils import get_client_ip
from quart_jwt_extended import verify_jwt_in_request, get_jwt_identity

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
        skip_successful_requests: bool = False,
        use_user_id: bool = False
    ):
        """
        Rate limiting decorator with multiple time windows
        
        Args:
            requests_per_minute: Max requests per minute
            requests_per_hour: Max requests per hour  
            requests_per_day: Max requests per day
            key_func: Custom function to generate rate limit key
            skip_successful_requests: Only count failed requests
            use_user_id: Use authenticated user ID instead of IP for rate limiting
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                # Generate rate limit key
                if key_func:
                    key = await key_func()
                elif use_user_id:
                    key = await self._user_key_func()
                else:
                    key = await self._default_key_func()
                
                # Atomic check and record - eliminates race condition
                is_limited, retry_after = await self._check_and_record_atomic(
                    key, requests_per_minute, requests_per_hour, requests_per_day
                )
                
                if is_limited:
                    logger.warning(f"Rate limit exceeded for key: {key}")
                    return jsonify({
                        "error": "Rate limit exceeded",
                        "retry_after": retry_after
                    }), 429, {"Retry-After": str(retry_after)}
                
                # Execute the function
                result = await f(*args, **kwargs)
                return result
                    
            return decorated_function
        return decorator
    
    async def _default_key_func(self) -> str:
        """Generate default rate limit key based on IP and user"""
        ip = get_client_ip(request)
        user_agent = request.headers.get('User-Agent', '')
        
        # Create a hash for privacy
        key_data = f"{ip}:{user_agent}"
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        
        return f"rate_limit:ip:{key_hash}"
    
    async def _user_key_func(self) -> str:
        """Generate rate limit key based on authenticated user ID"""
        try:
            await verify_jwt_in_request()
            user_id = get_jwt_identity()
            return f"rate_limit:user:{user_id}"
        except:
            # Fall back to IP-based if not authenticated
            return await self._default_key_func()
    
    async def _check_and_record_atomic(
        self, 
        key: str, 
        per_minute: int, 
        per_hour: int, 
        per_day: int
    ) -> tuple[bool, int]:
        """Atomically check and record request to eliminate race conditions"""
        current_time = int(time.time())
        
        # Define time windows
        windows = [
            (60, per_minute, "minute"),
            (3600, per_hour, "hour"), 
            (86400, per_day, "day")
        ]
        
        try:
            # Use pipeline for atomic operations
            pipe = self.app.redis.pipeline()
            
            # Increment all windows atomically
            window_keys = []
            for window_size, limit, window_name in windows:
                window_key = f"{key}:{window_name}:{current_time // window_size}"
                window_keys.append((window_key, window_size, limit, window_name))
                pipe.incr(window_key)
            
            # Execute all increments atomically
            results = await pipe.execute()
            
            # Set expiry for new keys (non-atomic but safe)
            pipe = self.app.redis.pipeline()
            for i, (window_key, window_size, limit, window_name) in enumerate(window_keys):
                new_count = results[i]
                if new_count == 1:
                    # First request in this window, set expiry
                    pipe.expire(window_key, window_size * 2)
            await pipe.execute()
            
            # Check if any limit was exceeded
            for i, (window_key, window_size, limit, window_name) in enumerate(window_keys):
                current_count = results[i]
                if current_count > limit:
                    # Calculate retry after
                    retry_after = window_size - (current_time % window_size)
                    logger.warning(f"Rate limit exceeded: {current_count}/{limit} for {window_name} window")
                    return True, retry_after
            
            return False, 0
                    
        except Exception as e:
            logger.error(f"Redis error in rate limiting: {e}")
            # Fail open - allow request if Redis is down
            return False, 0

# Global rate limiting for different endpoint types
class GlobalRateLimits:
    """Predefined rate limits for different endpoint categories"""
    
    # OTP endpoints - very strict limits to prevent abuse
    OTP_LIMITS = {
        "requests_per_minute": 3,
        "requests_per_hour": 10,
        "requests_per_day": 20
    }
    
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
