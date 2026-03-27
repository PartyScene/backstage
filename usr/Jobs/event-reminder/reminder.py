"""
event-reminder — Cloud Run Job

Queries SurrealDB for events starting in the next 60 minutes that haven't
had a reminder dispatched yet, atomically claims them (sets reminder_sent),
then fires a Novu "event-reminder" notification to every attendee.

Designed to run every 15 minutes via Cloud Scheduler. Atomic claiming via
UPDATE...WHERE reminder_sent = NONE means overlapping runs are safe — only
one instance will claim any given event.

Environment variables required:
    SURREAL_URI, SURREAL_USER, SURREAL_PASS  — SurrealDB connection
    NOVU_SECRET_KEY                           — Novu API key
"""

import asyncio
import logging
import os

from surrealdb import AsyncSurreal
from shared.workers.novu import NotificationManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SURREAL_URI  = os.environ["SURREAL_URI"]
SURREAL_USER = os.environ["SURREAL_USER"]
SURREAL_PASS = os.environ["SURREAL_PASS"]
NAMESPACE    = "partyscene"
DATABASE     = "partyscene"

# How many minutes before the event we send the reminder.
# Cloud Scheduler fires every 15 min, so a 75-min window ensures no event is
# missed even if one run is slightly delayed.
REMINDER_WINDOW_MINS = 75

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def run():
    notifier = NotificationManager()

    async with AsyncSurreal(SURREAL_URI) as db:
        await db.signin({"username": SURREAL_USER, "password": SURREAL_PASS})
        await db.use(NAMESPACE, DATABASE)

        # Atomically claim all events starting within the reminder window that
        # haven't been claimed yet.  UPDATE...RETURN BEFORE gives us the rows
        # as they were before the write — so we're guaranteed to process each
        # event exactly once even if two job instances run concurrently.
        claimed = await db.query(
            """
            UPDATE events
            SET reminder_sent = time::now()
            WHERE is_private = false
              AND reminder_sent  = NONE
              AND time > time::now()
              AND time < time::now() + type::duration(string::concat($window, "m"))
            RETURN BEFORE;
            """,
            {"window": str(REMINDER_WINDOW_MINS)},
        )

        if not claimed:
            logger.info("No events to remind about — exiting.")
            return

        logger.info(f"Claimed {len(claimed)} event(s) for reminder dispatch.")

        for event in claimed:
            event_id   = str(event.get("id", "")).split(":")[-1]
            event_name = event.get("name", "your event")

            # Fetch attendee IDs for this event
            attendees = await db.query(
                """
                SELECT VALUE in.id FROM attends WHERE out = $event_id;
                """,
                {"event_id": event["id"]},
            )

            # Flatten and stringify — attendees is [[RecordID, ...]]
            attendee_ids = [
                str(a).split(":")[-1]
                for a in (attendees[0] if attendees else [])
                if a
            ]

            if not attendee_ids:
                logger.info(f"Event {event_id} ({event_name}): no attendees, skipping.")
                continue

            result = await notifier.send_event_reminder(
                event_id=event_id,
                event_name=event_name,
                attendee_ids=attendee_ids,
                minutes_until=REMINDER_WINDOW_MINS,
            )

            logger.info(
                f"✅ Reminder sent for '{event_name}' ({event_id}) "
                f"to {len(attendee_ids)} attendee(s). Novu response: {result}"
            )


if __name__ == "__main__":
    asyncio.run(run())