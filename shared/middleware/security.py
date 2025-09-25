import logging
from typing import Dict, List, Optional
from quart import request, jsonify, current_app
from functools import wraps
import secrets
import time

logger = logging.getLogger(__name__)

class SecurityMiddleware:
    """Production-ready security middleware with CORS, headers, and size limits"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize security middleware with Quart app"""
        app.config.setdefault('MAX_CONTENT_LENGTH', 100 * 1024 * 1024)  # 100MB
        app.config.setdefault('CORS_ORIGINS', ['https://partyscene.app', 'https://api.partyscene.app'])
        app.config.setdefault('SECURITY_HEADERS', True)
        
        @app.before_request
        async def security_before_request():
            await self._check_request_size()
            await self._check_content_type()
        
        @app.after_request
        async def security_after_request(response):
            if app.config.get('SECURITY_HEADERS', True):
                self._add_security_headers(response)
            self._add_cors_headers(response)
            return response
    
    def cors(self, 
             origins: Optional[List[str]] = None,
             methods: Optional[List[str]] = None,
             headers: Optional[List[str]] = None,
             credentials: bool = True):
        """
        CORS decorator for specific endpoints
        
        Args:
            origins: Allowed origins
            methods: Allowed HTTP methods
            headers: Allowed headers
            credentials: Allow credentials
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                # Handle preflight requests
                if request.method == 'OPTIONS':
                    response = jsonify({'status': 'ok'})
                    self._add_cors_headers(response, origins, methods, headers, credentials)
                    return response
                
                result = await f(*args, **kwargs)
                
                # Add CORS headers to actual response
                if hasattr(result, 'headers'):
                    self._add_cors_headers(result, origins, methods, headers, credentials)
                
                return result
                
            return decorated_function
        return decorator
    
    def require_https(self):
        """Decorator to require HTTPS in production"""
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                if (current_app.config.get('ENV') == 'production' and 
                    not request.is_secure and 
                    not request.headers.get('X-Forwarded-Proto') == 'https'):
                    
                    return jsonify({
                        "error": "HTTPS required",
                        "message": "This endpoint requires HTTPS in production"
                    }), 400
                
                return await f(*args, **kwargs)
                
            return decorated_function
        return decorator
    
    def content_security_policy(self, policy: Dict[str, str]):
        """Add Content Security Policy headers"""
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                result = await f(*args, **kwargs)
                
                if hasattr(result, 'headers'):
                    csp_value = '; '.join([f"{key} {value}" for key, value in policy.items()])
                    result.headers['Content-Security-Policy'] = csp_value
                
                return result
                
            return decorated_function
        return decorator
    
    async def _check_request_size(self):
        """Check if request size exceeds limits"""
        from quart import abort
        max_size = current_app.config.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024)
        
        content_length = request.headers.get('Content-Length')
        if content_length:
            try:
                size = int(content_length)
                if size > max_size:
                    logger.warning(f"Request size {size} exceeds limit {max_size}")
                    abort(413, description={
                        "error": "Request too large",
                        "message": f"Request size {size} exceeds limit {max_size}",
                        "max_size": max_size
                    })
            except ValueError:
                pass
        
    async def _check_content_type(self):
        """
        Validates content type based on content length for POST/PUT/PATCH.
        - If Content-Length > 0, Content-Type must be present and allowed.
        - If Content-Length is 0 or absent, Content-Type must also be absent.
        """
        from quart import abort, request
        # Assuming 'logger' is defined elsewhere in your class/module

        if request.method in ['POST', 'PUT', 'PATCH']:
            content_type = request.headers.get('Content-Type')
            content_length_str = request.headers.get('Content-Length')

            # Safely determine the content length as an integer.
            content_length = 0
            if content_length_str and content_length_str.isdigit():
                content_length = int(content_length_str)

            # --- Scenario 1: Request has a body ---
            if content_length > 0:
                # A body exists, so Content-Type is mandatory.
                if not content_type:
                    abort(415, description={
                        "error": "Unsupported Media Type",
                        "message": "Content-Type header is required for requests with a body."
                    })
                
                allowed_types = [
                    'application/json',
                    'multipart/form-data',
                    'application/x-www-form-urlencoded'
                ]
                    
                # The Content-Type must be one of the allowed types.
                if not any(allowed in content_type for allowed in allowed_types):
                    logger.warning(f"Invalid content type for non-empty body: {content_type}")
                    abort(415, description={
                        "error": "Unsupported Media Type",
                        "message": f"Content-Type '{content_type}' is not allowed.",
                        "allowed_types": allowed_types
                    })

            # --- Scenario 2: Request has NO body ---
            else: # This means content_length is 0.
                # No body, so a Content-Type header is invalid.
                if content_type:
                    logger.warning(f"Extraneous Content-Type '{content_type}' for empty body.")
                    abort(400, description={
                        "error": "Bad Request",
                        "message": "Content-Type header cannot be present for requests with an empty body."
                    })
    
    def _add_security_headers(self, response):
        """Add security headers to response"""
        headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
        }
        
        for header, value in headers.items():
            response.headers[header] = value
    
    def _add_cors_headers(self, 
                         response, 
                         origins: Optional[List[str]] = None,
                         methods: Optional[List[str]] = None,
                         headers: Optional[List[str]] = None,
                         credentials: bool = True):
        """Add CORS headers to response"""
        
        # Get origin from request
        origin = request.headers.get('Origin')
        
        # Use configured origins if not specified
        if not origins:
            origins = current_app.config.get('CORS_ORIGINS', ['*'])
        
        # Check if origin is allowed
        if origin and (origins == ['*'] or origin in origins):
            response.headers['Access-Control-Allow-Origin'] = origin
        elif not origin and origins == ['*']:
            response.headers['Access-Control-Allow-Origin'] = '*'
        
        # Set allowed methods
        if not methods:
            methods = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH']
        response.headers['Access-Control-Allow-Methods'] = ', '.join(methods)
        
        # Set allowed headers
        if not headers:
            headers = [
                'Content-Type',
                'Authorization',
                'X-Requested-With',
                'Accept',
                'Origin'
            ]
        response.headers['Access-Control-Allow-Headers'] = ', '.join(headers)
        
        # Set credentials
        if credentials:
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        
        # Set max age for preflight cache
        response.headers['Access-Control-Max-Age'] = '86400'  # 24 hours

class RequestSizeLimiter:
    """Request size limiting middleware"""
    
    def __init__(self, max_size: int = 100 * 1024 * 1024):  # 100MB default
        self.max_size = max_size
    
    def limit_request_size(self, max_size: Optional[int] = None):
        """Decorator to limit request size for specific endpoints"""
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                size_limit = max_size or self.max_size
                
                content_length = request.headers.get('Content-Length')
                if content_length:
                    try:
                        size = int(content_length)
                        if size > size_limit:
                            logger.warning(f"Request size {size} exceeds limit {size_limit}")
                            return jsonify({
                                "error": "Request too large",
                                "message": f"Request size exceeds limit of {size_limit} bytes",
                                "max_size": size_limit
                            }), 413
                    except ValueError:
                        pass
                
                return await f(*args, **kwargs)
                
            return decorated_function
        return decorator

# Security configuration presets
class SecurityConfig:
    """Predefined security configurations"""
    
    # Production security headers
    PRODUCTION_CSP = {
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        'style-src': "'self' 'unsafe-inline' https://fonts.googleapis.com",
        'font-src': "'self' https://fonts.gstatic.com",
        'img-src': "'self' data: https:",
        'connect-src': "'self' https://api.partyscene.app",
        'frame-ancestors': "'none'",
        'base-uri': "'self'",
        'form-action': "'self'"
    }
    
    # Development CORS settings
    DEV_CORS_ORIGINS = [
        'http://localhost:3000',
        'http://localhost:8080',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:8080'
    ]
    
    # Production CORS settings
    PROD_CORS_ORIGINS = [
        'https://partyscene.app',
        'https://www.partyscene.app',
        'https://api.partyscene.app'
    ]
    
    # File upload size limits
    IMAGE_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB
    VIDEO_SIZE_LIMIT = 100 * 1024 * 1024  # 100MB
    DOCUMENT_SIZE_LIMIT = 5 * 1024 * 1024  # 5MB
