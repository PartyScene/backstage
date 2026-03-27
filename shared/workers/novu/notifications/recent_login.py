"""
Recent login alert notification.

Notifies the user when their account is accessed from a new session,
similar to what Google, GitHub, and Stripe send on every sign-in.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class RecentLoginNotification(BaseNotification):

    workflow_id = WorkflowID.RECENT_LOGIN
    critical = True  # security alert — caller should know if it fails

    subscriber_id: str
    ip_address: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "ip_address": self.ip_address,
            "timestamp": self.timestamp,
        }
