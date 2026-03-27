"""
Ticket purchase host notification — NEW.

Notifies the event host every time someone buys a ticket to their event.

Thought process
───────────────
Eventbrite, Luma, and Partiful all notify hosts in real-time when tickets
sell.  This serves two purposes:
  1. Excitement / social proof — hosts see momentum building.
  2. Operational awareness — hosts know to prepare for larger turnout.

We fire this from the Stripe and Paystack webhook handlers, right after
tickets are created and the attendee count is incremented.  The host's
Novu subscriber_id is fetched from the event record.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class TicketPurchaseHostNotification(BaseNotification):

    workflow_id = WorkflowID.TICKET_PURCHASE_HOST
    critical = False  # host notification failure must never block ticket issuance

    host_subscriber_id: str
    buyer_name: str
    event_name: str
    event_id: str
    ticket_count: int
    total_amount: float = 0.0
    currency: str = "USD"

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "buyer_name": self.buyer_name,
            "event_name": self.event_name,
            "event_id": self.event_id,
            "ticket_count": self.ticket_count,
            "total_amount": self.total_amount,
            "currency": self.currency,
        }
