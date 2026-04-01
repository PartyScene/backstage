"""
Host welcome notification.

Sent when a user becomes a host (e.g. creates their first event or
is granted host privileges). Distinct from the general welcome email
which goes to all new signups.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID, APP_NAME


@dataclass
class HostWelcomeNotification(BaseNotification):

    workflow_id = WorkflowID.HOST_WELCOME
    critical = False

    subscriber_id: str
    first_name: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "first_name": self.first_name,
        }
