"""
Account deletion warning — sent 7 days before the user's account is
permanently deleted, giving them a final opportunity to cancel the request.

Thought process
───────────────
The 30-day grace period is only useful if the user knows the clock is
running out.  The scheduled deletion cleanup job sends this warning once,
at the T-7 mark, and sets `deletion_warning_sent` so it's never resent.
A single well-timed warning is far more actionable than repeated nags.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class AccountDeletionWarningNotification(BaseNotification):

    workflow_id = WorkflowID.ACCOUNT_DELETION_WARNING
    critical = False  # a failed warning must not abort the cleanup job

    subscriber_id: str
    deletion_date: str  # ISO-8601 date string

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "deletion_date": self.deletion_date,
        }
