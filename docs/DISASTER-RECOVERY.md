# Disaster Recovery Procedures

## Overview
This document outlines the procedures for disaster recovery of the SurrealDB database.

## System Architecture

- **Database**: SurrealDB running in Docker container
- **Compute Engine VM**: `surrealvm` in zone `us-central1-a`
- **Network Access**: **Internal-only** - VM is only accessible via VPC/private network, not from external IPs
- **Persistent Disk**: `surrealvm` (10GB, pd-balanced)
- **Backup Disk**: `surrealvm-20250402-093916` (manual backup from April 2, 2025)
- **Snapshots**: Automated 2x daily (01:35 and 01:59 UTC), ~28-day retention
- **Namespace**: `partyscene`
- **Database**: `partyscene`
- **Port**: 8000 (listens on 0.0.0.0 internally)

## Backup Strategy

### Automated Snapshots
- **Frequency**: 2x daily (01:35 and 01:59 UTC)
- **Retention**: ~28 days (56 snapshots)
- **Coverage**: Both `surrealvm` and `surrealvm-20250402-093916` disks
- **Location**: us-central1-a

### Backup Validation
- **Schedule**: Weekly (Sunday 03:00 UTC)
- **Process**: Automated restoration test to temporary VM
- **Verification**: Database connectivity and record count check
- **Alerts**: Slack notification on failure

## Recovery Time Objective (RTO)
- **Target**: < 4 hours
- **Current**: ~2 hours (with automated script)
- **Worst Case**: ~8 hours (manual process)

## Recovery Point Objective (RPO)
- **Target**: < 24 hours
- **Current**: ~12 hours (2x daily snapshots)
- **Worst Case**: ~48 hours (if one snapshot fails)

## Disaster Scenarios

### Scenario 1: VM Failure
**Severity**: High
**Impact**: Database unavailable
**RTO**: < 2 hours

**Recovery Steps**:
1. Identify the latest snapshot
   ```bash
   gcloud compute snapshots list \
     --filter="sourceDisk~surrealvm" \
     --format="table(name,createTime)" \
     --sort-by="~createTime" \
     --limit=1
   ```

2. Run automated restoration script
   ```bash
   cd /home/dylee/backstage/scripts
   ./restore-surrealdb.sh
   ```

3. Verify database connectivity (must use SSH, VM is internal-only)
   ```bash
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="curl http://localhost:8000/health"
   ```

4. Update DNS/load balancer if needed

5. Verify application connectivity
   ```bash
   kubectl get pods -l app=microserv.users
   kubectl logs deploy/microserv.users --tail=50
   ```

### Scenario 2: Disk Failure
**Severity**: Critical
**Impact**: Data loss risk
**RTO**: < 4 hours

**Recovery Steps**:
1. Stop the VM to prevent further damage
   ```bash
   gcloud compute instances stop surrealvm --zone=us-central1-a
   ```

2. Detach the failed disk
   ```bash
   gcloud compute instances detach-disk surrealvm \
     --disk=surrealvm \
     --zone=us-central1-a
   ```

3. Create new disk from latest snapshot
   ```bash
   SNAPSHOT_NAME=$(gcloud compute snapshots list \
     --filter="sourceDisk~surrealvm" \
     --format="value(name)" \
     --sort-by="~createTime" \
     --limit=1)
   
   gcloud compute disks create surrealvm-new \
     --source-snapshot="$SNAPSHOT_NAME" \
     --zone=us-central1-a \
     --type=pd-balanced
   ```

4. Attach new disk to VM
   ```bash
   gcloud compute instances attach-disk surrealvm \
     --disk=surrealvm-new \
     --zone=us-central1-a \
     --device-name=surrealvm-new
   ```

5. Start VM
   ```bash
   gcloud compute instances start surrealvm --zone=us-central1-a
   ```

6. Start SurrealDB container
   ```bash
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="docker start surrealdb"
   ```

7. Verify database (see Scenario 1 steps 3-5)

### Scenario 3: Data Corruption
**Severity**: Critical
**Impact**: Data integrity compromised
**RTO**: < 8 hours

**Recovery Steps**:
1. Identify point of corruption (check logs, user reports)

2. Find snapshot from before corruption
   ```bash
   gcloud compute snapshots list \
     --filter="sourceDisk~surrealvm AND creationTime<'<CORRUPTION_TIME>'" \
     --format="table(name,createTime)" \
     --sort-by="~createTime" \
     --limit=5
   ```

3. Restore from pre-corruption snapshot
   ```bash
   ./restore-surrealdb.sh --snapshot <SNAPSHOT_NAME>
   ```

