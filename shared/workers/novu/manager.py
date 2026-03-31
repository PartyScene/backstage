"""
NotificationManager — public facade for the notification subsystem.

Thought process
───────────────
This class is the *only* thing callers need to import.  It keeps the
exact same public method signatures as the old monolithic class so that
existing code in auth/, users/, payments/, and the event-reminder job
continues to work without any changes.

Internally it delegates to:
  • SubscriberService  — for subscriber CRUD
  • Individual notification dataclasses — for building typed payloads
  • A generic ``_dispatch()`` method — for sending via Novu

The generic ``send()`` method accepts *any* BaseNotification instance,
so new code can also use the modern pattern directly:

    notification = WelcomeNotification(subscriber_id="abc", first_name="Dylan")
    await manager.send(notification)

Error handling strategy (standardised):
  • notification.critical == True  → exception propagates to caller
  • notification.critical == False → exception is logged, None returned
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

import ipinfo
from novu_py import Novu, SubscriberResponseDto

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.subscribers import SubscriberService

# Import notifications so they self-register via __init_subclass__
from shared.workers.novu.notifications import (  # noqa: F401
    OTPNotification,
    WelcomeNotification,
    RecentLoginNotification,
    FriendRequestNotification,
    EventInvitationNotification,
    EventReminderNotification,
    LivestreamNotification,
    PostInteractionNotification,
    TicketPurchaseHostNotification,
    TicketPurchaseBuyerNotification,
    PasswordResetConfirmation,
    EventRecapNotification,
)

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Unified entry point for all notification operations.

    Backward-compatible: every method that existed on the old class still
    exists with the same signature.  New callers can use ``send()`` with
    any BaseNotification subclass.
    """

    def __init__(self):
        self.novu_client = Novu(secret_key=os.getenv("NOVU_SECRET_KEY", ""))
        self.handler = ipinfo.getHandlerAsync(os.getenv("IPINFO_TOKEN", ""))
        self._subscribers = SubscriberService(self.novu_client)

    # ──────────────────────────────────────────────────────────────────
    # Generic dispatch — the modern API
    # ──────────────────────────────────────────────────────────────────

    async def send(self, notification: BaseNotification):
        """
        Send any notification via Novu.

        Respects the ``critical`` flag on the notification class:
        critical notifications raise on failure; non-critical ones log
        and return None.
        """
        return await self._dispatch(notification)

    async def _dispatch(
        self,
        notification: BaseNotification,
        workflow_id_override: Optional[str] = None,
    ):
        """
        Internal dispatch — builds the trigger request and sends it.

        ``workflow_id_override`` exists solely for backward compatibility
        with the old API where callers could pass a custom workflow_id.
        """
        try:
            req = notification.to_trigger_request()
            if workflow_id_override:
                req.workflow_id = workflow_id_override
            return await self.novu_client.trigger_async(
                trigger_event_request_dto=req
            )
        except Exception as e:
            label = type(notification).__name__
            if notification.critical:
                logger.error("%s dispatch error: %s", label, e)
                raise
            else:
                logger.error("%s dispatch error (non-critical, swallowed): %s", label, e)
                return None

    # ──────────────────────────────────────────────────────────────────
    # IP geolocation utility
    # ──────────────────────────────────────────────────────────────────

    async def get_ip_location(self, ip_address: str) -> Tuple[str, str]:
        """Resolve an IP address to (city, country)."""
        try:
            details = await self.handler.getDetails(ip_address)
            return details.city, details.country
        except Exception:
            return "", ""

    # ──────────────────────────────────────────────────────────────────
    # Subscriber management (delegates to SubscriberService)
    # ──────────────────────────────────────────────────────────────────

    async def get_subscriber_by_email(
        self, email: str
    ) -> Union[Dict, SubscriberResponseDto, None]:
        return await self._subscribers.get_by_email(email)

    async def create_subscriber(
        self,
        email: str,
        user_id: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ):
        return await self._subscribers.create_or_update(
            email=email, user_id=user_id, first_name=first_name, last_name=last_name
        )

    async def delete_subscriber(self, user_id: str) -> bool:
        return await self._subscribers.delete(user_id)

    # ──────────────────────────────────────────────────────────────────
    # Push notification device token management
    # ──────────────────────────────────────────────────────────────────

    async def register_device_token(
        self,
        user_id: str,
        device_token: str,
        provider: str = "fcm",
    ) -> bool:
        """Register a push device token (FCM or APNs) for a user."""
        return await self._subscribers.append_device_token(
            subscriber_id=user_id,
            device_token=device_token,
            provider=provider,
        )

    async def unregister_device_tokens(
        self,
        user_id: str,
        provider: str = "fcm",
    ) -> bool:
        """Remove all push credentials for a provider on logout."""
        return await self._subscribers.remove_device_tokens(
            subscriber_id=user_id,
            provider=provider,
        )

    # ──────────────────────────────────────────────────────────────────
    # Backward-compatible convenience methods
    #
    # Each one constructs the typed notification dataclass and dispatches.
    # Existing callers don't need to change anything.
    # ──────────────────────────────────────────────────────────────────

    async def send_otp_notification(
        self,
        user_id: str,
        ip_address: str,
        otp: str,
        workflow_id: str = None,
    ):
        location = ", ".join(await self.get_ip_location(ip_address))
        notification = OTPNotification(
            subscriber_id=user_id,
            otp_code=otp,
            ip_address=ip_address,
            location=location,
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def recent_login_notification(
        self,
        user_id: str,
        ip_address: str,
        timestamp: str = None,
        workflow_id: str = None,
    ):
        notification = RecentLoginNotification(
            subscriber_id=user_id,
            ip_address=ip_address,
            timestamp=timestamp or "",
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_welcome_notification(
        self,
        user_id: str,
        first_name: str,
    ):
        """Send a welcome email after successful registration."""
        notification = WelcomeNotification(
            subscriber_id=user_id,
            first_name=first_name,
        )
        return await self._dispatch(notification)

    async def send_friend_request_notification(
        self,
        recipient_id: str,
        sender_name: str,
        workflow_id: str = None,
    ):
        notification = FriendRequestNotification(
            recipient_id=recipient_id,
            sender_name=sender_name,
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_event_invitation(
        self,
        event_id: str,
        invitee_ids: List[str] = None,
        workflow_id: str = None,
    ):
        notification = EventInvitationNotification(
            event_id=event_id,
            invitee_ids=invitee_ids or [],
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_event_reminder(
        self,
        event_id: str,
        event_name: str,
        attendee_ids: List[str] = None,
        minutes_until: int = 60,
        workflow_id: str = None,
    ):
        if not attendee_ids:
            return None
        notification = EventReminderNotification(
            event_id=event_id,
            event_name=event_name,
            attendee_ids=attendee_ids,
            minutes_until=minutes_until,
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_livestream_notification(
        self,
        event_id: str,
        subscribers: List[str] = None,
        workflow_id: str = None,
    ):
        notification = LivestreamNotification(
            event_id=event_id,
            subscriber_ids=subscribers or [],
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_post_interaction_notification(
        self,
        post_id: str,
        actor_id: str,
        recipient_id: str,
        interaction_type: str,
        workflow_id: str = None,
    ):
        """
        Now async (was sync in the old implementation — inconsistency fixed).
        """
        notification = PostInteractionNotification(
            post_id=post_id,
            actor_id=actor_id,
            recipient_id=recipient_id,
            interaction_type=interaction_type,
        )
        return await self._dispatch(notification, workflow_id_override=workflow_id)

    async def send_ticket_purchase_host_notification(
        self,
        host_subscriber_id: str,
        buyer_name: str,
        event_name: str,
        event_id: str,
        ticket_count: int,
        total_amount: float = 0.0,
        currency: str = "USD",
    ):
        """Notify the event host that someone purchased ticket(s)."""
        notification = TicketPurchaseHostNotification(
            host_subscriber_id=host_subscriber_id,
            buyer_name=buyer_name,
            event_name=event_name,
            event_id=event_id,
            ticket_count=ticket_count,
            total_amount=total_amount,
            currency=currency,
        )
        return await self._dispatch(notification)

    async def send_ticket_purchase_buyer_notification(
        self,
        buyer_subscriber_id: str,
        event_name: str,
        event_id: str,
        ticket_count: int,
        total_amount: float = 0.0,
        currency: str = "USD",
    ):
        """Push-notify the buyer that their ticket purchase is confirmed."""
        notification = TicketPurchaseBuyerNotification(
            buyer_subscriber_id=buyer_subscriber_id,
            event_name=event_name,
            event_id=event_id,
            ticket_count=ticket_count,
            total_amount=total_amount,
            currency=currency,
        )
        return await self._dispatch(notification)

    async def send_password_reset_confirmation(
        self,
        subscriber_id: str,
        email: str,
    ):
        """Notify user that their password was successfully reset."""
        notification = PasswordResetConfirmation(
            subscriber_id=subscriber_id,
            email=email,
        )
        return await self._dispatch(notification)

    async def send_event_recap(
        self,
        host_subscriber_id: str,
        event_id: str,
        event_name: str,
        **recap_data,
    ):
        """
        Send a PartyScene Wrapped recap to the event host.

        Accepts all recap fields as kwargs — the CronJob and inline
        trigger both compute these via the recap collector.
        """
        notification = EventRecapNotification(
            host_subscriber_id=host_subscriber_id,
            event_id=event_id,
            event_name=event_name,
            **recap_data,
        )
        return await self._dispatch(notification)
