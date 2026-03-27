"""
Friend request notification.

Alerts a user when someone sends them a connection / friend request.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class FriendRequestNotification(BaseNotification):

    workflow_id = WorkflowID.FRIEND_REQUEST
    critical = False  # social notification — don't break the friend-request flow

    recipient_id: str
    sender_name: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.recipient_id}

    def build_payload(self) -> Dict[str, Any]:
        return {"sender_name": self.sender_name}
