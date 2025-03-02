import os
import novu_py
from novu_py import Novu, TriggerEventRequestDto, To
from typing import Dict, List, Union, Optional


class NotificationManager:
    def __init__(self):
        """
        Initialize Novu client with secret key from environment
        """
        self.novu_client = Novu(secret_key=os.getenv("NOVU_SECRET_KEY", ""))

    async def create_subscriber(
        self,
        user_id: str,
        email: str,
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
                "subscriber_id": user_id,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
            }
            if exists := await self.novu_client.subscribers.search_async(
                request={"email": email}
            ):
                if len(exists.result.data) >= 1:
                    print("Found a Novu Subscriber with %s " % email)
                    print(exists.result)
                    return await self.novu_client.subscribers.update_async(
                        subscriber_id=exists.result.data[0].subscriber_id,
                        update_subscriber_request_dto={
                            "email": subscriber_data["email"]
                        },
                    )
            return await self.novu_client.subscribers.create_async(
                create_subscriber_request_dto=subscriber_data
            )
        except Exception as e:
            print(f"Subscriber creation error: {e}")
            raise

    async def send_otp_notification(
        self, user_id: str, otp: str, workflow_id: str = "one-time-password"
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
                    payload={"otp": otp},
                )
            )
        except Exception as e:
            print(f"OTP notification error: {e}")
            raise

    async def recent_login_notification(
        self, user_id: str, payload: Dict, workflow_id: str = "recent-login"
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
                    payload=payload,
                )
            )
        except Exception as e:
            print(f"Recent Login notification error: {e}")
            raise

    async def send_friend_request_notification(
        self, sender: str, recipient_id: str, workflow_id: str = "friend-request"
    ):
        """
        Send friend request notification

        Args:
            sender (str): Name of the sender
            recipient_id (str): User ID of the recipient
            workflow_id (str): Novu workflow identifier for friend requests

        Returns:
            Dict: Notification trigger response
        """
        try:
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=TriggerEventRequestDto(
                    workflow_id=workflow_id,
                    to={"subscriber_id": recipient_id},
                    payload={"sender": sender},
                )
            )
        except Exception as e:
            print(f"Friend request notification error: {e}")
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
            print(f"Event invitation notification error: {e}")
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
            print(f"Livestream notification error: {e}")
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
            print(f"Post interaction notification error: {e}")
            raise
