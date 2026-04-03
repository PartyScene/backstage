"""
KYC decision notification — sent to the user after Veriff approves or
declines their identity verification.

Thought process
───────────────
Hosts submit KYC and then have no feedback loop — they have to re-open
the app and guess.  Sending a push + email at decision time closes that
loop immediately, reducing support tickets and re-submission attempts.
The `approved` flag lets the Novu template branch on status without
requiring two separate workflows.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class KYCDecisionNotification(BaseNotification):

    workflow_id = WorkflowID.KYC_DECISION
    critical = False  # notification failure must never break the Veriff webhook response

    subscriber_id: str
    approved: bool

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "status": "approved" if self.approved else "declined",
        }
