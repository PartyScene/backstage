"""
Shared object store utilities for temp staging and final media storage.
Uses obstore (Option C) with GCS backend.
"""

import os
from datetime import timedelta
from typing import Sequence, Optional

from obstore import store
import obstore as obs


class ObstoreHandler:
    """Thin async wrapper around obstore for temp and final GCS buckets."""

    def __init__(self) -> None:
        self._temp_store = store.GCSStore(os.environ.get("TMP_GCS_BUCKET_NAME", "partyscene-temp"))
        self._final_store = store.GCSStore(os.environ.get("GCS_BUCKET_NAME", "partyscene"))

    # ---------- Temp bucket (staging) ----------
    async def put_temp_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        """Put bytes into the temp bucket (staging)."""
        attrs = {"Content-Type": content_type} if content_type else {}
        await obs.put_async(self._temp_store, key, data, attributes=attrs)

    async def get_temp_bytes(self, key: str) -> bytes:
        """Get bytes from the temp bucket."""
        result = await obs.get_async(self._temp_store, key)
        return await result.bytes_async()

    async def delete_temp(self, key: str) -> None:
        """Delete an object from the temp bucket."""
        await obs.delete_async(self._temp_store, key)

    async def exists_temp(self, key: str) -> bool:
        """Check if an object exists in the temp bucket."""
        try:
            await obs.head_async(self._temp_store, key)
            return True
        except Exception:
            return False

    # ---------- Final bucket (media) ----------
    async def put_final_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        """Put bytes into the final bucket (processed media)."""
        attrs = {"Content-Type": content_type} if content_type else {}
        await obs.put_async(self._final_store, key, data, attributes=attrs)

    async def get_final_bytes(self, key: str) -> bytes:
        """Get bytes from the final bucket."""
        result = await obs.get_async(self._final_store, key)
        return await result.bytes_async()

    async def exists_final(self, key: str) -> bool:
        """Check if an object exists in the final bucket."""
        try:
            await obs.head_async(self._final_store, key)
            return True
        except Exception:
            return False

    # ---------- Signed URLs ----------
    async def sign_temp_put_urls(self, keys: Sequence[str], ttl: timedelta = timedelta(hours=6)) -> list:
        """Generate signed PUT URLs for the temp bucket."""
        return await obs.sign_async(self._temp_store, "PUT", keys, ttl)

    async def sign_final_put_urls(self, keys: Sequence[str], ttl: timedelta = timedelta(hours=6)) -> list:
        """Generate signed PUT URLs for the final bucket."""
        return await obs.sign_async(self._final_store, "PUT", keys, ttl)

    async def sign_final_get_urls(self, keys: Sequence[str], ttl: timedelta = timedelta(hours=6)) -> list:
        """Generate signed GET URLs for the final bucket."""
        return await obs.sign_async(self._final_store, "GET", keys, ttl)


# Singleton for easy import in workers and services
_obstore_handler: Optional[ObstoreHandler] = None


def get_obstore() -> ObstoreHandler:
    """Get or create the singleton ObstoreHandler."""
    global _obstore_handler
    if _obstore_handler is None:
        _obstore_handler = ObstoreHandler()
    return _obstore_handler
