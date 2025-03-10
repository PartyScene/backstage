from .client import MediaClient
from surrealdb import AsyncSurreal, RecordID
import json
import os
from typing import Optional, Any, Dict


def create_media_client(media_service_url: str) -> MediaClient:
    """Factory function to create a MediaClient instance"""
    return MediaClient(media_service_url)


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
