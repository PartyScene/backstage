"""
Post interaction notification.

Notifies a post owner when someone likes, comments, or otherwise
interacts with their content.

NOTE: The original implementation was synchronous. This version is async
for consistency with the rest of the notification system.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class PostInteractionNotification(BaseNotification):

    workflow_id = WorkflowID.POST_INTERACTION
    critical = False

    post_id: str
    actor_id: str
    recipient_id: str
    interaction_type: str  # "like", "comment", etc.

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.recipient_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "actor_id": self.actor_id,
            "interaction_type": self.interaction_type,
        }
