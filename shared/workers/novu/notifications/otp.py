"""
OTP verification notification.

Sends a one-time password to the user's email for identity verification
during registration or password reset flows.
"""

from dataclasses import dataclass
from typing import Any, Dict

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID, APP_NAME


@dataclass
class OTPNotification(BaseNotification):
    """
    Payload:
        subscriber_id — Novu subscriber to receive the OTP
        otp_code      — the generated one-time password
        ip_address    — IP that requested the OTP (for transparency)
        location      — human-readable location derived from IP
    """

    workflow_id = WorkflowID.OTP_VERIFICATION
    critical = True  # OTP delivery failure must propagate

    subscriber_id: str
    otp_code: str
    ip_address: str
    location: str = ""

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            "data": {
                "app_name": APP_NAME,
                "requested_by": self.ip_address,
                "requested_at": self.location,
                "otp_code": self.otp_code,
            }
        }
