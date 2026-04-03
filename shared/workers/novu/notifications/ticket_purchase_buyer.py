"""
Ticket purchase buyer receipt — push + email notification.

Sent to the buyer immediately after their ticket purchase is confirmed
(Stripe or Paystack webhook success).  Carries QR ticket data so the
Novu email step renders one QR card per ticket inline — Resend is no
longer used for authenticated buyers.

Novu workflow setup
───────────────────
The ``ticket-purchase`` workflow buyer branch should have three steps:
  1. Email — ticket_purchase.html (buyer branch with QR loop)
  2. Push (FCM / APNs) — "Your tickets for {{event_name}} are confirmed!"
  3. In-App — fallback if push delivery fails or user has no device token.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class TicketPurchaseBuyerNotification(BaseNotification):

    workflow_id = WorkflowID.TICKET_PURCHASE
    critical = False  # push failure must never block ticket issuance

    buyer_subscriber_id: str
    event_name: str
    event_id: str
    ticket_count: int
    total_amount: float = 0.0
    currency: str = "USD"
    ticket_numbers: List[str] = field(default_factory=list)

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.buyer_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "notification_type": "buyer",
            "event_name": self.event_name,
            "event_id": self.event_id,
            "ticket_count": self.ticket_count,
            "total_amount": self.total_amount,
            "currency": self.currency,
            "ticket_numbers": self.ticket_numbers,
        }
