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
        filenames = [obj["filename"]]
        data = await generate_signed_url(filenames)
        flattened_obj = {**obj, 'signed_url': data.get(obj['filename'])}
    
    elif isinstance(obj, str):
        filenames = [obj]
        data = await generate_signed_url(filenames)
        flattened_obj = data.get(obj)
    
    else: return obj
    
    return flattened_obj