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


APP_NAME = "Scenes"
