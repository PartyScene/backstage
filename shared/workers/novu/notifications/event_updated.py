"""
Event update notification — sent to all attendees when the host changes
a material detail of the event (time, date, or location).

Thought process
───────────────
Cosmetic changes (cover photo, description) don't warrant a push.  Only
fields that affect whether an attendee can actually show up — time and
location — are "material".  The caller is responsible for filtering which
fields changed before instantiating this notification.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventUpdatedNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_CHANGE
    critical = False

    attendee_ids: List[str]
    event_name: str
    event_id: str
    changed_fields: List[str]  # e.g. ["time", "location"]

    def build_recipient(self) -> List[Dict[str, str]]:
        return [{"subscriber_id": uid} for uid in self.attendee_ids]

    def build_payload(self) -> Dict[str, Any]:
        return {
            "change_type": "updated",
            "event_name": self.event_name,
            "event_id": self.event_id,
            "changed_fields": ", ".join(self.changed_fields),
        }
