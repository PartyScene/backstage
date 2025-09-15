import logging
import traceback
import uuid
from typing import Dict, Any, Optional
from quart import jsonify, request, current_app
from functools import wraps
from datetime import datetime
import sys

logger = logging.getLogger(__name__)

class ErrorHandlerMiddleware:
    """Production-ready global error handling middleware"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize error handler with Quart app"""
        
        # Register error handlers for common HTTP errors
        @app.errorhandler(400)
        async def handle_bad_request(error):
            return await self._handle_error(error, 400, "Bad Request")
        
        @app.errorhandler(401)
        async def handle_unauthorized(error):
            return await self._handle_error(error, 401, "Unauthorized")
        
        @app.errorhandler(403)
        async def handle_forbidden(error):
            return await self._handle_error(error, 403, "Forbidden")
        
        @app.errorhandler(404)
        async def handle_not_found(error):
            return await self._handle_error(error, 404, "Not Found")
        
        @app.errorhandler(405)
        async def handle_method_not_allowed(error):
            return await self._handle_error(error, 405, "Method Not Allowed")
        
        @app.errorhandler(413)
        async def handle_payload_too_large(error):
            return await self._handle_error(error, 413, "Payload Too Large")
        
        @app.errorhandler(415)
        async def handle_unsupported_media_type(error):
            return await self._handle_error(error, 415, "Unsupported Media Type")
        
        @app.errorhandler(422)
        async def handle_unprocessable_entity(error):
            return await self._handle_error(error, 422, "Unprocessable Entity")
        
        @app.errorhandler(429)
        async def handle_too_many_requests(error):
            return await self._handle_error(error, 429, "Too Many Requests")
        
        @app.errorhandler(500)
        async def handle_internal_server_error(error):
            return await self._handle_error(error, 500, "Internal Server Error")
        
        @app.errorhandler(502)
        async def handle_bad_gateway(error):
            return await self._handle_error(error, 502, "Bad Gateway")
        
        @app.errorhandler(503)
        async def handle_service_unavailable(error):
            return await self._handle_error(error, 503, "Service Unavailable")
        
        @app.errorhandler(504)
        async def handle_gateway_timeout(error):
            return await self._handle_error(error, 504, "Gateway Timeout")
        
        # Handle uncaught exceptions
        @app.errorhandler(Exception)
        async def handle_exception(error):
            return await self._handle_exception(error)
    
    async def _handle_error(self, error, status_code: int, error_type: str):
        """Handle HTTP errors with structured response"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            "error_id": error_id,
            "error_type": error_type,
            "status_code": status_code,
            "message": str(error) if str(error) else error_type,
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path if request else None,
            "method": request.method if request else None
        }
        
        # Log error details
        logger.error(
            f"HTTP Error {status_code}: {error_type}",
            extra={
                "error_id": error_id,
                "status_code": status_code,
                "path": request.path if request else None,
                "method": request.method if request else None,
                "user_agent": request.headers.get('User-Agent') if request else None,
                "ip_address": request.remote_addr if request else None
            }
        )
        
        # Don't expose internal details in production
        if current_app.config.get('ENV') == 'production':
            if status_code >= 500:
                error_data["message"] = "Internal server error occurred"
        
        return jsonify(error_data), status_code
    
    async def _handle_exception(self, error):
        """Handle uncaught exceptions"""
        error_id = str(uuid.uuid4())
        
        # Get exception details
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        error_data = {
            "error_id": error_id,
            "error_type": "Internal Server Error",
            "status_code": 500,
            "message": "An unexpected error occurred",
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path if request else None,
            "method": request.method if request else None
        }
        
        # Log full exception details
        logger.error(
            f"Unhandled Exception: {exc_type.__name__}: {str(exc_value)}",
            extra={
                "error_id": error_id,
                "exception_type": exc_type.__name__ if exc_type else None,
                "exception_message": str(exc_value),
                "traceback": traceback.format_exc(),
                "path": request.path if request else None,
                "method": request.method if request else None,
                "user_agent": request.headers.get('User-Agent') if request else None,
                "ip_address": request.remote_addr if request else None
            },
            exc_info=True
        )
        
        # Include exception details in development
        if current_app.config.get('ENV') == 'development':
            error_data.update({
                "exception_type": exc_type.__name__ if exc_type else None,
                "exception_message": str(exc_value),
                "traceback": traceback.format_exc().split('\n')
            })
        
        return jsonify(error_data), 500
    
    def handle_async_errors(self):
        """Decorator to handle async errors in route handlers"""
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                try:
                    return await f(*args, **kwargs)
                except ValidationError as e:
                    return await self._handle_validation_error(e)
                except AuthenticationError as e:
                    return await self._handle_auth_error(e)
                except BusinessLogicError as e:
                    return await self._handle_business_error(e)
                except ExternalServiceError as e:
                    return await self._handle_external_service_error(e)
                except Exception as e:
                    return await self._handle_exception(e)
            
            return decorated_function
        return decorator
    
    async def _handle_validation_error(self, error):
        """Handle validation errors"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            "error_id": error_id,
            "error_type": "Validation Error",
            "status_code": 400,
            "message": str(error),
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path,
            "method": request.method
        }
        
        if hasattr(error, 'field_errors'):
            error_data["field_errors"] = error.field_errors
        
        logger.warning(f"Validation Error: {str(error)}", extra={"error_id": error_id})
        
        return jsonify(error_data), 400
    
    async def _handle_auth_error(self, error):
        """Handle authentication errors"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            "error_id": error_id,
            "error_type": "Authentication Error",
            "status_code": 401,
            "message": str(error),
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path,
            "method": request.method
        }
        
        logger.warning(f"Authentication Error: {str(error)}", extra={"error_id": error_id})
        
        return jsonify(error_data), 401
    
    async def _handle_business_error(self, error):
        """Handle business logic errors"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            "error_id": error_id,
            "error_type": "Business Logic Error",
            "status_code": 422,
            "message": str(error),
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path,
            "method": request.method
        }
        
        logger.warning(f"Business Logic Error: {str(error)}", extra={"error_id": error_id})
        
        return jsonify(error_data), 422
    
    async def _handle_external_service_error(self, error):
        """Handle external service errors"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            "error_id": error_id,
            "error_type": "External Service Error",
            "status_code": 502,
            "message": "External service temporarily unavailable",
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.path,
            "method": request.method
        }
        
        logger.error(f"External Service Error: {str(error)}", extra={"error_id": error_id})
        
        return jsonify(error_data), 502

# Custom exception classes
class ValidationError(Exception):
    """Raised when request validation fails"""
    def __init__(self, message: str, field_errors: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.field_errors = field_errors

class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass

class BusinessLogicError(Exception):
    """Raised when business logic validation fails"""
    pass

class ExternalServiceError(Exception):
    """Raised when external service calls fail"""
    pass

# Error response utilities
class ErrorResponse:
    """Utility class for creating consistent error responses"""
    
    @staticmethod
    def validation_error(message: str, field_errors: Optional[Dict[str, str]] = None):
        """Create validation error response"""
        raise ValidationError(message, field_errors)
    
    @staticmethod
    def auth_error(message: str = "Authentication required"):
        """Create authentication error response"""
        raise AuthenticationError(message)
    
    @staticmethod
    def forbidden_error(message: str = "Access forbidden"):
        """Create forbidden error response"""
        raise AuthenticationError(message)
    
    @staticmethod
    def not_found_error(message: str = "Resource not found"):
        """Create not found error response"""
        raise BusinessLogicError(message)
    
    @staticmethod
    def business_error(message: str):
        """Create business logic error response"""
        raise BusinessLogicError(message)
    
    @staticmethod
    def external_service_error(message: str = "External service unavailable"):
        """Create external service error response"""
        raise ExternalServiceError(message)
