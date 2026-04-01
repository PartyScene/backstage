"""
Event RSVP notification — sent to both attendee and host on free attendance.

Fired from the mark_attendance endpoint (not the payment webhooks).
This covers free events and direct RSVPs where no purchase occurs.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventRSVPAttendeeNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_RSVP_ATTENDEE
    critical = False

    subscriber_id: str
    event_name: str
    event_id: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "event_name": self.event_name,
            "event_id": self.event_id,
        }


@dataclass
class EventRSVPHostNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_RSVP_HOST
    critical = False

    host_subscriber_id: str
    attendee_name: str
    event_name: str
    event_id: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "attendee_name": self.attendee_name,
            "event_name": self.event_name,
            "event_id": self.event_id,
        }
