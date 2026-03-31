"""
KPI Aggregator — periodic SurrealDB aggregate queries cached in Redis.

Designed to run as a background task inside any MicroService instance.
Queries are batched into a single SurrealDB round-trip and cached in
Redis with a configurable TTL. The /kpis endpoint reads from cache,
never hitting the DB directly.

Usage:
    aggregator = KPIAggregator(pool, redis, logger)
    await aggregator.refresh()          # called periodically
    data = await aggregator.snapshot()  # called by /kpis endpoint
"""

import asyncio
import time
import logging
from typing import Any, Optional

import orjson

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
)


CACHE_KEY = "kpi:snapshot"
DEFAULT_TTL = 60  # seconds


class KPIAggregator:
    """
    Collects business KPIs from SurrealDB + Prometheus and caches them in Redis.
    """

    def __init__(self, pool, redis, logger: Optional[logging.Logger] = None, ttl: int = DEFAULT_TTL):
        """
        Args:
            pool: SurrealDBConnectionPool (from any service's connector)
            redis: async Redis client
            logger: optional logger
            ttl: cache TTL in seconds
        """
        self.pool = pool
        self.redis = redis
        self.logger = logger or logging.getLogger(__name__)
        self.ttl = ttl
        self._running = False

    # ------------------------------------------------------------------
    # DB aggregate queries (batched into one round-trip)
    # ------------------------------------------------------------------

    _AGGREGATE_QUERY = """
        -- ── Totals ──────────────────────────────────────────────────────
        LET $total_users           = count((SELECT id FROM users));
        LET $total_events          = count((SELECT id FROM events));
        LET $total_tickets         = count((SELECT id FROM tickets));
        LET $active_events         = count((SELECT id FROM events WHERE time + duration::from::mins(duration) > time::now() AND status != 'cancelled'));
        LET $total_posts           = count((SELECT id FROM posts));
        LET $total_friends         = count((SELECT id FROM friends WHERE status = 'accepted'));

        -- ── Active users (DAU / WAU / MAU) ──────────────────────────────
        LET $dau                   = count((SELECT id FROM users WHERE last_active > time::now() - 24h));
        LET $wau                   = count((SELECT id FROM users WHERE last_active > time::now() - 7d));
        LET $mau                   = count((SELECT id FROM users WHERE last_active > time::now() - 30d));

        -- ── Signups (creation windows) ──────────────────────────────────
        LET $signups_24h           = count((SELECT id FROM users WHERE created_at > time::now() - 24h));
        LET $signups_7d            = count((SELECT id FROM users WHERE created_at > time::now() - 7d));
        LET $signups_30d           = count((SELECT id FROM users WHERE created_at > time::now() - 30d));
        LET $signups_prev_7d       = count((SELECT id FROM users WHERE created_at > time::now() - 14d AND created_at <= time::now() - 7d));
        LET $signups_prev_30d      = count((SELECT id FROM users WHERE created_at > time::now() - 60d AND created_at <= time::now() - 30d));

        -- ── Retention cohorts ───────────────────────────────────────────
        LET $cohort_d1_total       = count((SELECT id FROM users WHERE created_at > time::now() - 2d AND created_at <= time::now() - 1d));
        LET $cohort_d1_retained    = count((SELECT id FROM users WHERE created_at > time::now() - 2d AND created_at <= time::now() - 1d AND last_active != NONE AND last_active > created_at));
        LET $cohort_d7_total       = count((SELECT id FROM users WHERE created_at > time::now() - 8d AND created_at <= time::now() - 7d));
        LET $cohort_d7_retained    = count((SELECT id FROM users WHERE created_at > time::now() - 8d AND created_at <= time::now() - 7d AND last_active != NONE AND last_active > time::now() - 7d));
        LET $cohort_d30_total      = count((SELECT id FROM users WHERE created_at > time::now() - 31d AND created_at <= time::now() - 30d));
        LET $cohort_d30_retained   = count((SELECT id FROM users WHERE created_at > time::now() - 31d AND created_at <= time::now() - 30d AND last_active != NONE AND last_active > time::now() - 30d));

        -- ── Churn ───────────────────────────────────────────────────────
        LET $churned_users         = count((SELECT id FROM users WHERE last_active != NONE AND last_active < time::now() - 30d));
        LET $trackable_users       = count((SELECT id FROM users WHERE last_active != NONE));

        -- ── Activity windows ────────────────────────────────────────────
        LET $events_24h            = count((SELECT id FROM events WHERE created_at > time::now() - 24h));
        LET $events_7d             = count((SELECT id FROM events WHERE created_at > time::now() - 7d));
        LET $tickets_24h           = count((SELECT id FROM tickets WHERE created_at > time::now() - 24h));
        LET $tickets_7d            = count((SELECT id FROM tickets WHERE created_at > time::now() - 7d));
        LET $tickets_30d           = count((SELECT id FROM tickets WHERE created_at > time::now() - 30d));
        LET $posts_24h             = count((SELECT id FROM posts WHERE created_at > time::now() - 24h));

        -- ── Revenue (from tier pricing × sold_count) ────────────────────
        LET $gmv_total             = (SELECT math::sum(price * sold_count) AS total FROM ticket_tiers);
        LET $avg_ticket_price      = (SELECT math::mean(price) AS avg FROM ticket_tiers WHERE sold_count > 0);

        -- ── Engagement ──────────────────────────────────────────────────
        LET $avg_attendees         = (SELECT math::mean(attendee_count) AS avg FROM events);
        LET $users_with_tickets    = count(array::distinct((SELECT VALUE user FROM tickets WHERE user != NONE)));

        RETURN {
            total_users:                $total_users,
            total_events:               $total_events,
            total_tickets:              $total_tickets,
            active_events:              $active_events,
            total_posts:                $total_posts,
            total_friends:              $total_friends,

            dau:                        $dau,
            wau:                        $wau,
            mau:                        $mau,

            signups_24h:                $signups_24h,
            signups_7d:                 $signups_7d,
            signups_30d:                $signups_30d,
            signups_prev_7d:            $signups_prev_7d,
            signups_prev_30d:           $signups_prev_30d,

            retention_d1_cohort:        $cohort_d1_total,
            retention_d1_retained:      $cohort_d1_retained,
            retention_d7_cohort:        $cohort_d7_total,
            retention_d7_retained:      $cohort_d7_retained,
            retention_d30_cohort:       $cohort_d30_total,
            retention_d30_retained:     $cohort_d30_retained,

            churned_users:              $churned_users,
            trackable_users:            $trackable_users,

            events_24h:                 $events_24h,
            events_7d:                  $events_7d,
            tickets_24h:                $tickets_24h,
            tickets_7d:                 $tickets_7d,
            tickets_30d:                $tickets_30d,
            posts_24h:                  $posts_24h,

            gmv_total_cents:            $gmv_total[0].total,
            avg_ticket_price:           $avg_ticket_price[0].avg,

            avg_attendees_per_event:    $avg_attendees[0].avg,
            users_with_tickets:         $users_with_tickets
        };
    """

    async def _fetch_db_aggregates(self) -> dict:
        """Execute the aggregate query and return a flat dict of results.

        Uses query_raw() because the query contains many LET statements
        followed by a single RETURN.  query() only returns the first
        statement's result (a LET → None), so the RETURN dict is lost.
        query_raw() returns every statement's result, and we grab the last.
        """
        try:
            async with self.pool.acquire() as conn:
                raw = await conn.query_raw(self._AGGREGATE_QUERY)

            # raw is {"result": [<per-statement>, ...], ...}
            statements = raw.get("result") if isinstance(raw, dict) else raw
            if not isinstance(statements, list) or not statements:
                self.logger.warning(f"KPI query returned unexpected shape: {type(raw)}")
                return {}

            last = statements[-1]

            # Each statement entry is {"status": "OK", "result": <value>}
            if isinstance(last, dict) and "result" in last:
                if last.get("status") == "ERR":
                    self.logger.error(f"KPI RETURN statement error: {last['result']}")
                    return {}
                data = last["result"]
            else:
                data = last

            if isinstance(data, dict):
                return self._sanitize(data)
            if isinstance(data, list) and data:
                return self._sanitize(data[0] if isinstance(data[0], dict) else {})
            return {}

        except Exception as exc:
            self.logger.error(f"KPI aggregate query failed: {exc}", exc_info=True)
            return {}

    @staticmethod
    def _sanitize(data: dict) -> dict:
        """Ensure all values are JSON-serializable primitives."""
        clean = {}
        for k, v in data.items():
            if v is None:
                clean[k] = 0
            elif isinstance(v, (int, float, str, bool)):
                clean[k] = v
            elif isinstance(v, list):
                clean[k] = v[0] if v else 0
            else:
                clean[k] = str(v)
        return clean

    # ------------------------------------------------------------------
    # Prometheus metric extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_prometheus_metrics() -> dict:
        """
        Read current values from the in-process Prometheus registry.
        Returns a dict of metric_name -> value (or dict of label->value).
        """
        from .collector import BusinessMetrics  # avoid circular at module level

        metrics = {}

        # Simple counters (total value)
        metrics["signups_total"] = _counter_value(BusinessMetrics.SIGNUPS)
        metrics["events_created_total"] = _counter_value(BusinessMetrics.EVENTS_CREATED)
        metrics["event_attendances_total"] = _counter_value(BusinessMetrics.EVENT_ATTENDANCES)
        metrics["posts_created_total"] = _counter_value(BusinessMetrics.POSTS_CREATED)
        metrics["friend_requests_total"] = _counter_value(BusinessMetrics.FRIEND_REQUESTS)
        metrics["livestream_starts_total"] = _counter_value(BusinessMetrics.LIVESTREAM_STARTS)
        metrics["ticket_checkins_total"] = _counter_value(BusinessMetrics.TICKET_CHECKINS)

        # Labeled counters — flatten to dict
        metrics["logins_total"] = _labeled_counter_values(BusinessMetrics.LOGINS)
        metrics["ticket_purchases_total"] = _labeled_counter_values(BusinessMetrics.TICKET_PURCHASES)
        metrics["revenue_cents_total"] = _labeled_counter_values(BusinessMetrics.REVENUE_CENTS)

        # Gauges
        metrics["livestreams_active"] = _gauge_value(BusinessMetrics.LIVESTREAMS_ACTIVE)

        return metrics

    # ------------------------------------------------------------------
    # Refresh & snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_derived(db: dict) -> dict:
        """
        Compute investor-grade derived metrics from raw DB aggregates.

        All rates are expressed as percentages (0-100).
        Division-by-zero is handled gracefully (returns 0).
        """
        def _safe_pct(numerator, denominator):
            n = db.get(numerator, 0) or 0
            d = db.get(denominator, 0) or 0
            return round((n / d) * 100, 2) if d else 0

        def _safe_growth(current_key, previous_key):
            c = db.get(current_key, 0) or 0
            p = db.get(previous_key, 0) or 0
            return round(((c - p) / p) * 100, 2) if p else 0

        derived = {}

        # ── Retention rates (D1 / D7 / D30) ─────────────────────────
        derived["retention_d1_rate"] = _safe_pct("retention_d1_retained", "retention_d1_cohort")
        derived["retention_d7_rate"] = _safe_pct("retention_d7_retained", "retention_d7_cohort")
        derived["retention_d30_rate"] = _safe_pct("retention_d30_retained", "retention_d30_cohort")

        # ── Churn rate (inactive 30d+ / trackable) ──────────────────
        derived["churn_rate"] = _safe_pct("churned_users", "trackable_users")

        # ── Growth rates ─────────────────────────────────────────────
        derived["growth_wow_pct"] = _safe_growth("signups_7d", "signups_prev_7d")
        derived["growth_mom_pct"] = _safe_growth("signups_30d", "signups_prev_30d")

        # ── DAU/MAU ratio (stickiness, target ~20-30% for social) ───
        dau = db.get("dau", 0) or 0
        mau = db.get("mau", 0) or 0
        derived["dau_mau_ratio"] = round((dau / mau) * 100, 2) if mau else 0

        # ── ARPU (GMV / MAU) ─────────────────────────────────────────
        gmv = db.get("gmv_total_cents", 0) or 0
        derived["arpu_cents"] = round(gmv / mau, 2) if mau else 0

        # ── Conversion (users who bought tickets / total users) ──────
        derived["ticket_conversion_pct"] = _safe_pct("users_with_tickets", "total_users")

        return derived

    async def refresh(self) -> dict:
        """
        Fetch fresh aggregates from DB + Prometheus, merge, cache in Redis.
        Returns the merged snapshot dict.
        """
        t0 = time.monotonic()

        db_data = await self._fetch_db_aggregates()
        prom_data = self._collect_prometheus_metrics()
        derived = self._compute_derived(db_data)

        snapshot = {
            "timestamp": time.time(),
            "business": db_data,
            "derived": derived,
            "realtime": prom_data,
        }

        # Cache in Redis
        try:
            await self.redis.set(
                CACHE_KEY,
                orjson.dumps(snapshot),
                ex=self.ttl,
            )
        except Exception as exc:
            self.logger.error(f"KPI cache write failed: {exc}")

        elapsed = time.monotonic() - t0
        self.logger.info(f"KPI refresh completed in {elapsed:.3f}s")
        return snapshot

    async def snapshot(self) -> dict:
        """
        Return the most recent cached snapshot, or refresh if cache is empty.
        This is the method called by the /kpis endpoint.
        """
        try:
            cached = await self.redis.get(CACHE_KEY)
            if cached:
                return orjson.loads(cached)
        except Exception as exc:
            self.logger.error(f"KPI cache read failed: {exc}")

        # Fallback: refresh now
        return await self.refresh()

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def start_background_loop(self, interval: int = 60):
        """
        Start a background task that refreshes KPI aggregates every `interval` seconds.
        Call this once at app startup (e.g. in before_serving).
        """
        if self._running:
            return
        self._running = True
        self.logger.info(f"KPI background refresh loop started (interval={interval}s)")

        async def _loop():
            while self._running:
                try:
                    await self.refresh()
                except Exception as exc:
                    self.logger.error(f"KPI background refresh error: {exc}", exc_info=True)
                await asyncio.sleep(interval)

        asyncio.create_task(_loop())

    def stop(self):
        """Signal the background loop to stop."""
        self._running = False


# ======================================================================
# Prometheus helper functions
# ======================================================================

def _counter_value(counter: Counter) -> float:
    """Get the current value of a label-less counter."""
    try:
        return counter._value.get()
    except AttributeError:
        # If the counter has no observations yet, _metrics is empty
        try:
            # For counters without labels
            for metric in counter.collect():
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        return sample.value
        except Exception:
            pass
    return 0.0


def _gauge_value(gauge: Gauge) -> float:
    """Get the current value of a label-less gauge."""
    try:
        return gauge._value.get()
    except AttributeError:
        try:
            for metric in gauge.collect():
                for sample in metric.samples:
                    return sample.value
        except Exception:
            pass
    return 0.0


def _labeled_counter_values(counter: Counter) -> dict:
    """Get all label combinations and their values for a labeled counter."""
    result = {}
    try:
        for metric in counter.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    label_key = "|".join(f"{k}={v}" for k, v in sorted(sample.labels.items()))
                    result[label_key] = sample.value
    except Exception:
        pass

    # Also return a flat total
    result["_total"] = sum(result.values())
    return result
