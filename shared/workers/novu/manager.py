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
    EventRSVPAttendeeNotification,
    EventRSVPHostNotification,
    HostWelcomeNotification,
    EventCancelledNotification,
    EventUpdatedNotification,
    KYCDecisionNotification,
    GuestlistDecisionNotification,
    GuestlistRSVPNotification,
    PayoutProcessedNotification,
    TicketRefundNotification,
    AccountDeletionWarningNotification,
    TicketCheckinHostNotification,
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
        event_name: str = "",
        workflow_id: str = None,
    ):
        notification = EventInvitationNotification(
            event_id=event_id,
            event_name=event_name,
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
        event_name: str = "",
        host_name: str = "",
        workflow_id: str = None,
    ):
        notification = LivestreamNotification(
            event_id=event_id,
            event_name=event_name,
            host_name=host_name,
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

    async def send_event_rsvp_attendee(
        self,
        subscriber_id: str,
        event_name: str,
        event_id: str,
    ):
        """Confirm to the attendee that they've RSVP'd."""
        notification = EventRSVPAttendeeNotification(
            subscriber_id=subscriber_id,
            event_name=event_name,
            event_id=event_id,
        )
        return await self._dispatch(notification)

    async def send_event_rsvp_host(
        self,
        host_subscriber_id: str,
        attendee_name: str,
        event_name: str,
        event_id: str,
    ):
        """Notify the host that someone RSVP'd to their event."""
        notification = EventRSVPHostNotification(
            host_subscriber_id=host_subscriber_id,
            attendee_name=attendee_name,
            event_name=event_name,
            event_id=event_id,
        )
        return await self._dispatch(notification)

    async def send_host_welcome(
        self,
        subscriber_id: str,
        first_name: str,
    ):
        """Welcome email for new hosts."""
        notification = HostWelcomeNotification(
            subscriber_id=subscriber_id,
            first_name=first_name,
        )
        return await self._dispatch(notification)

    async def send_event_cancelled(
        self,
        attendee_ids: List[str],
        event_name: str,
        event_id: str,
    ):
        """Notify all attendees that an event has been cancelled."""
        if not attendee_ids:
            return None
        notification = EventCancelledNotification(
            attendee_ids=attendee_ids,
            event_name=event_name,
            event_id=event_id,
        )
        return await self._dispatch(notification)

    async def send_event_updated(
        self,
        attendee_ids: List[str],
        event_name: str,
        event_id: str,
        changed_fields: List[str],
    ):
        """Notify all attendees that a material event detail has changed."""
        if not attendee_ids:
            return None
        notification = EventUpdatedNotification(
            attendee_ids=attendee_ids,
            event_name=event_name,
            event_id=event_id,
            changed_fields=changed_fields,
        )
        return await self._dispatch(notification)

    async def send_kyc_decision(
        self,
        subscriber_id: str,
        approved: bool,
    ):
        """Notify a user of their Veriff KYC approval or rejection."""
        notification = KYCDecisionNotification(
            subscriber_id=subscriber_id,
            approved=approved,
        )
        return await self._dispatch(notification)

    async def send_guestlist_decision(
        self,
        guest_subscriber_id: str,
        event_name: str,
        event_id: str,
        status: str,
    ):
        """Notify a guest of the host's decision on their guestlist application."""
        notification = GuestlistDecisionNotification(
            guest_subscriber_id=guest_subscriber_id,
            event_name=event_name,
            event_id=event_id,
            status=status,
        )
        return await self._dispatch(notification)

    async def send_guestlist_rsvp(
        self,
        host_subscriber_id: str,
        guest_name: str,
        event_name: str,
        event_id: str,
        status: str,
    ):
        """Notify the host that an invited guest has responded to their invitation."""
        notification = GuestlistRSVPNotification(
            host_subscriber_id=host_subscriber_id,
            guest_name=guest_name,
            event_name=event_name,
            event_id=event_id,
            status=status,
        )
        return await self._dispatch(notification)

    async def send_payout_processed(
        self,
        host_subscriber_id: str,
        amount: float,
        currency: str,
        arrival_date: str,
    ):
        """Notify a host that a Stripe payout has been dispatched."""
        notification = PayoutProcessedNotification(
            host_subscriber_id=host_subscriber_id,
            amount=amount,
            currency=currency,
            arrival_date=arrival_date,
        )
        return await self._dispatch(notification)

    async def send_ticket_refund(
        self,
        subscriber_id: str,
        event_name: str,
        event_id: str,
        amount: float,
        currency: str,
    ):
        """Notify a buyer that a refund has been issued for their ticket."""
        notification = TicketRefundNotification(
            subscriber_id=subscriber_id,
            event_name=event_name,
            event_id=event_id,
            amount=amount,
            currency=currency,
        )
        return await self._dispatch(notification)

    async def send_account_deletion_warning(
        self,
        subscriber_id: str,
        deletion_date: str,
    ):
        """Warn a user that their account will be permanently deleted soon."""
        notification = AccountDeletionWarningNotification(
            subscriber_id=subscriber_id,
            deletion_date=deletion_date,
        )
        return await self._dispatch(notification)

    async def send_ticket_checkin_host(
        self,
        host_subscriber_id: str,
        event_name: str,
        event_id: str,
        attendee_name: str,
        ticket_number: str,
    ):
        """Push-notify the host the moment a ticket is freshly checked in."""
        notification = TicketCheckinHostNotification(
            host_subscriber_id=host_subscriber_id,
            event_name=event_name,
            event_id=event_id,
            attendee_name=attendee_name,
            ticket_number=ticket_number,
        )
        return await self._dispatch(notification)
