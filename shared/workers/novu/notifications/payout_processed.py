"""
Payout processed notification — sent to an event host when a Stripe payout
has been dispatched to their bank account.

Thought process
───────────────
Hosts sell tickets and trust the platform to forward their revenue.
A payout confirmation email is standard practice (Stripe, Eventbrite, and
Luma all send one) and builds host confidence in the platform.

The `payout.paid` event fires on the *connected* Stripe account webhook,
not the platform webhook.  The payments service webhook handler receives
it only when the platform is configured with `connect: true` event
forwarding, or when a connected-account webhook is registered per host.
The handler must look up the host by their `stripe_account_id` to resolve
the Novu subscriber_id.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class PayoutProcessedNotification(BaseNotification):

    workflow_id = WorkflowID.PAYOUT_PROCESSED
    critical = False  # payout notification failure must never re-trigger the webhook

    host_subscriber_id: str
    amount: float
    currency: str
    arrival_date: str  # ISO-8601 date string

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency.upper(),
            "arrival_date": self.arrival_date,
        }
