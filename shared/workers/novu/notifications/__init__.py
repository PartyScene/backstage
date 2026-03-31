"""
Auto-import every notification module so that ``__init_subclass__``
fires and each type registers itself in ``BaseNotification._registry``.

To add a new notification:
  1.  Create a new file in this directory.
  2.  Define a @dataclass subclass of BaseNotification.
  3.  Import it below.
  That's it — the registry picks it up automatically.
"""

from .otp import OTPNotification
from .welcome import WelcomeNotification
from .recent_login import RecentLoginNotification
from .friend_request import FriendRequestNotification
from .event_invitation import EventInvitationNotification
from .event_reminder import EventReminderNotification
from .livestream import LivestreamNotification
from .post_interaction import PostInteractionNotification
from .ticket_purchase_host import TicketPurchaseHostNotification
from .ticket_purchase_buyer import TicketPurchaseBuyerNotification
from .password_reset_confirmation import PasswordResetConfirmation

__all__ = [
    "OTPNotification",
    "WelcomeNotification",
    "RecentLoginNotification",
    "FriendRequestNotification",
    "EventInvitationNotification",
    "EventReminderNotification",
    "LivestreamNotification",
    "PostInteractionNotification",
    "TicketPurchaseHostNotification",
    "TicketPurchaseBuyerNotification",
    "PasswordResetConfirmation",
]
