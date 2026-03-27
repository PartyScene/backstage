"""
Event invitation notification.

Sends an invite to one or more users when they are invited to an event.
Uses Novu's bulk recipient support (list of subscriber dicts).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventInvitationNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_INVITATION
    critical = False

    event_id: str
    invitee_ids: List[str] = None

    def __post_init__(self):
        if self.invitee_ids is None:
            self.invitee_ids = []

    def build_recipient(self) -> Union[Dict[str, str], List[Dict[str, str]]]:
        return [{"subscriber_id": uid} for uid in self.invitee_ids]

    def build_payload(self) -> Dict[str, Any]:
        return {"event_id": self.event_id}
