"""
Event cancellation notification — sent in bulk to all ticket holders and
RSVPs when a host permanently deletes their event.

Thought process
───────────────
People who bought tickets or RSVPd have a financial and time stake in the
event.  Silently deleting it without notifying them is a support liability
and a trust violation.  We fan out to all attendee subscriber IDs at once
using Novu's bulk recipient syntax so a single trigger covers every attendee.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventCancelledNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_CHANGE
    critical = False  # never block the delete response for a notification failure

    attendee_ids: List[str]
    event_name: str
    event_id: str

    def build_recipient(self) -> List[Dict[str, str]]:
        return [{"subscriber_id": uid} for uid in self.attendee_ids]

    def build_payload(self) -> Dict[str, Any]:
        return {
            "change_type": "cancelled",
            "event_name": self.event_name,
            "event_id": self.event_id,
        }
