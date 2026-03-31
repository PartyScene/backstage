"""
Password reset confirmation notification.

Sent after a user successfully resets their password via the
``POST /auth/reset-password`` endpoint.  This serves two purposes:

  1. Security alert — if the user did NOT reset their password, they
     know immediately that their account may be compromised.
  2. UX closure — confirms the action succeeded so the user can
     confidently log in with their new credentials.

Novu workflow setup
───────────────────
The ``password-reset-confirmation`` workflow should have:
  1. Email — "Your password has been changed"
  2. Push (FCM / APNs) — "Your Scenes password was just changed"
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID, APP_NAME


@dataclass
class PasswordResetConfirmation(BaseNotification):

    workflow_id = WorkflowID.PASSWORD_RESET_CONFIRMATION
    critical = False  # must never block the reset-password response

    subscriber_id: str
    email: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "email": self.email,
        }
