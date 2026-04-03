"""
Guestlist status notifications — two variants covering both directions of
the host ↔ guest decision flow.

  GuestlistDecisionNotification
    Fired when the *host* accepts or declines a guest's application.
    Recipient: the guest.

  GuestlistRSVPNotification
    Fired when the *guest* accepts or declines a host-issued invitation.
    Recipient: the host.

Thought process
───────────────
The RSVP endpoint is bidirectional — either party can update the status
field.  We branch on who made the change and notify the other party,
keeping both sides informed without a separate workflow per direction.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class GuestlistDecisionNotification(BaseNotification):
    """Host accepted or declined a guest's guestlist application."""

    workflow_id = WorkflowID.GUESTLIST_STATUS
    critical = False

    guest_subscriber_id: str
    event_name: str
    event_id: str
    status: str  # "accepted" | "declined"

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.guest_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "notification_type": "host_decision",
            "event_name": self.event_name,
            "event_id": self.event_id,
            "status": self.status,
        }


@dataclass
class GuestlistRSVPNotification(BaseNotification):
    """Invited guest accepted or declined a host-issued invitation."""

    workflow_id = WorkflowID.GUESTLIST_STATUS
    critical = False

    host_subscriber_id: str
    guest_name: str
    event_name: str
    event_id: str
    status: str  # "accepted" | "declined"

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "notification_type": "guest_rsvp",
            "guest_name": self.guest_name,
            "event_name": self.event_name,
            "event_id": self.event_id,
            "status": self.status,
        }
