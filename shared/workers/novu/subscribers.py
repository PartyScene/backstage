"""
Subscriber management — separated from notification dispatch.

Thought process
───────────────
The original NotificationManager mixed subscriber CRUD with notification
sending.  Separating them follows the Single Responsibility Principle:

  • SubscriberService owns the Novu subscriber lifecycle (create, patch,
    search, delete).
  • NotificationManager owns *dispatching* notifications.

This also makes each piece independently testable and mockable.
"""

import logging
import uuid

from typing import Dict, Optional, Union

from novu_py import Novu, SubscriberResponseDto

logger = logging.getLogger(__name__)


class SubscriberService:
    """Handles all Novu subscriber lifecycle operations."""

    def __init__(self, novu_client: Novu):
        self._client = novu_client

    async def get_by_email(self, email: str) -> Union[Dict, SubscriberResponseDto, None]:
        """
        Search for a subscriber by email.

        Returns the first match or ``None``.
        """
        try:
            result = await self._client.subscribers.search_async(
                request={"email": email}
            )
            if result and result.result.data:
                return result.result.data[0]
            return None
        except Exception as e:
            logger.error("Subscriber search error: %s", e)
            return None

    async def create_or_update(
        self,
        email: str,
        user_id: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ):
        """
        Upsert a subscriber in Novu.

        If a subscriber with the given email already exists, patch it;
        otherwise create a new one.  This is idempotent by design — safe
        to call from multiple services without coordination.
        """
        try:
            subscriber_data = {
                "subscriber_id": user_id or str(uuid.uuid4())[:8],
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
            }
            if exists := await self._client.subscribers.search_async(
                request={"email": email}
            ):
                if len(exists.result.data) >= 1:
                    logger.warning("Found a Novu Subscriber with %s", email)
                    logger.warning(exists.result)
                    return await self._client.subscribers.patch_async(
                        subscriber_id=exists.result.data[0].subscriber_id,
                        patch_subscriber_request_dto=subscriber_data,
                    )
            return await self._client.subscribers.create_async(
                create_subscriber_request_dto=subscriber_data
            )
        except Exception as e:
            logger.error("Subscriber creation error: %s", e)
            raise

    async def delete(self, user_id: str) -> bool:
        """
        Remove a subscriber from Novu.

        Returns ``True`` on success, ``False`` on failure (logged, not raised).
        """
        try:
            await self._client.subscribers.delete_async(subscriber_id=user_id)
            logger.info("Deleted Novu subscriber: %s", user_id)
            return True
        except Exception as e:
            logger.error("Subscriber deletion error: %s", e)
            return False
