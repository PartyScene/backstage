import os
import novu_py
import logging
import httpx

from datetime import datetime
from novu_py import Novu, TriggerEventRequestDto, To
from typing import Tuple
import uuid
from typing import Dict, List, Union, Optional

logger = logging.getLogger(__name__)

import ipinfo


class NotificationManager:
    def __init__(self):
        """
        Initialize Novu client with secret key from environment
        """
        self.novu_client = Novu(secret_key=os.getenv("NOVU_SECRET_KEY", ""))
        self.handler = ipinfo.getHandlerAsync(os.getenv("IPINFO_TOKEN", ""))

    async def get_ip_location(self, ip_address: str) -> Tuple[str, str]:
        """Get the Location from an IP Address

        Args:
            ip_address (str): _description_
        """
        try:
            details = await self.handler.getDetails(ip_address)
            return details.city, details.country
        except:
            return "", ""

        # try:
        #     async with httpx.AsyncClient() as client:
        #         r = await client.get(f"https://ipapi.co/{ip_address}/json/")
        #         r.raise_for_status()
        #         json_data = r.json()
        #         return json_data["city"], json_data["country"]

        # except Exception as e:
        #     logger.error(f"Failed to get Location from IP {e}")
        #     return "", ""

    async def create_subscriber(
        self,
        email: str,
        user_id: str = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ):
        """
        Create or update a subscriber in Novu

        Args:
            user_id (str): Unique identifier for the subscriber
            email (str): Email address of the subscriber
            first_name (Optional[str]): First name of the subscriber
            last_name (Optional[str]): Last name of the subscriber

        Returns:
            Dict: Subscriber creation/update response
        """
        try:
            subscriber_data = {
                "subscriber_id": user_id or str(uuid.uuid4())[:8],
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
            }
            if exists := await self.novu_client.subscribers.search_async(
                request={"email": email}
            ):
                if len(exists.result.data) >= 1:
                    logger.info("Found a Novu Subscriber with %s " % email)
                    logger.info(exists.result)
                    return await self.novu_client.subscribers.patch_async(
                        subscriber_id=exists.result.data[0].subscriber_id,
                        patch_subscriber_request_dto=subscriber_data,
                    )
            return await self.novu_client.subscribers.create_async(
                create_subscriber_request_dto=subscriber_data
            )
        except Exception as e:
            logger.error(f"Subscriber creation error: {e}")
            raise

    async def send_otp_notification(
        self,
        user_id: str,
        ip_address: str,
        otp: str,
        workflow_id: str = "email-verification-flow",
    ):
        """
        Send OTP notification to a user

        Args:
            user_id (str): Subscriber ID to send OTP
            otp (str): One-time password
            workflow_id (str): Novu workflow identifier for OTP

        Returns:
            Dict: Notification trigger response
        """
        try:
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to={"subscriber_id": user_id},
                    payload={
                        "data": {
                            "app_name": "Scenes",
                            "requested_by": ip_address,
                            "requested_at": ", ".join(
                                await self.get_ip_location(ip_address)
                            ),
                            "otp_code": otp,
                        }
                    },
                )
            )
        except Exception as e:
            logger.error(f"OTP notification error: {e}")
            raise

    async def recent_login_notification(
        self,
        user_id: str,
        ip_address: str,
        timestamp: str = None,
        workflow_id: str = "recent-login",
    ):
        """
        Send recent login notification to a user

        Args:
            user_id (str): Subscriber ID to send notification
            workflow_id (str): Novu workflow identifier for Recent Logins
            payload (Dict): Additional payload data (ip_address, timestamp)

        Returns:
            Dict: Notification trigger response
        """
        try:
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to={"subscriber_id": user_id},
                    payload={
                        "ip_address": ip_address,
                        "timestamp": timestamp or datetime.now().isoformat(),
                    },
                )
            )
        except Exception as e:
            logger.error(f"Recent Login notification error: {e}")
            raise

    async def send_friend_request_notification(
        self, sender: str, recipient_id: str, recipient_name: str, workflow_id: str = "friend-request"
    ):
        """
        Send friend request notification

        Args:
            sender (str): Name of the sender
            recipient_id (str): User ID of the recipient
            recipient_name (str): Name of the recipient
            workflow_id (str): Novu workflow identifier for friend requests

        Returns:
            Dict: Notification trigger response
        """
        try:
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to={"subscriber_id": recipient_id},
                    payload={"sender": recipient_name},
                )
            )
        except Exception as e:
            logger.error(f"Friend request notification error: {e}")
            raise

    async def send_event_invitation(
        self,
        event_id: str,
        invitee_ids: List[str],
        workflow_id: str = "event-invitation",
    ):
        """
        Send event invitation notifications to multiple users

        Args:
            event_id (str): Unique event identifier
            invitee_ids (List[str]): List of user IDs to invite
            workflow_id (str): Novu workflow identifier for event invitations

        Returns:
            List[Dict]: Notification trigger responses
        """
        try:

            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    # to={
                    #     'subscriber_id': invitee_id
                    # },
                    to=invitee_ids,
                    payload={"event_id": event_id},
                )
            )

        except Exception as e:
            logger.info(f"Event invitation notification error: {e}")
            raise

    async def send_livestream_notification(
        self,
        event_id: str,
        subscribers: List[str],
        workflow_id: str = "livestream-notification",
    ):
        """
        Send livestream notifications to event subscribers

        Args:
            event_id (str): Unique event identifier
            subscribers (List[str]): List of subscriber IDs
            workflow_id (str): Novu workflow identifier for livestream notifications

        Returns:
            List[Dict]: Notification trigger responses
        """
        try:
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to=subscribers,
                    payload={"event_id": event_id},
                )
            )
        except Exception as e:
            logger.info(f"Livestream notification error: {e}")
            raise

    def send_post_interaction_notification(
        self,
        post_id: str,
        actor_id: str,
        recipient_id: str,
        interaction_type: str,
        workflow_id: str = "post-interaction",
    ):
        """
        Send post interaction notifications

        Args:
            post_id (str): Unique post identifier
            actor_id (str): User ID who performed the interaction
            recipient_id (str): User ID receiving the notification
            interaction_type (str): Type of interaction (e.g., 'like', 'comment')
            workflow_id (str): Novu workflow identifier for post interactions

        Returns:
            Dict: Notification trigger response
        """
        try:
            return self.novu_client.trigger(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to={"subscriberId": recipient_id},
                    payload={
                        "post_id": post_id,
                        "actor_id": actor_id,
                        "interaction_type": interaction_type,
                    },
                )
            )
        except Exception as e:
            logger.info(f"Post interaction notification error: {e}")
            raise
