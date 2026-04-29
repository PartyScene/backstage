# Backup Monitoring & Alerting Setup

## Overview
This document describes the monitoring and alerting setup for SurrealDB backups.

## Cloud Monitoring Dashboard

### Metrics to Monitor

1. **Snapshot Creation Success**
   - Metric: `compute.googleapis.com/snapshots/created_count`
   - Filter: `resource.labels.snapshot_name =~ "surrealvm.*"`
   - Alert: No snapshots created in last 48h

2. **Snapshot Age**
   - Custom metric via Cloud Monitoring
   - Alert: Latest snapshot older than 48h

3. **Snapshot Storage Size**
   - Metric: `compute.googleapis.com/snapshots/storage_bytes`
   - Filter: `resource.labels.snapshot_name =~ "surrealvm.*"`

4. **Backup Validation Job Status**
   - Metric: `batch.googleapis.com/job/status`
   - Filter: `resource.labels.job_name = "surrealdb-backup-validation"`
   - Alert: Job failed

## Alert Policies

### Alert 1: Snapshot Creation Failure

```bash
# Create alert policy for snapshot creation failure
gcloud alpha monitoring policies create \
  --display-name="SurrealDB Snapshot Creation Failure" \
  --condition-display-name="No snapshots in 48h" \
  --condition-filter='resource.type="gce_disk" AND resource.labels.disk_name="surrealvm"' \
  --condition-duration=48h \
  --condition-threshold-comparison=COMPARISON_LT \
  --condition-threshold-value=1 \
  --notification-channels=projects/partyscene-441317/notificationChannels/SLACK \
  --enabled
```

### Alert 2: Backup Validation Job Failure

```bash
# Create alert policy for backup validation failure
gcloud alpha monitoring policies create \
  --display-name="SurrealDB Backup Validation Failure" \
  --condition-display-name="Validation job failed" \
  --condition-filter='resource.type="k8s_pod" AND resource.labels.pod_name=~"surrealdb-backup-validation.*"' \
  --condition-duration=1h \
  --condition-threshold-comparison=COMPARISON_GT \
  --condition-threshold-value=0 \
  --notification-channels=projects/partyscene-441317/notificationChannels/SLACK \
  --enabled
```

## Notification Channels

### Slack Integration

```bash
# Create Slack notification channel
gcloud alpha monitoring channels create \
  --display-name="Slack Alerts" \
  --type=slack \
  --channel-labels=channel_name="#alerts" \
  --channel-labels=auth_token="${SLACK_AUTH_TOKEN}" \
  --channel-labels=team_name="${SLACK_TEAM_NAME}"
```

## Custom Metrics Exporter

Create a Cloud Function to export custom backup metrics:

```python
# main.py
import functions_framework
from google.cloud import monitoring_v3
import datetime

@functions_framework.http
def export_backup_metrics(request):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{os.getenv('PROJECT_ID')}"
    
    # Get latest snapshot
    snapshots = list_gce_snapshots(project_id, filter="name:surrealvm")
    latest_snapshot = snapshots[0] if snapshots else None
    
    if latest_snapshot:
        # Calculate snapshot age in hours
        snapshot_time = latest_snapshot.creation_timestamp
        age_hours = (datetime.datetime.now(datetime.timezone.utc) - snapshot_time).total_seconds() / 3600
        
        # Write custom metric
        series = monitoring_v3.TimeSeries()
        series.metric.type = "custom.googleapis.com/surrealdb/snapshot_age_hours"
        series.resource.type = "gce_instance"
        series.resource.labels["instance_name"] = "surrealvm"
        
        point = series.points.add()
        point.value.double_value = age_hours
        point.interval.end_time.GetCurrentTime()
        
        client.create_time_series(name=project_name, time_series=[series])
    
    return "OK", 200
```

## Grafana Dashboard (Alternative)

If using Grafana, import this dashboard configuration:

```json
{
  "dashboard": {
    "title": "SurrealDB Backup Status",
    "panels": [
      {
        "title": "Snapshot Age (Hours)",
        "targets": [
          {
            "expr": "surrealdb_snapshot_age_hours"
          }
        ],
        "alert": {
          "conditions": [
            {
              "evaluator": {
                "params": [48],
                "type": "gt"
              },
              "operator": {
                "type": "and"
              }
            }
          ]
        }
      },
      {
        "title": "Snapshot Count",
        "targets": [
          {
            "expr": "count(gce_snapshot{disk=\"surrealvm\"})"
          }
        ]
      },
      {
        "title": "Backup Validation Status",
        "targets": [
          {
            "expr": "kube_job_status_succeeded{job_name=\"surrealdb-backup-validation\"}"
          }
        ]
      }
    ]
  }
}
```

## Manual Check Commands

```bash
# Check latest snapshot age
gcloud compute snapshots list \
  --filter="sourceDisk~surrealvm" \
  --format="table(name,createTime)" \
  --sort-by="~createTime" \
  --limit=1

# Check snapshot count in last 7 days
gcloud compute snapshots list \
  --filter="sourceDisk~surrealvm AND creationTime>'$(date -d '7 days ago' +%Y-%m-%d)'" \
  --format="value(name)" | wc -l

# Check backup validation job status
kubectl get cronjob surrealdb-backup-validation
kubectl get jobs --selector=app=backup-validation --sort-by=.metadata.creationTimestamp
```

## Cost Monitoring

Track backup storage costs:

```bash
# Check snapshot storage costs
gcloud billing accounts get-iam-policy 01C2E4-123456-7890AB
```

## Recommended Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Snapshot Age | 24h | 48h |
| Snapshot Count (7 days) | < 12 | < 10 |
| Validation Job Failure | - | Immediate |
| Storage Growth | > 20% MoM | > 50% MoM |
