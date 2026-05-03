#!/bin/bash
# Automated SurrealDB Restoration Script
# Usage: ./restore-surrealdb.sh [--snapshot SNAPSHOT_NAME] [--dry-run]
#
# This script automates the restoration of SurrealDB from the latest snapshot
# or a specific snapshot. It handles the entire restoration process including:
# - Finding/selecting the snapshot
# - Creating a new disk from the snapshot
# - Creating/restoring the VM
# - Starting SurrealDB container
# - Verifying the restoration

set -euo pipefail

# Configuration
PROJECT_ID="partyscene-441317"
ZONE="us-central1-a"
VM_NAME="surrealvm"
DISK_NAME="surrealvm"
BACKUP_DISK_NAME="surrealvm-20250402-093916"
DOCKER_IMAGE="surrealdb/surrealdb:latest"
SURREALDB_PORT=8000
NAMESPACE="partyscene"
DATABASE="partyscene"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
SNAPSHOT_NAME=""
DRY_RUN=false
SKIP_VM=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --snapshot)
            SNAPSHOT_NAME="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-vm)
            SKIP_VM=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--snapshot SNAPSHOT_NAME] [--dry-run] [--skip-vm]"
            echo ""
            echo "Options:"
            echo "  --snapshot SNAPSHOT_NAME  Use specific snapshot instead of latest"
            echo "  --dry-run                 Show what would be done without executing"
            echo "  --skip-vm                 Skip VM creation (use if VM already exists)"
            echo "  --help                    Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

log_info "Starting SurrealDB restoration process..."
log_info "Project: $PROJECT_ID"
log_info "Zone: $ZONE"
log_info "VM: $VM_NAME"

# Find latest snapshot if not specified
if [[ -z "$SNAPSHOT_NAME" ]]; then
    log_info "Finding latest snapshot for disk $DISK_NAME..."
    SNAPSHOT_NAME=$(gcloud compute snapshots list \
        --filter="sourceDisk~$DISK_NAME AND sourceDisk!~$BACKUP_DISK_NAME" \
        --format="value(name)" \
        --sort-by="~createTime" \
        --limit=1 \
        --project="$PROJECT_ID")
    
    if [[ -z "$SNAPSHOT_NAME" ]]; then
        log_error "No snapshots found for disk $DISK_NAME"
        exit 1
    fi
    
    log_info "Latest snapshot: $SNAPSHOT_NAME"
else
    log_info "Using specified snapshot: $SNAPSHOT_NAME"
fi

# Verify snapshot exists and has data
log_info "Verifying snapshot exists and has data..."
SNAPSHOT_BYTES=$(gcloud compute snapshots describe "$SNAPSHOT_NAME" \
    --format="value(storageBytes)" \
    --project="$PROJECT_ID")

if [[ -z "$SNAPSHOT_BYTES" ]]; then
    log_error "Snapshot $SNAPSHOT_NAME not found"
    exit 1
fi

if [[ "$SNAPSHOT_BYTES" -eq 0 ]]; then
    log_error "Snapshot $SNAPSHOT_BYTES has 0 bytes (empty snapshot)"
    log_error "This snapshot contains no data and cannot be used for restoration"
    log_error "Please select a snapshot with storage_bytes > 0"
    exit 1
fi

log_info "Snapshot size: $SNAPSHOT_BYTES bytes"

# Stop existing VM if it exists
if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
    log_warn "VM $VM_NAME already exists. Stopping it..."
    if [[ "$DRY_RUN" == false ]]; then
        gcloud compute instances stop "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID"
        log_info "VM stopped"
    else
        log_info "[DRY-RUN] Would stop VM $VM_NAME"
    fi
fi

# Create new disk from snapshot
NEW_DISK_NAME="${DISK_NAME}-restore-$(date +%Y%m%d-%H%M%S)"
log_info "Creating new disk $NEW_DISK_NAME from snapshot $SNAPSHOT_NAME..."

if [[ "$DRY_RUN" == false ]]; then
    gcloud compute disks create "$NEW_DISK_NAME" \
        --source-snapshot="$SNAPSHOT_NAME" \
        --zone="$ZONE" \
        --type=pd-balanced \
        --project="$PROJECT_ID"
    log_info "Disk created successfully"
else
    log_info "[DRY-RUN] Would create disk $NEW_DISK_NAME from snapshot $SNAPSHOT_NAME"
fi

# Delete old disk (optional - comment out if you want to keep it)
if [[ "$DRY_RUN" == false ]] && [[ "$SKIP_VM" == false ]]; then
    log_warn "Deleting old disk $DISK_NAME (optional - comment out in script to keep)..."
    # gcloud compute disks delete "$DISK_NAME" --zone="$ZONE" --project="$PROJECT_ID" --quiet
    log_info "Old disk deletion skipped (commented out for safety)"
fi

