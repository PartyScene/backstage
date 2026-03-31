"""
KPI endpoint — serves the aggregated KPI snapshot as JSON.

Compatible with Grafana's JSON API / Infinity datasource plugin.
The endpoint returns a flat structure that Grafana can parse directly.

Mounted by the MicroService base class at /{service}/kpis.
"""

from http import HTTPStatus
from quart import current_app as app

from shared.utils.response import api_response


async def kpis_handler():
    """
    GET /{service}/kpis

    Returns the most recent KPI snapshot from Redis cache.
    If the cache is empty, triggers a synchronous refresh (rare).

    Response shape (Grafana-friendly):
    {
        "message": "KPI snapshot",
        "status": "OK",
        "data": {
            "timestamp": 1718000000.0,
            "business": {
                "total_users": 1234,
                "total_events": 56,
                ...
            },
            "realtime": {
                "signups_total": 42,
                "livestreams_active": 3,
                ...
            }
        }
    }
    """
    aggregator = getattr(app, "_kpi_aggregator", None)
    if aggregator is None:
        return api_response(
            "KPI aggregator not initialized",
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    try:
        snapshot = await aggregator.snapshot()
        return api_response("KPI snapshot", HTTPStatus.OK, data=snapshot)
    except Exception as exc:
        app.logger.error(f"KPI endpoint error: {exc}", exc_info=True)
        return api_response(
            f"Failed to retrieve KPIs: {str(exc)}",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


async def kpis_refresh_handler():
    """
    POST /{service}/kpis/refresh

    Force an immediate KPI refresh (useful for testing / manual trigger).
    """
    aggregator = getattr(app, "_kpi_aggregator", None)
    if aggregator is None:
        return api_response(
            "KPI aggregator not initialized",
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    try:
        snapshot = await aggregator.refresh()
        return api_response("KPI snapshot refreshed", HTTPStatus.OK, data=snapshot)
    except Exception as exc:
        app.logger.error(f"KPI refresh error: {exc}", exc_info=True)
        return api_response(
            f"Failed to refresh KPIs: {str(exc)}",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