4. Verify data integrity (use SSH, VM is internal-only)
   ```bash
   # Check record counts
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="curl http://localhost:8000/sql \
       -H 'NS: partyscene' \
       -H 'DB: partyscene' \
       -d 'SELECT count() FROM users GROUP ALL;'"
   
   # Check specific records
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="curl http://localhost:8000/sql \
       -H 'NS: partyscene' \
       -H 'DB: partyscene' \
       -d \"SELECT * FROM users WHERE id = 'users:KNOWN_ID';\""
   ```

5. If needed, replay transactions from logs (not currently implemented)

### Scenario 4: Region Failure
**Severity**: Catastrophic
**Impact**: Complete outage
**RTO**: < 24 hours

**Recovery Steps**:
1. Activate cross-region recovery (if configured)
   - Currently NOT configured
   - See "Future Improvements" section

2. If cross-region not available:
   - Create new VM in different region
   - Restore from latest snapshot (may have latency)
   - Update DNS to point to new region
   - Notify users of extended downtime

## Automated Restoration Script

### Location
`/home/dylee/backstage/scripts/restore-surrealdb.sh`

### Usage
```bash
# Restore from latest snapshot
./restore-surrealdb.sh

# Restore from specific snapshot
./restore-surrealdb.sh --snapshot <SNAPSHOT_NAME>

# Dry run (show what would be done)
./restore-surrealdb.sh --dry-run

# Skip VM creation (use if VM already exists)
./restore-surrealdb.sh --skip-vm
```

### What the Script Does
1. Finds the latest snapshot (or uses specified one)
2. Stops existing VM if running
3. Creates new disk from snapshot
4. Creates/restores VM with new disk
5. Starts SurrealDB container
6. Verifies database connectivity
7. Verifies database data
8. Cleans up old snapshots (> 30 days)

## Manual Restoration (Fallback)

If automated script fails, follow these manual steps:

1. **Create new disk from snapshot**
   ```bash
   SNAPSHOT_NAME="<SNAPSHOT_NAME>"
   NEW_DISK="surrealvm-manual-restore-$(date +%Y%m%d-%H%M%S)"
   
   gcloud compute disks create "$NEW_DISK" \
     --source-snapshot="$SNAPSHOT_NAME" \
     --zone=us-central1-a \
     --type=pd-balanced
   ```

2. **Stop existing VM**
   ```bash
   gcloud compute instances stop surrealvm --zone=us-central1-a
   ```

3. **Delete old disk** (optional, backup first)
   ```bash
   gcloud compute snapshots create "surrealvm-backup-$(date +%Y%m%d-%H%M%S)" \
     --source-disk=surrealvm \
     --zone=us-central1-a
   
   gcloud compute disks delete surrealvm --zone=us-central1-a
   ```

4. **Create new VM**
   ```bash
   gcloud compute instances create surrealvm \
     --zone=us-central1-a \
     --machine-type=e2-medium \
     --network-interface=network-tier=PREMIUM \
     --create-disk=auto-delete=yes,boot=yes,device-name="$NEW_DISK",mode=rw,name="$NEW_DISK"
   ```

5. **Start SurrealDB container**
   ```bash
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="docker run -d \
       --name surrealdb \
       --restart=always \
       -p 8000:8000 \
       -v /data:/data \
       surrealdb/surrealdb:latest start \
       --user root \
       --pass root \
       --bind 0.0.0.0:8000 \
       file:///data"
   ```

6. **Verify database** (use SSH, VM is internal-only)
   ```bash
   gcloud compute ssh surrealvm --zone=us-central1-a \
     --command="curl http://localhost:8000/health"
   ```

## Verification Checklist

After restoration, verify:

- [ ] VM is running
  ```bash
  gcloud compute instances describe surrealvm --zone=us-central1-a --format="value(status)"
  ```

- [ ] SurrealDB container is running
  ```bash
  gcloud compute ssh surrealvm --zone=us-central1-a --command="docker ps"
  ```

- [ ] SurrealDB is responding (use SSH, VM is internal-only)
  ```bash
  gcloud compute ssh surrealvm --zone=us-central1-a \
    --command="curl http://localhost:8000/health"
  ```

- [ ] Database is accessible (use SSH, VM is internal-only)
  ```bash
  gcloud compute ssh surrealvm --zone=us-central1-a \
    --command="curl http://localhost:8000/sql \
      -H 'NS: partyscene' \
      -H 'DB: partyscene' \
      -d 'INFO FOR DB;'"
  ```

