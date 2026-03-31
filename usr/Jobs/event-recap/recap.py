"""
event-recap — Cloud Run Job

Queries SurrealDB for events that have ended (either manually set to
"ended" or whose time+duration has elapsed) that haven't received a
recap yet, computes "PartyScene Wrapped" insights, and sends the recap
notification to each event's host.

Designed to run every hour via Cloud Scheduler.  Atomic claiming via
UPDATE...WHERE recap_sent = NONE means overlapping runs are safe — only
one instance will ever process a given event.

Environment variables required:
    SURREAL_URI, SURREAL_USER, SURREAL_PASS  — SurrealDB connection
    NOVU_SECRET_KEY                           — Novu API key
"""

import asyncio
import logging
import os

from surrealdb import AsyncSurreal
from shared.workers.novu import NotificationManager
from shared.workers.novu.recap import collect_recap

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SURREAL_URI  = os.environ["SURREAL_URI"]
SURREAL_USER = os.environ["SURREAL_USER"]
SURREAL_PASS = os.environ["SURREAL_PASS"]
NAMESPACE    = "partyscene"
DATABASE     = "partyscene"

# Only send recaps for events that ended at least this many minutes ago,
# so final check-ins and posts are captured.
COOLDOWN_MINS = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claim query
# ---------------------------------------------------------------------------

_CLAIM_QUERY = """
UPDATE events
SET recap_sent = time::now()
WHERE
    (
        status = 'ended'
        OR (time + duration::from::mins(duration)) < time::now() - type::duration(string::concat($cooldown, "m"))
    )
    AND recap_sent = NONE
    AND time != NONE
RETURN BEFORE;
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def run():
    notifier = NotificationManager()

    async with AsyncSurreal(SURREAL_URI) as db:
        await db.signin({"username": SURREAL_USER, "password": SURREAL_PASS})
        await db.use(NAMESPACE, DATABASE)

        # Atomically claim all ended events that haven't been recapped.
        claimed = await db.query(
            _CLAIM_QUERY,
            {"cooldown": str(COOLDOWN_MINS)},
        )

        if not claimed:
            logger.info("No events need recap — exiting.")
            return

        # Flatten: claimed can be [[...]] depending on driver version
        events = claimed
        if isinstance(events, list) and events and isinstance(events[0], list):
            events = events[0]

        logger.info("Claimed %d event(s) for recap dispatch.", len(events))

        for event in events:
            event_id = str(event.get("id", "")).split(":")[-1]
            event_name = event.get("title", "") or event.get("name", "Your Event")

            # Extract host subscriber ID
            host = event.get("host")
            if isinstance(host, dict):
                host_id = str(host.get("id", "")).split(":")[-1]
            elif host:
                host_id = str(host).split(":")[-1]
            else:
                logger.warning(
                    "Event %s (%s): no host found, skipping.",
                    event_id, event_name,
                )
                continue

            if not host_id:
                logger.warning(
                    "Event %s (%s): empty host ID, skipping.",
                    event_id, event_name,
                )
                continue

            # Collect all recap data
            recap_data = await collect_recap(db, event_id)
            if not recap_data:
                logger.warning(
                    "Event %s (%s): no recap data, skipping.",
                    event_id, event_name,
                )
                continue

            # Send the recap notification
            result = await notifier.send_event_recap(
                host_subscriber_id=host_id,
                event_id=event_id,
                event_name=event_name,
                **recap_data,
            )

            total = recap_data.get("total_attendees", 0)
            revenue = recap_data.get("total_revenue", 0)
            posts = recap_data.get("total_posts", 0)
            logger.info(
                "Recap sent for '%s' (%s) — "
                "%d attendees, $%.2f revenue, %d posts. "
                "Novu response: %s",
                event_name, event_id, total, revenue, posts, result,
            )


if __name__ == "__main__":
    asyncio.run(run())
