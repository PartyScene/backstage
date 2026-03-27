"""
Event reminder notification.

Sends a "your event starts soon" push to all attendees.
Designed to be triggered by the Cloud Run cron job (event-reminder).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventReminderNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_REMINDER
    critical = False  # reminder failure should never break the cron job

    event_id: str
    event_name: str
    attendee_ids: List[str] = None
    minutes_until: int = 60

    def __post_init__(self):
        if self.attendee_ids is None:
            self.attendee_ids = []

    def build_recipient(self) -> Union[Dict[str, str], List[Dict[str, str]]]:
        return [{"subscriber_id": uid} for uid in self.attendee_ids]

    def build_payload(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "minutes_until": self.minutes_until,
        }
