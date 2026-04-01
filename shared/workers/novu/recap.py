"""
Event recap collector — computes "PartyScene Wrapped" insights.

Given an event ID and a SurrealDB connection, this module queries every
data source (tickets, attendance, posts, guestlists, media, livestream)
and produces a flat dict of insights ready to be passed directly to
EventRecapNotification as **kwargs.

Thought process
───────────────
Spotify Wrapped works because it transforms raw listening data into
*stories*: "You were in the top 1%", "Your most-played song", "You
discovered 47 new artists".  We do the same for event hosts:

  • "87% of ticket holders actually showed up"
  • "VIP tier sold out in 2 hours"
  • "12 attendees posted 34 photos"
  • "If you'd filled every seat, you'd have made $4,200"

Every insight is computed server-side so the Novu email template is
pure presentation — no logic, just handlebars.

All queries run in a single connection acquisition to minimise pool
contention.  The batch query returns everything in one round-trip.
"""

import logging
import os
from collections import Counter
from datetime import timedelta
from typing import Any, Dict, List, Optional

from shared.utils.signer import generate_cdn_signed_url

logger = logging.getLogger(__name__)

# Maximum media items to include in the notification payload
MAX_MEDIA_ITEMS = 6
MAX_TOP_CONTRIBUTORS = 5

# Recap emails are archival — sign media URLs for 1 year so they
# remain viewable whenever the host reopens the email.
RECAP_MEDIA_TTL = timedelta(days=365)
LOAD_BALANCER_BASE_URL = os.environ.get("LOAD_BALANCER_BASE_URL", "")

# ── Batch query ─────────────────────────────────────────────────────────────
# Single round-trip to SurrealDB that returns everything needed for a recap.

_RECAP_QUERY = """
-- 1. Full event record
LET $event = (SELECT
    *,
    (time + duration::from::mins(duration)) AS end_time,
    host.{id, first_name, last_name, organization_name, avatar} AS host_profile
FROM ONLY type::thing('events', $event_id));

-- 2. Ticket tiers with revenue
LET $tiers = (SELECT
    id, name, price, capacity, sold_count, description
FROM ticket_tiers
WHERE event = type::thing('events', $event_id)
ORDER BY price ASC);

-- 3. All tickets (for check-in analysis)
LET $tickets = (SELECT
    id, user, guest_email, guest_name, tier,
    checked_in_at, created_at
FROM tickets
WHERE event = type::thing('events', $event_id));

-- 4. Posts for this event
LET $posts = (SELECT
    id,
    in.{id, first_name, last_name, avatar} AS author,
    content, created_at
FROM posts
WHERE event = type::thing('events', $event_id)
AND visible = true
ORDER BY created_at ASC);

-- 5. Comments on those posts
LET $comment_count = (SELECT VALUE count()
FROM comments
WHERE out.event = type::thing('events', $event_id)
GROUP ALL);

-- 6. Event media
LET $media = (SELECT
    filename, thumbnail, blurhash
FROM media
WHERE id IN (
    SELECT VALUE ->has_media->media.id
    FROM ONLY type::thing('events', $event_id)
));

-- 7. Guestlist
LET $guestlist = (SELECT
    status
FROM guestlists
WHERE out = type::thing('events', $event_id));

-- 8. Livestream scene
LET $scene = (SELECT
    live_started_at, metadata, created_at, updated_at
FROM scenes
WHERE event = type::thing('events', $event_id)
LIMIT 1);

RETURN {
    event: $event,
    tiers: $tiers,
    tickets: $tickets,
    posts: $posts,
    comment_count: $comment_count,
    media: $media,
    guestlist: $guestlist,
    scene: $scene
};
"""


def _safe_pct(numerator: float, denominator: float) -> float:
    """Compute percentage, return 0.0 on division by zero."""
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _format_hour_range(hour: int) -> str:
    """Convert 24h hour int to a readable range like '8:00 PM - 9:00 PM'."""
    def _fmt(h: int) -> str:
        if h == 0 or h == 24:
            return "12:00 AM"
        if h == 12:
            return "12:00 PM"
        if h < 12:
            return f"{h}:00 AM"
        return f"{h - 12}:00 PM"
    return f"{_fmt(hour)} - {_fmt((hour + 1) % 24)}"


