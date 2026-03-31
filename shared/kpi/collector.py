"""
Business-specific Prometheus metrics for Partyscene KPI tracking.

These counters/gauges are incremented at key code points across services.
Prometheus scrapes them via the existing /{service}/metrics endpoint.
The KPIAggregator reads them (along with DB aggregates) to build the
/kpis JSON payload for Grafana.
"""

from prometheus_client import Counter, Gauge, Histogram


class BusinessMetrics:
    """
    Singleton-style namespace for all business KPI Prometheus metrics.

    Usage:
        from shared.kpi import BusinessMetrics

        BusinessMetrics.SIGNUPS.inc()
        BusinessMetrics.LOGINS.inc()
        BusinessMetrics.TICKET_PURCHASES.labels(payment_provider="stripe").inc()
        BusinessMetrics.LIVESTREAMS_ACTIVE.inc()   # on go-live
        BusinessMetrics.LIVESTREAMS_ACTIVE.dec()   # on end-live
    """

    # ── Auth ──────────────────────────────────────────────────────────────
    SIGNUPS = Counter(
        "partyscene_signups_total",
        "Total number of successful user registrations",
    )
    LOGINS = Counter(
        "partyscene_logins_total",
        "Total number of successful logins",
        ["auth_provider"],  # password | google | apple
    )

    # ── Events ────────────────────────────────────────────────────────────
    EVENTS_CREATED = Counter(
        "partyscene_events_created_total",
        "Total number of events created",
    )
    EVENT_ATTENDANCES = Counter(
        "partyscene_event_attendances_total",
        "Total attendance marks (free + paid)",
    )

    # ── Tickets / Revenue ─────────────────────────────────────────────────
    TICKET_PURCHASES = Counter(
        "partyscene_ticket_purchases_total",
        "Total paid ticket purchases",
        ["payment_provider"],  # stripe | paystack
    )
    REVENUE_CENTS = Counter(
        "partyscene_revenue_cents_total",
        "Total revenue in the smallest currency unit (cents/kobo)",
        ["payment_provider", "currency"],
    )

    # ── Livestream ────────────────────────────────────────────────────────
    LIVESTREAMS_ACTIVE = Gauge(
        "partyscene_livestreams_active",
        "Number of currently live streams",
    )
    LIVESTREAM_STARTS = Counter(
        "partyscene_livestream_starts_total",
        "Total number of livestream go-live events",
    )

    # ── Posts / Social ────────────────────────────────────────────────────
    POSTS_CREATED = Counter(
        "partyscene_posts_created_total",
        "Total posts created",
    )
    FRIEND_REQUESTS = Counter(
        "partyscene_friend_requests_total",
        "Total friend requests sent",
    )

    # ── Ticket Verification ───────────────────────────────────────────────
    TICKET_CHECKINS = Counter(
        "partyscene_ticket_checkins_total",
        "Total successful ticket check-ins (QR scans)",
    )