- [ ] Record counts are reasonable (use SSH, VM is internal-only)
  ```bash
  gcloud compute ssh surrealvm --zone=us-central1-a \
    --command="curl http://localhost:8000/sql \
      -H 'NS: partyscene' \
      -H 'DB: partyscene' \
      -d 'SELECT count() FROM users GROUP ALL;'"
  ```

- [ ] Microservices can connect
  ```bash
  kubectl logs deploy/microserv.users --tail=50
  kubectl logs deploy/microserv.events --tail=50
  kubectl logs deploy/microserv.posts --tail=50
  ```

- [ ] Application is functional
  - Test user login
  - Test event creation
  - Test post creation

## Escalation Procedures

### Level 1: Automated Recovery
- Trigger: Automated monitoring alert
- Action: Run automated restoration script
- Owner: DevOps / On-call engineer
- Timeline: < 2 hours

### Level 2: Manual Recovery
- Trigger: Automated recovery fails
- Action: Manual restoration procedure
- Owner: Senior DevOps / DBA
- Timeline: < 8 hours

### Level 3: Major Incident
- Trigger: Manual recovery fails or data corruption detected
- Action: Declare major incident, assemble war room
- Owner: CTO / VP Engineering
- Timeline: As long as needed

## Contact Information

### Primary
- **DevOps**: [EMAIL]
- **DBA**: [EMAIL]
- **CTO**: [EMAIL]

### Escalation
- **VP Engineering**: [EMAIL]
- **CEO**: [EMAIL] (catastrophic only)

## Testing Procedures

### Monthly
- Review snapshot retention policy
- Verify snapshot creation schedule
- Check backup validation job logs

### Quarterly
- Full disaster recovery drill (non-production)
- Update this document with lessons learned
- Review and update contact information

### Annually
- Cross-region recovery test (if configured)
- Review RTO/RPO targets
- Cost optimization review

## Known Issues & Limitations

1. **Docker Volume Data**
   - Issue: Snapshots may not include Docker volume data
   - Workaround: Manual copy from old disk if needed
   - Future: Include Docker volume in snapshot or use separate backup

2. **No Point-in-Time Recovery**
   - Issue: Can only restore to snapshot points
   - Workaround: Choose snapshot closest to desired time
   - Future: Enable SurrealDB WAL archiving

3. **No Cross-Region Replication**
   - Issue: Single region dependency
   - Workaround: Manual snapshot copy to secondary region
   - Future: Automated cross-region replication

4. **No Automated Failover**
   - Issue: Manual intervention required
   - Workaround: Use automated restoration script
   - Future: Implement automatic failover logic

5. **Logical Exports Blocked by IAM Authentication**
   - Issue: SurrealDB HTTP API returns 403 Forbidden with IAM error
   - Root cause: SurrealDB v2.x IAM authentication is configured and blocking access regardless of credentials
   - Correct credentials: Username: root, Password: rootrm
   - Container credentials: root/rootrm (corrected)
   - Status: IAM permissions block access even with correct credentials
   - Prerequisite: Disable IAM authentication or configure proper IAM permissions before implementing logical exports
   - Future: Implement daily logical exports to GCS as complement to disk snapshots

## Restoration Best Practices

### Snapshot Selection
- **Use `surrealvm-us-central1-a-*` snapshots** for actual data (58MB - 96MB)
- **Avoid `surrealvm-20250402--us-central1-a-*` snapshots** (mostly 0 bytes or very small, no data)
- **Check snapshot storage bytes** before restoring to identify which have data
- **Last snapshot with data**: April 25, 2026 (70MB) - April 26-27 snapshots have 0 bytes

### Data Location
- Database data is in Docker volume: `/var/lib/docker/volumes/mydata/_data/mydatabase.db`
- NOT in `/data` directory on the host
- Container mounts: `-v /var/lib/docker/volumes/mydata/_data/mydatabase.db:/data`

### Permission Fix Workflow
**Required after every snapshot restore** - GCP snapshots preserve filesystem ownership as-is. The restored disk has files owned by UID from the snapshot, but the SurrealDB Docker image runs as UID 65532. This causes permission errors on startup.

