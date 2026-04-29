from surrealdb import RecordID
from surrealdb.data.types import geometry
import orjson as json
import os
from typing import Optional, Any, Dict
import rusty_req

from .db import report_resource

MEDIA_MICROSERVICE_URL = os.getenv("MEDIA_MICROSERVICE_URL", "")


def parse_rusty_req_response(response: dict, expected_status: tuple = (200,)) -> dict:
    """
    Parse and validate rusty_req response with proper error handling.
    
    Handles the fact that rusty_req returns all fields as JSON strings:
    - exception: JSON string (e.g., "{}" for no error)
    - http_status: String representation of int
    - response: JSON string containing another JSON object with 'content'
    
    Args:
        response: Response dict from rusty_req.fetch_single()
        expected_status: Tuple of acceptable HTTP status codes
        
    Returns:
        dict: Parsed content from response
        
    Raises:
        RuntimeError: If request failed or returned unexpected status
    """
    # Check for request-level errors
    exception = response.get("exception")
    if exception and exception != "{}":  # Ignore empty dict string
        if isinstance(exception, str):
            raise RuntimeError(f"Request failed: {exception}")
        elif isinstance(exception, dict) and exception.get("type"):
            raise RuntimeError(f"Request failed: {exception.get('message')}")
    
    # Check HTTP status
    http_status = response.get("http_status", "0")
    http_status = int(http_status) if isinstance(http_status, str) else http_status
    if http_status not in expected_status:
        raise RuntimeError(f"Unexpected HTTP status: {http_status}")
    
    # Parse response body
    try:
        response_data = response.get("response", "{}")
        if isinstance(response_data, str):
            response_data = json.loads(response_data)
        content = response_data.get("content", "")
        return json.loads(content) if content else {}
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Malformed response: {exc}") from exc


def get_client_ip(request) -> str:
    """
    Extract client IP address with proxy awareness.
    
    In production deployments behind load balancers, reverse proxies, or CDNs,
    the X-Forwarded-For header contains the original client IP.
    The first IP in the chain is the real client; subsequent IPs are proxies.
    
    Args:
        request: Quart/Flask request object
        
    Returns:
        str: Client IP address, or 'unknown' if unavailable
    """
    if forwarded := request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For format: "client, proxy1, proxy2"
        # First IP is the original client
        return forwarded.split(',')[0].strip()
    
    # Fallback to direct connection IP (reliable in dev, unreliable in prod)
    return request.remote_addr or 'unknown'


