"""
Livestream notification.

Alerts event subscribers when a livestream goes live.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class LivestreamNotification(BaseNotification):

    workflow_id = WorkflowID.LIVESTREAM
    critical = False

    event_id: str
    subscriber_ids: List[str] = None

    def __post_init__(self):
        if self.subscriber_ids is None:
            self.subscriber_ids = []

    def build_recipient(self) -> Union[Dict[str, str], List[Dict[str, str]]]:
        return [{"subscriber_id": uid} for uid in self.subscriber_ids]

    def build_payload(self) -> Dict[str, Any]:
        return {"event_id": self.event_id}
