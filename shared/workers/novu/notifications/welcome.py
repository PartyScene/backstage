"""
Welcome notification — NEW.

Sent once after a user successfully verifies their email and completes
registration.

Thought process
───────────────
Every major consumer app (Spotify, Airbnb, Luma, Partiful) sends a
welcome email immediately after sign-up.  It:
  1. Confirms the account is active.
  2. Sets expectations for what the platform does.
  3. Drives first engagement (e.g. "create your first event").

We trigger this in the auth /verify endpoint right after
`_store_after_verify` succeeds — that's the moment the user truly
becomes a registered member.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID, APP_NAME


@dataclass
class WelcomeNotification(BaseNotification):

    workflow_id = WorkflowID.WELCOME
    critical = False  # welcome email failure should never block registration

    subscriber_id: str
    first_name: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "first_name": self.first_name,
        }
