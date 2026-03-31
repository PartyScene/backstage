"""
Event recap notification — "PartyScene Wrapped" for hosts.

Sent to event organizers after their event concludes, delivering a
Spotify-Wrapped-style summary of everything that happened: attendance
stats, revenue breakdown, engagement highlights, top contributors,
and growth predictions.

Thought process
───────────────
Eventbrite sends a bare-bones "your event ended" email.  Spotify Wrapped
proved that *celebrating* user data drives massive engagement and
sharing.  By packaging post-event analytics into a visually rich,
shareable recap, we:
  1. Make hosts feel the impact of their event immediately.
  2. Drive repeat event creation ("your next one could be even bigger").
  3. Give hosts social-proof content to share on Instagram/TikTok.
  4. Surface insights that help hosts optimise pricing and marketing.

The payload is intentionally rich — Novu's template engine renders
the visuals, but we compute every data point server-side so the
template stays logic-free.

Triggered by:
  • CronJob (primary) — runs hourly, catches all ended events.
  • Inline (immediate) — when host sets status to "ended" via API.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from shared.workers.novu.base import BaseNotification
from shared.workers.novu.config import WorkflowID


@dataclass
class EventRecapNotification(BaseNotification):

    workflow_id = WorkflowID.EVENT_RECAP
    critical = False  # recap failure must never block event lifecycle

    host_subscriber_id: str
    event_id: str
    event_name: str

    # ── Attendance ──────────────────────────────────────────────────
    total_attendees: int = 0
    registered_attendees: int = 0
    guest_attendees: int = 0
    checkin_count: int = 0
    checkin_rate: float = 0.0       # percentage
    no_show_count: int = 0

    # ── Revenue ─────────────────────────────────────────────────────
    total_revenue: float = 0.0
    currency: str = "USD"
    tickets_sold: int = 0
    tier_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    # each: {name, price, sold, capacity, revenue, fill_rate}
    best_selling_tier: str = ""
    sellthrough_rate: float = 0.0   # percentage of total capacity sold

    # ── Engagement ──────────────────────────────────────────────────
    total_posts: int = 0
    total_comments: int = 0
    total_media_uploads: int = 0
    engagement_rate: float = 0.0    # posts per attendee

    # ── Highlights ──────────────────────────────────────────────────
    top_contributors: List[Dict[str, str]] = field(default_factory=list)
    # each: {name, avatar, post_count}
    first_checkin_name: str = ""
    first_checkin_time: str = ""
    peak_checkin_hour: str = ""     # e.g. "8:00 PM - 9:00 PM"

    # ── Guestlist ───────────────────────────────────────────────────
    total_invited: int = 0
    invites_accepted: int = 0
    invites_declined: int = 0
    invite_acceptance_rate: float = 0.0

    # ── Livestream ──────────────────────────────────────────────────
    had_livestream: bool = False
    livestream_duration_mins: int = 0

    # ── Visuals ─────────────────────────────────────────────────────
    event_media: List[Dict[str, str]] = field(default_factory=list)
    # each: {url, thumbnail, blurhash} — first N media items
    hero_image_url: str = ""        # primary event flyer/cover

    # ── Event metadata ──────────────────────────────────────────────
    event_date: str = ""            # formatted start date
    event_duration_mins: int = 0
    event_location: str = ""
    event_categories: List[str] = field(default_factory=list)

    # ── Predictions & forecasts ─────────────────────────────────────
    projected_full_capacity_revenue: float = 0.0
    revenue_opportunity_missed: float = 0.0
    avg_ticket_price: float = 0.0
    trending_score: int = 0

    def build_recipient(self) -> Dict[str, str]:
        return {"subscriber_id": self.host_subscriber_id}

    def build_payload(self) -> Dict[str, Any]:
        return {
            # Identity
            "event_id": self.event_id,
            "event_name": self.event_name,
            "event_date": self.event_date,
            "event_duration_mins": self.event_duration_mins,
            "event_location": self.event_location,
            "event_categories": self.event_categories,

            # Attendance card
            "total_attendees": self.total_attendees,
            "registered_attendees": self.registered_attendees,
            "guest_attendees": self.guest_attendees,
            "checkin_count": self.checkin_count,
            "checkin_rate": self.checkin_rate,
            "no_show_count": self.no_show_count,

            # Revenue card
            "total_revenue": self.total_revenue,
            "currency": self.currency,
            "tickets_sold": self.tickets_sold,
            "tier_breakdown": self.tier_breakdown,
            "best_selling_tier": self.best_selling_tier,
            "sellthrough_rate": self.sellthrough_rate,

            # Engagement card
            "total_posts": self.total_posts,
            "total_comments": self.total_comments,
            "total_media_uploads": self.total_media_uploads,
            "engagement_rate": self.engagement_rate,

            # Highlights card
            "top_contributors": self.top_contributors,
            "first_checkin_name": self.first_checkin_name,
            "first_checkin_time": self.first_checkin_time,
            "peak_checkin_hour": self.peak_checkin_hour,

            # Guestlist card
            "total_invited": self.total_invited,
            "invites_accepted": self.invites_accepted,
            "invites_declined": self.invites_declined,
            "invite_acceptance_rate": self.invite_acceptance_rate,

            # Livestream card
            "had_livestream": self.had_livestream,
            "livestream_duration_mins": self.livestream_duration_mins,

            # Visuals
            "event_media": self.event_media,
            "hero_image_url": self.hero_image_url,

            # Predictions & forecasts
            "projected_full_capacity_revenue":
                self.projected_full_capacity_revenue,
            "revenue_opportunity_missed":
                self.revenue_opportunity_missed,
            "avg_ticket_price": self.avg_ticket_price,
            "trending_score": self.trending_score,
        }
