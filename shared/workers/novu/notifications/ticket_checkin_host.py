"""
Ticket check-in host notification — sent to the event host the moment a
ticket is freshly scanned and checked in at the door.

Thought process
───────────────
Hosts standing at the entrance want real-time awareness of who has arrived,
especially for VIP tiers or small private events.  This is a push-only,
non-critical notification — if Novu is slow the door scanner must not stall.
Already-checked-in scans are excluded by the caller to avoid duplicate pings.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class TicketCheckinHostNotification(BaseNotification):

    workflow_id = WorkflowID.TICKET_CHECKIN_HOST
    critical = False  # never block a door-scan response for a notification failure

    host_subscriber_id: str
    event_name: str
    event_id: str
    attendee_name: str
    ticket_number: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "event_name": self.event_name,
            "event_id": self.event_id,
            "attendee_name": self.attendee_name,
            "ticket_number": self.ticket_number,
        }
