"""
Centralized notification configuration.

All Novu workflow IDs and shared constants live here — a single source
of truth so that renaming a workflow is a one-line change instead of a
codebase-wide grep-and-replace.

Thought process
───────────────
Leading notification platforms (Novu, Knock, Courier) all recommend
externalising workflow identifiers from business logic. Hardcoding them
as default params across dozens of methods is a maintenance hazard that
gets worse with every new notification type.
"""


class WorkflowID:
    """
    Each class attribute maps a logical notification type to its Novu
    workflow identifier.  Import this instead of sprinkling string
    literals across the codebase.
    """

    OTP_VERIFICATION = "email-verification-flow"
    RECENT_LOGIN = "recent-login"
    WELCOME = "welcome"
    FRIEND_REQUEST = "friend-request"
    EVENT_INVITATION = "event-invitation"
    EVENT_REMINDER = "event-reminder"
    LIVESTREAM = "livestream-notification"
    POST_INTERACTION = "post-interaction"
    TICKET_PURCHASE_HOST = "ticket-purchase-host-notification"
    TICKET_PURCHASE_BUYER = "ticket-purchase-buyer-receipt"
    PASSWORD_RESET_CONFIRMATION = "password-reset-confirmation"
    EVENT_RECAP = "event-recap"
    EVENT_RSVP_ATTENDEE = "event-rsvp-attendee"
    EVENT_RSVP_HOST = "event-rsvp-host"
    HOST_WELCOME = "host-welcome"
    EVENT_CANCELLED = "event-cancelled"
    EVENT_UPDATED = "event-updated"
    KYC_DECISION = "kyc-decision"
    GUESTLIST_DECISION = "guestlist-decision"
    GUESTLIST_RSVP = "guestlist-rsvp"
    PAYOUT_PROCESSED = "payout-processed"
    TICKET_REFUND = "ticket-refund"
    ACCOUNT_DELETION_WARNING = "account-deletion-warning"
    TICKET_CHECKIN_HOST = "ticket-checkin-host"


APP_NAME = "Scenes"
