"""
KPI Tracking & Monitoring Module for Partyscene.

Provides:
- BusinessMetrics: Prometheus counters for business events (signups, logins, purchases, etc.)
- KPIAggregator: Periodic DB aggregate queries cached in Redis
- kpi_blueprint: Quart blueprint exposing /kpis endpoint (Grafana-compatible JSON)
"""

from .collector import BusinessMetrics
from .aggregator import KPIAggregator

__all__ = [
    "BusinessMetrics",
    "KPIAggregator",
]
