"""
Ticket purchase buyer receipt — push + email notification.

Sent to the buyer immediately after their ticket purchase is confirmed
(Stripe or Paystack webhook success).  Complements the rich HTML receipt
email sent via Resend by delivering a real-time push notification so the
buyer sees instant confirmation on their lock screen.

Novu workflow setup
───────────────────
The ``ticket-purchase-buyer-receipt`` workflow should have two steps:
  1. Push (FCM / APNs) — "Your tickets for {{event_name}} are confirmed!"
  2. In-App — fallback if push delivery fails or user has no device token.

The Resend HTML receipt is sent separately in payments/src/views/base.py
via ``_send_tickets_email`` and is intentionally NOT part of this Novu
workflow to avoid duplicate emails (Novu email vs Resend email).
"""

from dataclasses import dataclass
from typing import Any, Dict

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
        }
