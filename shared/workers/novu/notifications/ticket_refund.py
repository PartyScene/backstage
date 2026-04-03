"""
Ticket refund notification — sent to the ticket buyer when a refund has
been issued (event cancellation, host-initiated refund, or dispute).

Thought process
───────────────
Refunds are high-anxiety moments for buyers.  Stripe processes the refund
silently; without this notification the buyer either checks their bank
statement days later or opens a support ticket.  An immediate confirmation
reduces both support load and chargeback risk.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class TicketRefundNotification(BaseNotification):

    workflow_id = WorkflowID.TICKET_REFUND
    critical = False

    subscriber_id: str
    event_name: str
    event_id: str
    amount: float
    currency: str

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "event_name": self.event_name,
            "event_id": self.event_id,
            "amount": self.amount,
            "currency": self.currency.upper(),
        }