def record_id_to_json(obj: Any) -> Any:
    """
    Recursively convert RecordID to string and handle nested dictionaries and lists
    """
    if isinstance(obj, RecordID):
        return obj.id
    elif isinstance(obj, dict):
        return {k: record_id_to_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [record_id_to_json(item) for item in obj]
    return obj


from typing import Sequence, Dict


async def generate_signed_url(filenames: Sequence[str]) -> Dict[str, str]:
    url = f"{MEDIA_MICROSERVICE_URL}/media/sign"
    headers = {"Content-Type": "application/json"}
    payload = {"filenames": list(filenames)}
    
    response = await rusty_req.fetch_single(
        url=url,
        method="POST",
        headers=headers,
        params=payload,
        timeout=2,
    )
    
    data = parse_rusty_req_response(response, expected_status=(200,))
    return data["data"]  # type: ignore[index]


async def recursively_sign_object_media(obj: Any) -> Any:
    # Recursively sign media objects in the event data
    # Event data will either be a list of events, or an object with a "live" or "upcoming" key with value as a list of events
    if isinstance(obj, list):
        # Handle list of events
        return [await recursively_sign_object_media(item) for item in obj]
    elif isinstance(obj, dict):
        # Handle single event object
        if "event" in obj and "media" in obj["event"]:
            obj["event"]["media"] = await sign_media_object(obj["event"]["media"])
        # Handle post media if present
        if "post" in obj and "media" in obj["post"]:
            obj["post"]["media"] = await sign_media_object(obj["post"]["media"])
        if "media" in obj:
            media_val = obj["media"]
            if isinstance(media_val, list) and media_val and isinstance(media_val[0].get("media"), dict):
                # Gallery edge list — filename is nested under item["media"]
                for item in media_val:
                    if isinstance(item.get("media"), dict):
                        item["media"] = await sign_media_object(item["media"])
            else:
                obj["media"] = await sign_media_object(media_val)

        if "filename" in obj and obj['filename'] != "":
            obj["avatar"] = await sign_media_object(obj["filename"])

        if "user" in obj and isinstance(obj["user"], dict):
            user = obj["user"]
            if "cover_image" in user and isinstance(user["cover_image"], dict):
                user["cover_image"] = await sign_media_object(user["cover_image"])

        # Recursively handle nested dictionaries
        return obj
    return obj


# async def recursively_sign_object_media(obj: Any) -> Any:
#     # Recursively sign media objects in the event data
#     # Event data will either be a list of events, or an object with a "live" or "upcoming" key with value as a list of events
#     if isinstance(obj, list):
#         # If the object is a list, it should be a list of objects with an event key
#         # We will sign each media object in the list
#         result = [await sign_media_object(item['event']) for item in obj] # sign each event item in the list
#         # If the item is a dictionary, we check if it has an "event" key
#         # and if it has a "media" key, we sign the media object
#         # Check if any of the items in the list have a media object
#         if any("media" in item["event"] for item in result):
#             for item in result:
#                 if "media" in item["event"]:
#                     item["event"]["media"] = await sign_media_object(item["event"]["media"])
#         return result
#     elif isinstance(obj, dict):
#         result = {k: await recursively_sign_object_media(v['media']) for k, v in obj.items()}
#         # Check if any of the values in the dictionary have a media object
#         # This assumes that the media object is nested under an "event" key
#         # and that the media object is a list of media objects
#         # if any("media" in v["event"] for v in result.values()):
#         #     for k, v in result.items():
#         #         if "media" in v["event"]:
#         #             v["event"]["media"] = await sign_media_object(v["event"]["media"])

#         # If the media object is not under an "event" key, we can still sign it
#         for k, v in result.items():
#             if isinstance(v, list):
#                 result[k] = [await sign_media_object(item) for item in v]
#             elif isinstance(v, dict) and "filename" in v:
#                 result[k] = await sign_media_object(v)
#         return result
#     elif isinstance(obj, str):
#         # If the object is a string, it might be a filename, so we sign it directly
#         return await sign_media_object(obj)
#     else:
#         return obj

def coordinates_to_geometry_point(coordinates: list[float]) -> geometry.GeometryPoint:
    coordinates = tuple(float(x) for x in coordinates)

    try:
        return geometry.GeometryPoint.parse_coordinates(coordinates)
    except ValueError as exc:
        raise ValueError("Invalid coordinates") from exc

async def sign_media_object(obj: Any) -> Any:
    """
    Recursively request for signed urls for each filename in the object
    Object will either be a list of media objects or the media object itself
    """
    if isinstance(obj, list):
        # Collect both filename and thumbnail paths in one batch signing call
        # so video media items get both their primary URL and their preview URL
        # signed without an extra round-trip.
        all_paths = []
        for item in obj:
            if "filename" in item and item["filename"]:
                all_paths.append(item["filename"])
            if "thumbnail" in item and item["thumbnail"]:
                all_paths.append(item["thumbnail"])
        if not all_paths:
            return obj
        data = await generate_signed_url(tuple(all_paths))
        flattened_obj = [
            {
                **item,
                "signed_url":           data.get(item.get("filename")),
                "thumbnail_signed_url": data.get(item["thumbnail"]) if item.get("thumbnail") else None,
            }
            for item in obj
        ]

    elif isinstance(obj, dict):
        if "filename" not in obj:
            return obj
        paths = [obj["filename"]]
        if obj.get("thumbnail"):
            paths.append(obj["thumbnail"])
        data = await generate_signed_url(tuple(paths))
        flattened_obj = {
            **obj,
            "signed_url":           data.get(obj["filename"]),
            "thumbnail_signed_url": data.get(obj["thumbnail"]) if obj.get("thumbnail") else None,
        }

    elif isinstance(obj, str):
        filenames = [obj]
        data = await generate_signed_url(filenames)
        flattened_obj = data.get(obj)

    else:
        return obj

    return flattened_obj


# Import submodules after all functions are defined to avoid circular imports
from .crypto import AsyncEnvelopeCipherService, EnvelopeCipher
from .signer import generate_cdn_signed_url
from .veriff import VeriffClient
from .apple_auth import AppleAuthClient, verify_apple_token
from .response import api_response, api_error, api_success

__all__ = [
    "AsyncEnvelopeCipherService",
    "EnvelopeCipher",
    "generate_cdn_signed_url",
    "VeriffClient",
    "AppleAuthClient",
    "verify_apple_token",
    "parse_rusty_req_response",
    "get_client_ip",
    "record_id_to_json",
    "generate_signed_url",
    "recursively_sign_object_media",
    "api_response",
    "api_error",
    "api_success",
    "report_resource",
]