def _extract_name(user_obj: Any) -> str:
    """Pull a display name from a user dict or record ID string."""
    if isinstance(user_obj, dict):
        first = user_obj.get("first_name", "")
        last = user_obj.get("last_name", "")
        if first or last:
            return f"{first} {last}".strip()
    if isinstance(user_obj, str) and ":" in user_obj:
        return user_obj.split(":")[-1][:8]
    return str(user_obj) if user_obj else "Unknown"


def _extract_avatar(user_obj: Any) -> str:
    """Pull avatar URL from a user dict."""
    if isinstance(user_obj, dict):
        return user_obj.get("avatar", "") or ""
    return ""


async def collect_recap(
    db_conn,
    event_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Query SurrealDB and compute all recap insights for one event.

    Args:
        db_conn: An active SurrealDB async connection (already signed
                 in and using the correct namespace/database).
        event_id: The event ID (without the 'events:' prefix).

    Returns:
        A dict of kwargs ready for EventRecapNotification, or None if
        the event doesn't exist or has no meaningful data.
    """
    # query_raw() is required because the query has multiple LET
    # statements followed by a RETURN.  query() only returns the
    # first statement's result (a LET → None), losing the RETURN.
    try:
        raw = await db_conn.query_raw(
            _RECAP_QUERY, {"event_id": event_id},
        )
    except Exception as e:
        logger.error("Recap query failed for event %s: %s", event_id, e)
        return None

    # raw is {"result": [<per-statement>, ...], ...}
    statements = raw.get("result") if isinstance(raw, dict) else raw
    if not isinstance(statements, list) or not statements:
        logger.warning("No recap data returned for event %s", event_id)
        return None

    last = statements[-1]

    # Each statement entry is {"status": "OK", "result": <value>}
    if isinstance(last, dict) and "result" in last:
        if last.get("status") == "ERR":
            logger.error(
                "Recap RETURN error for event %s: %s",
                event_id, last["result"],
            )
            return None
        data = last["result"]
    else:
        data = last

    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    if not data or not isinstance(data, dict):
        logger.warning("No recap data returned for event %s", event_id)
        return None

    event = data.get("event")
    if isinstance(event, list):
        event = event[0] if event else None
    if not event:
        logger.warning("Event %s not found in recap query", event_id)
        return None

    tiers = data.get("tiers") or []
    tickets = data.get("tickets") or []
    posts = data.get("posts") or []
    comment_count_raw = data.get("comment_count") or []
    media = data.get("media") or []
    guestlist = data.get("guestlist") or []
    scene_list = data.get("scene") or []

    # CDN-sign a GCS filename into a publicly accessible URL.
    # Mirrors sign_media_url / sign_media_object robustness:
    #   • str  → plain filename, sign directly
    #   • dict → media object with "filename" key, extract and sign
    #   • falsy / anything else → empty string
    def _sign(obj) -> str:
        path = ""
        if isinstance(obj, dict):
            path = obj.get("filename", "") or ""
        elif isinstance(obj, str):
            path = obj
        if not path:
            return ""
        try:
            return generate_cdn_signed_url(
                LOAD_BALANCER_BASE_URL, "/" + path, RECAP_MEDIA_TTL,
            )
        except Exception as e:
            logger.error("Failed to sign media path %s: %s", path, e)
            return ""

    # ── Attendance ──────────────────────────────────────────────────
    registered = [t for t in tickets if t.get("user")]
    guests = [t for t in tickets if t.get("guest_email")]
    total_attendees = len(registered) + len(guests)
    scanned = [t for t in tickets if t.get("checked_in_at")]
    no_shows = [t for t in tickets if not t.get("checked_in_at")]
    checkin_rate = _safe_pct(len(scanned), total_attendees)

    # ── Peak check-in hour ──────────────────────────────────────────
    first_checkin_name = ""
    first_checkin_time = ""
    peak_checkin_hour = ""
    if scanned:
        sorted_scans = sorted(
            scanned,
            key=lambda t: t.get("checked_in_at", ""),
        )
        first = sorted_scans[0]
        first_user = first.get("user")
        first_checkin_name = (
            first.get("guest_name")
            or _extract_name(first_user)
        )
        first_checkin_time = str(
            first.get("checked_in_at", "")
        )[:16]  # trim to YYYY-MM-DDTHH:MM

        # Find the busiest hour
        hours: List[int] = []
        for t in sorted_scans:
            ts = str(t.get("checked_in_at", ""))
            if "T" in ts:
                try:
                    hours.append(int(ts.split("T")[1][:2]))
                except (ValueError, IndexError):
                    pass
        if hours:
            most_common_hour = Counter(hours).most_common(1)[0][0]
            peak_checkin_hour = _format_hour_range(most_common_hour)

    # ── Revenue ─────────────────────────────────────────────────────
    tier_breakdown = []
    total_revenue = 0.0
    total_capacity = 0
    total_sold = 0
    best_tier_name = ""
    best_tier_sold = 0

    for tier in tiers:
        price = float(tier.get("price", 0) or 0)
        sold = int(tier.get("sold_count", 0) or 0)
        cap = tier.get("capacity")
        cap_int = int(cap) if cap is not None else None
        tier_rev = price * sold
        total_revenue += tier_rev
        total_sold += sold

        fill = _safe_pct(sold, cap_int) if cap_int else 0.0
        if cap_int:
            total_capacity += cap_int

        tier_breakdown.append({
            "name": tier.get("name", "General"),
            "price": price,
            "sold": sold,
            "capacity": cap_int,
            "revenue": round(tier_rev, 2),
            "fill_rate": fill,
        })

        if sold > best_tier_sold:
            best_tier_sold = sold
            best_tier_name = tier.get("name", "General")

    sellthrough_rate = _safe_pct(total_sold, total_capacity)

    # Projections
    avg_ticket_price = (
        round(total_revenue / total_sold, 2) if total_sold else 0.0
    )
    projected_full = sum(
        float(t.get("price", 0) or 0) * int(t.get("capacity") or t.get("sold_count", 0) or 0)
        for t in tiers
    )
    revenue_missed = round(max(projected_full - total_revenue, 0), 2)

    # ── Engagement ──────────────────────────────────────────────────
    total_posts_count = len(posts)
    total_comments = (
        comment_count_raw[0]
        if comment_count_raw and isinstance(comment_count_raw[0], int)
        else 0
    )
    # count unique media referenced in posts
    total_media_uploads = len(media)
    engagement_rate = (
        round(total_posts_count / total_attendees, 2)
        if total_attendees
        else 0.0
    )

    # ── Top contributors ────────────────────────────────────────────
    author_posts: Counter = Counter()
    author_info: Dict[str, Dict[str, str]] = {}
    for post in posts:
        author = post.get("author") or {}
        author_id = ""
        if isinstance(author, dict):
            raw_id = author.get("id", "")
            author_id = (
                str(raw_id).split(":")[-1]
                if raw_id
                else ""
            )
        elif isinstance(author, str):
            author_id = str(author).split(":")[-1]
        if author_id:
            author_posts[author_id] += 1
            if author_id not in author_info:
                author_info[author_id] = {
                    "name": _extract_name(author),
                    "avatar": _extract_avatar(author),
                }

    top_contributors = []
    for uid, count in author_posts.most_common(MAX_TOP_CONTRIBUTORS):
        info = author_info.get(uid, {})
        top_contributors.append({
            "name": info.get("name", uid),
            "avatar": _sign(info.get("avatar", "")),
            "post_count": count,
        })

    # ── Guestlist ───────────────────────────────────────────────────
    total_invited = len(guestlist)
    accepted = sum(
        1 for g in guestlist if g.get("status") == "accepted"
    )
    declined = sum(
        1 for g in guestlist if g.get("status") == "declined"
    )
    invite_acceptance_rate = _safe_pct(accepted, total_invited)

    # ── Livestream ──────────────────────────────────────────────────
    had_livestream = False
    livestream_duration_mins = 0
    if scene_list:
        scene = scene_list[0] if isinstance(scene_list, list) else scene_list
        if scene and scene.get("live_started_at"):
            had_livestream = True
            started = scene.get("live_started_at", "")
            ended_at = scene.get("updated_at", "")
            if started and ended_at:
                try:
                    from datetime import datetime, timezone
                    fmt = "%Y-%m-%dT%H:%M:%S"
                    s = str(started)[:19]
                    e = str(ended_at)[:19]
                    dt_start = datetime.strptime(s, fmt)
                    dt_end = datetime.strptime(e, fmt)
                    diff = (dt_end - dt_start).total_seconds()
                    if diff > 0:
                        livestream_duration_mins = int(diff // 60)
                except (ValueError, TypeError):
                    pass

    # ── Visuals ─────────────────────────────────────────────────────
    event_media = []
    hero_image_url = ""
    for m in media[:MAX_MEDIA_ITEMS]:
        filename = m.get("filename", "") or ""
        thumb = m.get("thumbnail", "") or ""
        entry = {
            "url": _sign(filename),
            "thumbnail": _sign(thumb),
            "blurhash": m.get("blurhash", "") or "",
        }
        event_media.append(entry)
        if not hero_image_url and entry["url"]:
            hero_image_url = entry["url"]

    # ── Event metadata ──────────────────────────────────────────────
    event_date = str(event.get("time", ""))[:10]  # YYYY-MM-DD
    event_duration_mins = int(event.get("duration", 60) or 60)
    location = event.get("location", {})
    event_location = (
        location.get("address", "")
        if isinstance(location, dict)
        else ""
    )
    event_categories = event.get("categories", []) or []

    # ── Trending score (same formula as fn::fetch_trending_events) ──
    attendee_count = int(event.get("attendee_count", 0) or 0)
    trending_score = (attendee_count * 3) + (total_posts_count * 2)

    # ── Currency from event or first tier ───────────────────────────
    currency = "USD"
    if event.get("currency"):
        currency = event["currency"]

    return {
        # Attendance
        "total_attendees": total_attendees,
        "registered_attendees": len(registered),
        "guest_attendees": len(guests),
        "checkin_count": len(scanned),
        "checkin_rate": checkin_rate,
        "no_show_count": len(no_shows),
        # Revenue
        "total_revenue": round(total_revenue, 2),
        "currency": currency,
        "tickets_sold": total_sold,
        "tier_breakdown": tier_breakdown,
        "best_selling_tier": best_tier_name,
        "sellthrough_rate": sellthrough_rate,
        # Engagement
        "total_posts": total_posts_count,
        "total_comments": total_comments,
        "total_media_uploads": total_media_uploads,
        "engagement_rate": engagement_rate,
        # Highlights
        "top_contributors": top_contributors,
        "first_checkin_name": first_checkin_name,
        "first_checkin_time": first_checkin_time,
        "peak_checkin_hour": peak_checkin_hour,
        # Guestlist
        "total_invited": total_invited,
        "invites_accepted": accepted,
        "invites_declined": declined,
        "invite_acceptance_rate": invite_acceptance_rate,
        # Livestream
        "had_livestream": had_livestream,
        "livestream_duration_mins": livestream_duration_mins,
        # Visuals
        "event_media": event_media,
        "hero_image_url": hero_image_url,
        # Event metadata
        "event_date": event_date,
        "event_duration_mins": event_duration_mins,
        "event_location": event_location,
        "event_categories": event_categories,
        # Predictions
        "projected_full_capacity_revenue": round(projected_full, 2),
        "revenue_opportunity_missed": revenue_missed,
        "avg_ticket_price": avg_ticket_price,
        "trending_score": trending_score,
    }