# Create or restore VM
if [[ "$SKIP_VM" == false ]]; then
    log_info "Creating new VM $VM_NAME with disk $NEW_DISK_NAME..."
    
    if [[ "$DRY_RUN" == false ]]; then
        # Check if VM exists and delete it first
        if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
            log_warn "Deleting existing VM $VM_NAME..."
            gcloud compute instances delete "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --quiet
        fi
        
        # Create new VM with existing disk
        gcloud compute instances create "$VM_NAME" \
            --zone="$ZONE" \
            --machine-type=e2-medium \
            --network-interface=network-tier=PREMIUM \
            --maintenance-policy=MIGRATE \
            --provisioning-model=STANDARD \
            --scopes=https://www.googleapis.com/auth/cloud-platform \
            --disk=auto-delete=yes,boot=yes,device-name="$NEW_DISK_NAME",mode=rw,name="$NEW_DISK_NAME" \
            --project="$PROJECT_ID"
        
        log_info "VM created successfully"
    else
        log_info "[DRY-RUN] Would create VM $VM_NAME with disk $NEW_DISK_NAME"
    fi
else
    log_info "Skipping VM creation (--skip-vm flag set)"
    log_info "Attaching disk $NEW_DISK_NAME to existing VM..."
    
    if [[ "$DRY_RUN" == false ]]; then
        gcloud compute instances attach-disk "$VM_NAME" \
            --disk="$NEW_DISK_NAME" \
            --zone="$ZONE" \
            --project="$PROJECT_ID"
        log_info "Disk attached successfully"
    else
        log_info "[DRY-RUN] Would attach disk $NEW_DISK_NAME to VM $VM_NAME"
    fi
fi

# Wait for VM to be running and SSH to be available
if [[ "$DRY_RUN" == false ]] && [[ "$SKIP_VM" == false ]]; then
    log_info "Waiting for VM to be running and SSH to be available..."
    sleep 30
    # Wait for SSH to be available
    MAX_SSH_RETRIES=10
    SSH_RETRY_COUNT=0
    while [[ $SSH_RETRY_COUNT -lt $MAX_SSH_RETRIES ]]; do
        if gcloud compute ssh "$VM_NAME" \
            --zone="$ZONE" \
            --project="$PROJECT_ID" \
            --command="echo 'SSH ready'" >/dev/null 2>&1; then
            log_info "VM is running and SSH is available"
            break
        fi
        SSH_RETRY_COUNT=$((SSH_RETRY_COUNT + 1))
        log_info "Waiting for SSH... ($SSH_RETRY_COUNT/$MAX_SSH_RETRIES)"
        sleep 5
    done
    if [[ $SSH_RETRY_COUNT -eq $MAX_SSH_RETRIES ]]; then
        log_error "SSH did not become available after $MAX_SSH_RETRIES retries"
        exit 1
    fi
fi

# Start SurrealDB container
log_info "Starting SurrealDB container..."

if [[ "$DRY_RUN" == false ]]; then
    # Fix permissions on Docker volume before starting container
    log_info "Fixing permissions on Docker volume..."
    gcloud compute ssh "$VM_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT_ID" \
        --command="sudo chown -R 65532:65532 /var/lib/docker/volumes/mydata/_data/mydatabase.db"

    # Use gcloud compute ssh to start the container
    gcloud compute ssh "$VM_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT_ID" \
        --command="docker run -d \
            --name surrealdb \
            --restart=always \
            -p 8000:8000 \
            -v /var/lib/docker/volumes/mydata/_data/mydatabase.db:/data \
            surrealdb/surrealdb:latest start \
            --user root \
            --pass rootrm \
            --bind 0.0.0.0:8000 \
            rocksdb:///data"
    
    log_info "SurrealDB container started"
else
    log_info "[DRY-RUN] Would start SurrealDB container"
fi

# Wait for SurrealDB to be ready
log_info "Waiting for SurrealDB to be ready (this may take 1-2 minutes)..."

if [[ "$DRY_RUN" == false ]]; then
    # Get the internal IP of the VM (VM is only accessible internally)
    VM_IP=$(gcloud compute instances describe "$VM_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT_ID" \
        --format="value(networkInterfaces[0].networkIP)")
    
    log_info "VM internal IP: $VM_IP"
    log_info "Note: VM is only accessible internally via VPC/private network"
    
    # Wait for SurrealDB to be ready by checking docker logs
    MAX_RETRIES=30
    RETRY_COUNT=0

    while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
        # Check docker logs to see if SurrealDB started successfully
        LOGS=$(gcloud compute ssh "$VM_NAME" \
            --zone="$ZONE" \
            --project="$PROJECT_ID" \
            --command="docker logs surrealdb --tail=5" 2>/dev/null)

        if echo "$LOGS" | grep -q "Started web server"; then
            log_info "SurrealDB is ready (found 'Started web server' in logs)"
            break
        fi

        if echo "$LOGS" | grep -q "ERROR"; then
            log_error "SurrealDB encountered an error:"
            echo "$LOGS"
            break
        fi

        RETRY_COUNT=$((RETRY_COUNT + 1))
        log_info "Waiting for SurrealDB to start... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 5
    done
    
    if [[ $RETRY_COUNT -eq $MAX_RETRIES ]]; then
        log_error "SurrealDB did not become ready after $MAX_RETRIES retries"
        log_error "Check VM logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command 'docker logs surrealdb'"
        exit 1
    fi