```bash
# Step 1: Check what user the container runs as
docker inspect surrealdb --format '{{.Config.User}}'  # Returns: 65532

# Step 2: Check actual ownership of the data directory
ls -lan /var/lib/docker/volumes/mydata/_data/mydatabase.db/ | head -5
# Output shows ownership (e.g., 0:0 for root, or other UID)

# Step 3: Fix ownership to match the container's UID
sudo chown -R 65532:65532 /var/lib/docker/volumes/mydata/_data/mydatabase.db

# Step 4: Start container
docker run -d --name surrealdb --restart=always -p 8000:8000 \
  -v /var/lib/docker/volumes/mydata/_data/mydatabase.db:/data \
  surrealdb/surrealdb:latest start \
  --user root --pass rootrm --bind 0.0.0.0:8000 rocksdb:///data

# Step 5: Verify via logs
docker logs surrealdb --tail-5
# Should show "Started web server on 0.0.0.0:8000" with no ERROR
```

**Key gotcha:** Don't assume the container runs as root or 1000 — always confirm with `docker inspect --format '{{.Config.User}}'` before chowning. The SurrealDB Docker image runs as UID 65532 by default.

### Why Some Snapshots Have 0 Bytes
- Taken when SurrealDB container wasn't running
- Docker volume was empty (fresh install)
- Snapshot taken before data was written to database
- Snapshots after April 25, 2026 have 0 bytes (container likely stopped)

## Future Improvements

### Priority 1 (Next Quarter)
- [ ] Fix SurrealDB IAM authentication to enable logical exports
- [ ] Include Docker volume data in snapshot process (fix April 26-27 0-byte issue)
- [ ] Implement point-in-time recovery with WAL archiving
- [ ] Add automated failover detection and switching

### Priority 2 (Next 6 Months)
- [ ] Implement daily logical exports to GCS (complement disk snapshots)
- [ ] Cross-region snapshot replication
- [ ] Multi-region active-passive setup
- [ ] Read replicas for query offloading

### Priority 3 (Next Year)
- [ ] SurrealDB clustering for high availability
- [ ] Automated failover with zero downtime
- [ ] Disaster recovery as code (Terraform)

## Appendix: Useful Commands

### Snapshot Management
```bash
# List all snapshots
gcloud compute snapshots list --format="table(name,createTime,storageBytes)"

# List recent snapshots
gcloud compute snapshots list \
  --filter="creationTime>'$(date -d '7 days ago' +%Y-%m-%d)'" \
  --format="table(name,createTime)"

# Delete old snapshots
gcloud compute snapshots list \
  --filter="creationTime<'$(date -d '30 days ago' +%Y-%m-%d)'" \
  --format="value(name)" \
  | xargs -I {} gcloud compute snapshots delete {} --quiet
```

### VM Management
```bash
# Check VM status
gcloud compute instances describe surrealvm --zone=us-central1-a --format="value(status)"

# Stop VM
gcloud compute instances stop surrealvm --zone=us-central1-a

# Start VM
gcloud compute instances start surrealvm --zone=us-central1-a

# SSH into VM
gcloud compute ssh surrealvm --zone=us-central1-a

# View serial console
gcloud compute instances get-serial-port-output surrealvm --zone=us-central1-a
```

### Docker Container Management
```bash
# List containers
gcloud compute ssh surrealvm --zone=us-central1-a --command="docker ps -a"

# View logs
gcloud compute ssh surrealvm --zone=us-central1-a --command="docker logs surrealdb"

# Restart container
gcloud compute ssh surrealvm --zone=us-central1-a --command="docker restart surrealdb"

# Stop container
gcloud compute ssh surrealvm --zone=us-central1-a --command="docker stop surrealdb"
```

### Database Verification
```bash
# Health check (use SSH, VM is internal-only)
gcloud compute ssh surrealvm --zone=us-central1-a \
  --command="curl http://localhost:8000/health"

# Database info (use SSH, VM is internal-only)
gcloud compute ssh surrealvm --zone=us-central1-a \
  --command="curl http://localhost:8000/sql \
    -H 'NS: partyscene' \
    -H 'DB: partyscene' \
    -d 'INFO FOR DB;'"

# Record count (use SSH, VM is internal-only)
gcloud compute ssh surrealvm --zone=us-central1-a \
  --command="curl http://localhost:8000/sql \
    -H 'NS: partyscene' \
    -H 'DB: partyscene' \
    -d 'SELECT count() FROM users GROUP ALL;'"

# Test query (use SSH, VM is internal-only)
gcloud compute ssh surrealvm --zone=us-central1-a \
  --command="curl http://localhost:8000/sql \
    -H 'NS: partyscene' \
    -H 'DB: partyscene' \
    -d 'SELECT * FROM users LIMIT 1;'"
```

## Document Version

- **Version**: 1.0
- **Created**: 2026-04-28
- **Last Updated**: 2026-04-28
- **Author**: Cascade AI
- **Next Review**: 2026-07-28
