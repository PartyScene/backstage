"""
Base notification class with auto-registration.

Thought process
───────────────
The *Registry* pattern (a.k.a. self-registering plugins) is how Stripe's
internal notification service, Uber's uNotify, and Django's admin all
handle open-ended sets of handlers.  `__init_subclass__` lets every
concrete notification register itself at import time — no central list
to maintain, no risk of forgetting to add a new type.

Each notification is a @dataclass so:
  • The required payload fields are enforced by the constructor.
  • IDE autocomplete "just works" for every notification type.
  • `asdict()` gives us the Novu payload with zero manual dict-building.

The `critical` flag controls error propagation strategy:
  • critical=True  → failure raises (OTP, login alerts — callers must know)
  • critical=False → failure is logged and swallowed (reminders, social —
    a flaky Novu call should never break the happy path)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Union

from novu_py import TriggerEventRequestDto


class BaseNotification(ABC):
    """
    Abstract base for every notification type.

    Subclasses must set:
        workflow_id  — Novu workflow to trigger
        build_recipient()  — who receives the notification
        build_payload()    — what data to include

    Auto-registration: defining a subclass with a non-empty `workflow_id`
    adds it to ``_registry`` automatically via ``__init_subclass__``.
    """

    _registry: ClassVar[Dict[str, type]] = {}

    workflow_id: ClassVar[str] = ""
    critical: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.workflow_id:
            BaseNotification._registry[cls.workflow_id] = cls

    # ── Abstract interface ──────────────────────────────────────────

    @abstractmethod
    def build_recipient(self) -> Union[Dict[str, str], List[Dict[str, str]]]:
        """Return the ``to`` field for the Novu trigger."""
        ...

    @abstractmethod
    def build_payload(self) -> Dict[str, Any]:
        """Return the ``payload`` field for the Novu trigger."""
        ...

    # ── Concrete helpers ────────────────────────────────────────────

    def to_trigger_request(self) -> TriggerEventRequestDto:
        """Build a ready-to-send Novu trigger request."""
        return TriggerEventRequestDto(
            workflow_id=self.workflow_id,
            to=self.build_recipient(),
            payload=self.build_payload(),
        )

    @classmethod
    def list_registered(cls) -> Dict[str, type]:
        """Return a snapshot of all registered notification types."""
        return dict(cls._registry)
