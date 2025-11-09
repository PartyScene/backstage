"""
Standard API response formatting utilities.

All API responses should follow this format:
- message: Human-readable message (required)
- status: HTTP status phrase (required) 
- data: Response payload (optional)
"""
from http import HTTPStatus
from typing import Any, Optional
from quart import jsonify


def api_response(
    message: str,
    status_code: HTTPStatus,
    data: Optional[dict[str, Any]] = None
) -> tuple:
    """
    Create a standardized API response.
    
    Args:
        message: Human-readable message describing the result
        status_code: HTTP status code (use HTTPStatus enum)
        data: Optional dictionary containing response payload
        
    Returns:
        Tuple of (jsonify response, status_code)
        
    Examples:
        # Error response
        return api_response(
            "Invalid event ID format",
            HTTPStatus.BAD_REQUEST
        )
        
        # Success with data
        return api_response(
            "Stream created successfully",
            HTTPStatus.CREATED,
            data={"stream_id": "abc123"}
        )
    """
    response = {
        "message": message,
        "status": status_code.phrase
    }
    
    if data is not None:
        response["data"] = data
    
    return jsonify(**response), status_code


def api_error(message: str, status_code: HTTPStatus) -> tuple:
    """
    Create a standardized error response.
    Alias for api_response without data.
    """
    return api_response(message, status_code)


def api_success(message: str, data: Optional[dict[str, Any]] = None) -> tuple:
    """
    Create a standardized success response (200 OK).
    """
    return api_response(message, HTTPStatus.OK, data)
