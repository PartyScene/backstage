#!/usr/bin/env bash
# SurrealDB Logical Export Script
#
# Runs `surreal export` inside the surrealdb Docker container on the internal-only
# surrealvm VM, then uploads the .surql dump to GCS.
# All remote commands run via `gcloud compute ssh` — the VM has no external IP.
#
# Usage:
#   ./export-surrealdb.sh
#   ./export-surrealdb.sh --output gs://my-bucket/surreal-exports/
#   ./export-surrealdb.sh --dry-run
#
# Requirements (local machine):
#   gcloud CLI authenticated with compute.instances.get + compute.instances.setMetadata
#   permissions on the partyscene project.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
VM="surrealvm"
ZONE="us-central1-a"
CONTAINER="surrealdb"
NS="partyscene"
DB="partyscene"
SURREAL_USER="root"
SURREAL_PASS="rootrm"
SURREAL_ENDPOINT="http://localhost:8000"
DEFAULT_GCS_PREFIX="gs://partyscene-441317-backups/surreal-exports"
# ─────────────────────────────────────────────────────────────────────────────

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
DRY_RUN=false
GCS_PREFIX=""

usage() {
    echo "Usage: $0 [--output gs://bucket/prefix/] [--dry-run]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output)   GCS_PREFIX="${2%/}"; shift 2 ;;
        --dry-run)  DRY_RUN=true;        shift   ;;
        --help)     usage ;;
        *) echo "Unknown flag: $1"; usage ;;
    esac
done

GCS_PREFIX="${GCS_PREFIX:-$DEFAULT_GCS_PREFIX}"
GCS_FILE="${GCS_PREFIX}/partyscene-${TIMESTAMP}.surql"

log() { echo "[$(date -u +%T UTC)] $*"; }
die() { log "ERROR: $*"; exit 1; }

log "SurrealDB logical export"
log "  VM        : ${VM} (${ZONE})"
log "  Container : ${CONTAINER}"
log "  NS/DB     : ${NS}/${DB}"
log "  Destination: ${GCS_FILE}"

if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY RUN — no changes made."
    exit 0
fi

# ── 1. Verify the container is running ────────────────────────────────────────
log "Checking container health..."
RUNNING=$(gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet \
    --command="docker inspect --format='{{.State.Running}}' ${CONTAINER} 2>/dev/null || echo false")
[[ "$RUNNING" == "true" ]] || die "Container '${CONTAINER}' is not running on ${VM}"

# ── 2. Export inside the container ────────────────────────────────────────────
# `surreal export` is the SurrealDB CLI native export — it connects via the
# native protocol, not the HTTP API, so the IAM 403 issue does not apply.
REMOTE_DUMP="/tmp/surreal-export-${TIMESTAMP}.surql"

log "Running surreal export..."
gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
    docker exec ${CONTAINER} surreal export \
        --conn ${SURREAL_ENDPOINT} \
        --user ${SURREAL_USER} \
        --pass ${SURREAL_PASS} \
        --ns ${NS} \
        --db ${DB} \
        /tmp/export.surql \
    && docker cp ${CONTAINER}:/tmp/export.surql ${REMOTE_DUMP} \
    && docker exec ${CONTAINER} rm -f /tmp/export.surql \
    && echo 'export_ok'
" | grep -q "export_ok" || die "surreal export failed — check VM logs"

log "Export written to ${VM}:${REMOTE_DUMP}"

# ── 3. Upload to GCS from the VM ──────────────────────────────────────────────
# Upload happens from the VM itself — gsutil is available on GCE VMs via the
# pre-installed Cloud SDK, and the VM's service account has Storage Object Admin.
log "Uploading to GCS..."
gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
    gsutil -q cp ${REMOTE_DUMP} ${GCS_FILE} \
    && rm -f ${REMOTE_DUMP} \
    && echo 'upload_ok'
" | grep -q "upload_ok" || die "GCS upload failed"

# ── 4. Verify and report ──────────────────────────────────────────────────────
log "Verifying upload..."
SIZE=$(gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet \
    --command="gsutil du -s ${GCS_FILE} | awk '{print \$1}'")

if [[ -z "$SIZE" || "$SIZE" == "0" ]]; then
    die "Upload verification failed — file is missing or empty at ${GCS_FILE}"
fi

log "Export complete."
log "  File : ${GCS_FILE}"
log "  Size : ${SIZE} bytes"
