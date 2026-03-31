# Grafana KPI Dashboard Setup

Connect your Partyscene `/kpis` endpoint to Grafana Cloud using the **Infinity** datasource plugin.

## 1. Install Infinity Plugin

In Grafana Cloud → **Administration → Plugins** → search **"Infinity"** → Install.

## 2. Add Datasource

**Configuration → Data Sources → Add data source → Infinity**

| Field | Value |
|-------|-------|
| Name | `Partyscene KPIs` |
| URL | `https://your-api-domain.com/auth/kpis` |
| Auth | Bearer token (optional, if endpoint is protected) |

## 3. Dashboard Panels

### Panel: Active Users (DAU / WAU / MAU)

- **Type**: Stat or Bar gauge
- **Source**: Infinity → JSON
- **URL**: `/auth/kpis`
- **Parser**: JSONata
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.business.dau` | DAU |
| `$.business.wau` | WAU |
| `$.business.mau` | MAU |

### Panel: Retention Rates

- **Type**: Gauge (0–100 range)
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.derived.retention_d1_rate` | D1 Retention % |
| `$.derived.retention_d7_rate` | D7 Retention % |
| `$.derived.retention_d30_rate` | D30 Retention % |

### Panel: Growth & Churn

- **Type**: Stat
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.derived.growth_wow_pct` | Signup Growth WoW % |
| `$.derived.growth_mom_pct` | Signup Growth MoM % |
| `$.derived.churn_rate` | Churn Rate % |
| `$.derived.dau_mau_ratio` | Stickiness (DAU/MAU) % |

### Panel: Revenue & Conversion

- **Type**: Stat
- **Fields**:

| Field Path | Display Name | Unit |
|------------|-------------|------|
| `$.business.gmv_total_cents` | Total GMV | cents → currency |
| `$.derived.arpu_cents` | ARPU | cents → currency |
| `$.derived.ticket_conversion_pct` | Ticket Conversion % | percent |
| `$.business.avg_ticket_price` | Avg Ticket Price | currency |

### Panel: Totals Overview

- **Type**: Stat grid
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.business.total_users` | Total Users |
| `$.business.total_events` | Total Events |
| `$.business.total_tickets` | Total Tickets |
| `$.business.total_posts` | Total Posts |
| `$.business.total_friends` | Friendships |
| `$.business.active_events` | Active Events |

### Panel: Real-time Counters (since last restart)

- **Type**: Stat
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.realtime.signups_total` | Signups |
| `$.realtime.logins_total` | Logins (by provider) |
| `$.realtime.events_created_total` | Events Created |
| `$.realtime.ticket_purchases_total` | Ticket Purchases |
| `$.realtime.livestream_starts_total` | Livestream Starts |
| `$.realtime.livestreams_active` | Active Livestreams |
| `$.realtime.posts_created_total` | Posts Created |

### Panel: Activity Trends (24h / 7d / 30d)

- **Type**: Bar chart or Table
- **Fields**:

| Field Path | Display Name |
|------------|-------------|
| `$.business.signups_24h` | Signups (24h) |
| `$.business.signups_7d` | Signups (7d) |
| `$.business.signups_30d` | Signups (30d) |
| `$.business.events_24h` | Events (24h) |
| `$.business.tickets_24h` | Tickets (24h) |
| `$.business.tickets_30d` | Tickets (30d) |
| `$.business.posts_24h` | Posts (24h) |

## 4. Refresh Interval

Set the dashboard auto-refresh to **1m** (matches the KPI aggregator's 60s background loop).

For on-demand refresh, the endpoint `POST /auth/kpis/refresh` forces an immediate recalculation.

## 5. JSON Response Structure

```json
{
  "timestamp": 1711886400.0,
  "business": {
    "total_users": 1234,
    "dau": 89,
    "wau": 312,
    "mau": 876,
    "retention_d1_cohort": 15,
    "retention_d1_retained": 8,
    "churned_users": 45,
    "trackable_users": 900,
    "gmv_total_cents": 5678900,
    "..."
  },
  "derived": {
    "retention_d1_rate": 53.33,
    "retention_d7_rate": 42.0,
    "retention_d30_rate": 28.5,
    "churn_rate": 5.0,
    "growth_wow_pct": 12.5,
    "growth_mom_pct": 8.3,
    "dau_mau_ratio": 10.16,
    "arpu_cents": 648.29,
    "ticket_conversion_pct": 15.4
  },
  "realtime": {
    "signups_total": 42,
    "logins_total": {"password": 100, "google": 50, "apple": 30},
    "ticket_purchases_total": {"stripe": 25, "paystack": 10},
    "livestreams_active": 2,
    "..."
  }
}
```

## 6. Alerts (Optional)

Set up Grafana alerts on key thresholds:

| Metric | Condition | Severity |
|--------|-----------|----------|
| `derived.churn_rate` | > 10% | Warning |
| `derived.retention_d1_rate` | < 20% | Critical |
| `derived.dau_mau_ratio` | < 5% | Warning |
| `business.dau` | < 10 | Info |

## 7. Investor Dashboard Template

For funding presentations, create a dedicated dashboard row with:

1. **MAU trend** (track over time with Infinity's UQL backend)
2. **Retention curve** (D1 → D7 → D30 as a bar chart)
3. **Revenue metrics** (GMV, ARPU, conversion)
4. **Growth rates** (WoW, MoM signup growth)
5. **Stickiness** (DAU/MAU ratio — target 20-30% for social apps)
