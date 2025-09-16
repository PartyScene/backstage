import re
import logging
from typing import Dict, Any, Optional, List
from functools import wraps

import bleach
from quart import request, jsonify
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)

class ValidationMiddleware:
    """Production-ready request validation and sanitization middleware"""
    
    # Common validation patterns
    PATTERNS = {
        'username': re.compile(r'^[a-zA-Z0-9_]{3,30}$'),
        'password': re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'),
        'phone': re.compile(r'^\+?1?\d{9,15}$'),
        'uuid': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
        'slug': re.compile(r'^[a-z0-9-]+$'),
        'hex_color': re.compile(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$'),
    }
    
    # File upload restrictions
    ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'}
    ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/quicktime', 'video/avi', 'video/mov'}
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
    
    def validate_json(self, schema: Dict[str, Any], required: List[str] = None):
        """
        Validate JSON request body against schema
        
        Args:
            schema: Dictionary defining field validation rules
            required: List of required field names
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                try:
                    data = await request.get_json()
                    if not data:
                        return jsonify({
                            "error": "Invalid JSON",
                            "message": "Request body must be valid JSON"
                        }), 400
                    
                    # Validate required fields
                    if required:
                        missing_fields = [field for field in required if field not in data]
                        if missing_fields:
                            return jsonify({
                                "error": "Missing required fields",
                                "missing_fields": missing_fields
                            }), 400
                    
                    # Validate and sanitize fields
                    validated_data = {}
                    errors = {}
                    
                    for field, rules in schema.items():
                        if field in data:
                            value = data[field]
                            validated_value, error = await self._validate_field(field, value, rules)
                            
                            if error:
                                errors[field] = error
                            else:
                                validated_data[field] = validated_value
                        elif rules.get('required', False):
                            errors[field] = "This field is required"
                    
                    if errors:
                        return jsonify({
                            "error": "Validation failed",
                            "field_errors": errors
                        }), 400
                    
                    # Replace request data with validated data
                    request.validated_json = validated_data
                    
                    return await f(*args, **kwargs)
                    
                except Exception as e:
                    logger.error(f"Validation error: {e}")
                    return jsonify({
                        "error": "Validation error",
                        "message": str(e)
                    }), 400
                    
            return decorated_function
        return decorator
    
    def validate_file_upload(self, 
                           allowed_types: Optional[set] = None,
                           max_size: Optional[int] = None,
                           required: bool = True):
        """
        Validate file uploads
        
        Args:
            allowed_types: Set of allowed MIME types
            max_size: Maximum file size in bytes
            required: Whether file is required
        """
        def decorator(f):
            @wraps(f)
            async def decorated_function(*args, **kwargs):
                files = await request.files
                
                if required and not files:
                    return jsonify({
                        "error": "File required",
                        "message": "At least one file must be uploaded"
                    }), 400
                
                for field_name, file in files.items():
                    if not file.filename:
                        continue
                        
                    # Check file type
                    if allowed_types and file.content_type not in allowed_types:
                        return jsonify({
                            "error": "Invalid file type",
                            "message": f"File type {file.content_type} not allowed",
                            "allowed_types": list(allowed_types)
                        }), 400
                    
                    # Check file size
                    file_size = len(await file.read())
                    await file.seek(0)  # Reset file pointer
                    
                    max_allowed = max_size or self.MAX_FILE_SIZE
                    if file_size > max_allowed:
                        return jsonify({
                            "error": "File too large",
                            "message": f"File size {file_size} exceeds limit {max_allowed}",
                            "max_size": max_allowed
                        }), 400
                
                return await f(*args, **kwargs)
                
            return decorated_function
        return decorator
    
    async def _validate_field(self, field_name: str, value: Any, rules: Dict[str, Any]) -> tuple[Any, Optional[str]]:
        """Validate a single field against rules"""
        
        # Type validation
        expected_type = rules.get('type')
        if expected_type and not isinstance(value, expected_type):
            return None, f"Expected {expected_type.__name__}, got {type(value).__name__}"
        
        # String validations
        if isinstance(value, str):
            # Length validation
            min_length = rules.get('min_length')
            max_length = rules.get('max_length')
            
            if min_length and len(value) < min_length:
                return None, f"Minimum length is {min_length}"
            
            if max_length and len(value) > max_length:
                return None, f"Maximum length is {max_length}"
            
            # Pattern validation
            pattern_name = rules.get('pattern')
            if pattern_name and pattern_name in self.PATTERNS:
                if not self.PATTERNS[pattern_name].match(value):
                    return None, f"Invalid {pattern_name} format"
            
            # Custom regex
            custom_pattern = rules.get('regex')
            if custom_pattern and not re.match(custom_pattern, value):
                return None, "Invalid format"
            
            # Email validation
            if rules.get('email', False):
                try:
                    validated_email = validate_email(value)
                    value = validated_email.email
                except EmailNotValidError as e:
                    return None, f"Invalid email: {str(e)}"
            
            # Sanitization
            if rules.get('sanitize', True):
                value = self._sanitize_string(value, rules.get('allow_html', False))
        
        # Numeric validations
        if isinstance(value, (int, float)):
            min_val = rules.get('min')
            max_val = rules.get('max')
            
            if min_val is not None and value < min_val:
                return None, f"Minimum value is {min_val}"
            
            if max_val is not None and value > max_val:
                return None, f"Maximum value is {max_val}"
        
        # List validations
        if isinstance(value, list):
            min_items = rules.get('min_items')
            max_items = rules.get('max_items')
            
            if min_items and len(value) < min_items:
                return None, f"Minimum {min_items} items required"
            
            if max_items and len(value) > max_items:
                return None, f"Maximum {max_items} items allowed"
            
            # Validate list items
            item_rules = rules.get('item_rules')
            if item_rules:
                validated_items = []
                for i, item in enumerate(value):
                    validated_item, error = await self._validate_field(f"{field_name}[{i}]", item, item_rules)
                    if error:
                        return None, f"Item {i}: {error}"
                    validated_items.append(validated_item)
                value = validated_items
        
        return value, None
    
    def _sanitize_string(self, value: str, allow_html: bool = False) -> str:
        """Sanitize string input"""
        if not allow_html:
            # Strip all HTML tags
            value = bleach.clean(value, tags=[], strip=True)
        else:
            # Allow only safe HTML tags
            allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'p', 'br']
            value = bleach.clean(value, tags=allowed_tags, strip=True)
        
        # Remove null bytes and control characters
        value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
        
        # Trim whitespace
        value = value.strip()
        
        return value

# Common validation schemas
class ValidationSchemas:
    """Predefined validation schemas for common use cases"""
    
    USER_REGISTRATION = {
        'email': {
            'type': str,
            'required': True,
            'email': True,
            'max_length': 255
        },
        'username': {
            'type': str,
            'required': True,
            'pattern': 'username',
            'min_length': 3,
            'max_length': 30
        },
        'password': {
            'type': str,
            'required': True,
            'pattern': 'password',
            'min_length': 8,
            'max_length': 128
        },
        'first_name': {
            'type': str,
            'required': True,
            'min_length': 1,
            'max_length': 50
        },
        'last_name': {
            'type': str,
            'required': True,
            'min_length': 1,
            'max_length': 50
        }
    }
    
    EVENT_CREATION = {
        'title': {
            'type': str,
            'required': True,
            'min_length': 3,
            'max_length': 200
        },
        'description': {
            'type': str,
            'required': True,
            'min_length': 10,
            'max_length': 2000
        },
        'price': {
            'type': (int, float),
            'required': True,
            'min': 0,
            'max': 10000
        },
        'categories': {
            'type': list,
            'required': False,
            'max_items': 5,
            'item_rules': {
                'type': str,
                'max_length': 50
            }
        }
    }
    
    POST_CREATION = {
        'content': {
            'type': str,
            'required': True,
            'min_length': 1,
            'max_length': 2000,
            'allow_html': False
        }
    }
