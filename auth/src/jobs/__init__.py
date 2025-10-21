"""Background jobs for the auth service."""

from auth.src.jobs.scheduled_deletion_cleanup import ScheduledDeletionCleanup

__all__ = ["ScheduledDeletionCleanup"]