else
    log_info "[DRY-RUN] Would wait for SurrealDB to be ready"
fi
SurrealDB Started successfully but your shit counts down: Store key in cache? (y/n, Return cancels connection, i for more info) [2m2026-04-28T19:39:16.838151Z[0m [32m INFO[0m [2msurrealdb::core::kvs::rocksdb[0m[2m:[0m Setting storage engine log level: warn
[[2m2026-04-28T19:39:16.838155Z[0m [32m INFO[0m [2msurrealdb::core::kvs::rocksdb[0m[2m:[0m Background write-ahead-log flushing: disabled
[2m2026-04-28T19:39:16.839087Z[0m [32m INFO[0m [2msurrealdb::core::kvs::ds[0m[2m:[0m Started kvs store at rocksdb:///data
Goodbye!
2m2026-04-28T19:39:16.839141Z[0m [31mERROR[0m [2msurreal::cli[0m[2m:[0m There was a problem with the database: There was a problem with a datastore transaction: IO error: While renaming a file to /data/LOG.old.1777405156838595: /data/LOG: Permission denied



Execute the permission fix workflow and retest connection
# Verify SurrealDB data
log_info "Verifying SurrealDB data..."

if [[ "$DRY_RUN" == false ]]; then
    # Check docker logs to verify SurrealDB is running
    LOGS=$(gcloud compute ssh "$VM_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT_ID" \
        --command="docker logs surrealdb --tail-5" 2>/dev/null)

    if echo "$LOGS" | grep -q "Started web server"; then
        log_info "SurrealDB verification successful (found 'Started web server' in logs)"
    else
        log_error "SurrealDB verification failed"
        log_error "Logs: $LOGS"
        exit 1
    fi
else
    log_info "[DRY-RUN] Would verify SurrealDB data"
fi

# Update Kubernetes ConfigMaps with new VM IP
log_info "Updating Kubernetes ConfigMaps with new VM IP..."

if [[ "$DRY_RUN" == false ]]; then
    # Get the internal IP of the VM
    VM_IP=$(gcloud compute instances describe "$VM_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT_ID" \
        --format="value(networkInterfaces[0].networkIP)")
    
    log_info "VM internal IP: $VM_IP"
    
    # Update all ConfigMaps with SURREAL_URI
    kubectl get configmaps -A -o jsonpath='{range .items[?(@.data.SURREAL_URI)]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' | while IFS=$'\t' read -r namespace configmap; do
        if [[ -n "$namespace" && -n "$configmap" ]]; then
            log_info "Patching ConfigMap: $namespace/$configmap"
            kubectl patch configmap "$configmap" -n "$namespace" \
                -p "{\"data\":{\"SURREAL_URI\":\"ws://$VM_IP:8000\"}}" 2>/dev/null || \
                log_error "Failed to patch $namespace/$configmap"
        fi
    done
    
    # Restart all deployments that use SurrealDB
    log_info "Restarting deployments that use SurrealDB..."
    kubectl get deployments -A -o jsonpath='{range .items[?(@.spec.template.spec.containers[*].envFrom[*].configMapRef.name)]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' | while IFS=$'\t' read -r namespace deployment; do
        if [[ -n "$namespace" && -n "$deployment" ]]; then
            log_info "Restarting deployment: $namespace/$deployment"
            kubectl rollout restart deployment "$deployment" -n "$namespace" 2>/dev/null || \
                log_error "Failed to restart $namespace/$deployment"
        fi
    done
    
    log_info "Kubernetes ConfigMaps and deployments updated successfully"
else
    log_info "[DRY-RUN] Would update Kubernetes ConfigMaps and restart deployments"
fi

# Cleanup old snapshots (optional - keep last 30 days)
log_info "Cleaning up old snapshots (older than 30 days)..."

if [[ "$DRY_RUN" == false ]]; then
    gcloud compute snapshots list \
        --filter="sourceDisk~$DISK_NAME AND creationTime<'$(date -d '30 days ago' +%Y-%m-%d)'" \
        --format="value(name)" \
        --project="$PROJECT_ID" \
        | while read -r old_snapshot; do
            if [[ -n "$old_snapshot" ]]; then
                log_info "Deleting old snapshot: $old_snapshot"
                gcloud compute snapshots delete "$old_snapshot" --project="$PROJECT_ID" --quiet
            fi
        done
    log_info "Old snapshots cleaned up"
else
    log_info "[DRY-RUN] Would clean up old snapshots"
fi

# Summary
log_info "========================================"
log_info "Restoration completed successfully!"
log_info "========================================"
log_info "Snapshot used: $SNAPSHOT_NAME"
log_info "New disk: $NEW_DISK_NAME"
log_info "VM: $VM_NAME"
log_info "Zone: $ZONE"
log_info "VM internal IP: $VM_IP"
log_info "Note: VM is only accessible internally via VPC/private network"
log_info "To verify: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command 'curl http://localhost:$SURREALDB_PORT/health'"
log_info "========================================"

if [[ "$DRY_RUN" == true ]]; then
    log_warn "This was a DRY RUN - no changes were made"
    log_info "Run without --dry-run to execute the restoration"
fi
