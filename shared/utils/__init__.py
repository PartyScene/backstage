from .crypto import AsyncEnvelopeCipherService, EnvelopeCipher

from surrealdb import RecordID
import orjson as json
import os
from typing import Optional, Any, Dict
import httpx

MEDIA_MICROSERVICE_URL = os.getenv("MEDIA_MICROSERVICE_URL", "")

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
    async with httpx.AsyncClient(
        base_url=MEDIA_MICROSERVICE_URL,
        headers={"Content-Type": "application/json"},
        timeout=5.0,
    ) as client:
        response = await client.post("/media/sign", json={"filenames": list(filenames)})
        response.raise_for_status()

        try:
            data = response.json()
            return data["data"]     # type: ignore[index]
        except (KeyError, ValueError) as exc:
            raise RuntimeError("Malformed response from media service") from exc
        
async def recursively_sign_event_media(obj: Any) -> Any:
    # Recursively sign media objects in the event data
    # Event data will either be a list of events, or an object with a "live" or "upcoming" key with value as a list of events
    if isinstance(obj, list):
        # Handle list of events
        return [await recursively_sign_event_media(item) for item in obj]
    elif isinstance(obj, dict):
        # Handle single event object
        if 'event' in obj and 'media' in obj['event']:
            obj['event']['media'] = await sign_media_object(obj['event']['media'])
        # Handle post media if present
        if 'post' in obj and 'media' in obj['post']:
            obj['post']['media'] = await sign_media_object(obj['post']['media'])
        if 'media' in obj:
            obj['media'] = await sign_media_object(obj['media'])
        # Recursively handle nested dictionaries
        return obj
    return obj
    
# async def recursively_sign_event_media(obj: Any) -> Any:
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
#         result = {k: await recursively_sign_event_media(v['media']) for k, v in obj.items()}
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

async def sign_media_object(obj: Any) -> Any:
    """
    Recursively request for signed urls for each filename in the object
    Object will either be a list of media objects or the media object itself
    """
    if isinstance(obj, list):
        filenames = tuple(
        item["filename"] for item in obj if "filename" in item)   
        if not filenames:
            return obj  # nothing to sign, return unchanged
        data = await generate_signed_url(filenames)
        flattened_obj = [
            {**item, 'signed_url': data.get(item['filename'])} # Use .get() with default None
            for item in obj
        ]
    
    elif isinstance(obj, dict):
        if "filename" not in obj:
            return obj
        # If the object is a dictionary, it should have a "filename" key
        filenames = [obj["filename"]]
        data = await generate_signed_url(filenames)
        flattened_obj = {**obj, 'signed_url': data.get(obj['filename'])}
    
    elif isinstance(obj, str):
        filenames = [obj]
        data = await generate_signed_url(filenames)
        flattened_obj = data.get(obj)
    
    else: return obj
    
    return flattened_obj