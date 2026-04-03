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
    # Merged: host + buyer share one workflow; template branches on notification_type
    TICKET_PURCHASE = "ticket-purchase"
    TICKET_PURCHASE_HOST = TICKET_PURCHASE   # alias — do not use for new Novu workflows
    TICKET_PURCHASE_BUYER = TICKET_PURCHASE  # alias — do not use for new Novu workflows

    PASSWORD_RESET_CONFIRMATION = "password-reset-confirmation"
    EVENT_RECAP = "event-recap"

    # Merged: attendee + host share one workflow; template branches on notification_type
    EVENT_RSVP = "event-rsvp"
    EVENT_RSVP_ATTENDEE = EVENT_RSVP   # alias
    EVENT_RSVP_HOST = EVENT_RSVP       # alias

    HOST_WELCOME = "host-welcome"

    # Merged: cancelled + updated share one workflow; template branches on change_type
    EVENT_CHANGE = "event-change"
    EVENT_CANCELLED = EVENT_CHANGE   # alias
    EVENT_UPDATED = EVENT_CHANGE     # alias

    KYC_DECISION = "kyc-decision"

    # Merged: host decision + guest RSVP share one workflow; template branches on notification_type
    GUESTLIST_STATUS = "guestlist-status"
    GUESTLIST_DECISION = GUESTLIST_STATUS   # alias
    GUESTLIST_RSVP = GUESTLIST_STATUS       # alias

    PAYOUT_PROCESSED = "payout-processed"
    TICKET_REFUND = "ticket-refund"
    ACCOUNT_DELETION_WARNING = "account-deletion-warning"
    TICKET_CHECKIN_HOST = "ticket-checkin-host"


APP_NAME = "Scenes"
