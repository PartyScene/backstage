#!/usr/bin/env bash
# SurrealDB Backup & Restore — Manual Tool
#
# For automated periodic backups use the Kubernetes CronJob:
#   k8s/surrealdb-logical-backup-cronjob.yaml  (runs twice daily via GKE)
#
# This script is for ad-hoc / one-off operations:
#   backup  — runs `surreal export` inside the Docker container on surrealvm,
#             uploads the .surql dump to GCS.
#   restore — downloads a .surql dump from GCS (latest or specified),
#             runs `surreal import` inside the container.
#
# The VM surrealvm has no external IP — all remote commands use gcloud compute ssh.
#
# Usage:
#   ./export-surrealdb.sh backup
#   ./export-surrealdb.sh backup --output gs://bucket/prefix/
#   ./export-surrealdb.sh restore
#   ./export-surrealdb.sh restore --file gs://bucket/prefix/partyscene-20260503-161042.surql
#   ./export-surrealdb.sh backup --dry-run
#   ./export-surrealdb.sh restore --dry-run

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
GCS_PREFIX="gs://partyscene-441317-backups/surreal-exports"
# ─────────────────────────────────────────────────────────────────────────────

TIMESTAMP="$(date -u '+%Y%m%d-%H%M%S')"
DRY_RUN=false
MODE=""
CUSTOM_OUTPUT=""
RESTORE_FILE=""

log() { echo "[$(date -u '+%H:%M:%S') UTC] $*"; }
die() { log "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Usage:
  $0 backup   [--output gs://bucket/prefix/] [--dry-run]
  $0 restore  [--file gs://bucket/file.surql] [--dry-run]
EOF
    exit 1
}

[[ $# -gt 0 ]] || usage
MODE="$1"; shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output)   CUSTOM_OUTPUT="${2%/}"; shift 2 ;;
        --file)     RESTORE_FILE="$2";      shift 2 ;;
        --dry-run)  DRY_RUN=true;           shift   ;;
        --help)     usage ;;
        *) echo "Unknown flag: $1"; usage ;;
    esac
done

# ── Shared: verify container is running ───────────────────────────────────────
check_container() {
    log "Checking container health on ${VM}..."
    local running
    running=$(gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet \
        --command="docker inspect --format='{{.State.Running}}' ${CONTAINER} 2>/dev/null || echo false" \
        2>/dev/null | tr -d '[:space:]')
    [[ "$running" == "true" ]] || die "Container '${CONTAINER}' is not running on ${VM}"
    log "Container is running."
}

# ── Backup ────────────────────────────────────────────────────────────────────
do_backup() {
    local prefix="${CUSTOM_OUTPUT:-$GCS_PREFIX}"
    local gcs_file="${prefix}/partyscene-${TIMESTAMP}.surql"
    local remote_dump="/tmp/surreal-export-${TIMESTAMP}.surql"

    log "SurrealDB backup"
    log "  VM         : ${VM} (${ZONE})"
    log "  NS/DB      : ${NS}/${DB}"
    log "  Destination: ${gcs_file}"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "DRY RUN — no changes made."; return
    fi

    check_container

    log "Running surreal export inside container..."
    gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
        docker exec ${CONTAINER} surreal export \
            --conn ${SURREAL_ENDPOINT} \
            --user ${SURREAL_USER} \
            --pass ${SURREAL_PASS} \
            --ns ${NS} \
            --db ${DB} \
            /tmp/export.surql \
        && docker cp ${CONTAINER}:/tmp/export.surql ${remote_dump} \
        && docker exec ${CONTAINER} rm -f /tmp/export.surql \
        && echo export_ok
    " | grep -q "export_ok" || die "surreal export failed"

    log "Uploading to GCS..."
    gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
        gsutil -q cp ${remote_dump} ${gcs_file} \
        && rm -f ${remote_dump} \
        && echo upload_ok
    " | grep -q "upload_ok" || die "GCS upload failed"

    log "Verifying..."
    local size
    size=$(gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet \
        --command="gsutil du -s ${gcs_file} | awk '{print \$1}'" 2>/dev/null | tr -d '[:space:]')
    [[ -n "$size" && "$size" != "0" ]] || die "Verification failed — file empty or missing at ${gcs_file}"

    log "Backup complete: ${gcs_file} (${size} bytes)"
}

# ── Restore ───────────────────────────────────────────────────────────────────
do_restore() {
    local gcs_file="$RESTORE_FILE"

    if [[ -z "$gcs_file" ]]; then
        log "No --file specified, finding latest export in ${GCS_PREFIX}..."
        gcs_file=$(gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet \
            --command="gsutil ls '${GCS_PREFIX}/*.surql' 2>/dev/null | sort | tail -1" \
            2>/dev/null | tr -d '[:space:]')
        [[ -n "$gcs_file" ]] || die "No exports found in ${GCS_PREFIX}"
        log "Latest export: ${gcs_file}"
    fi

    local remote_dump="/tmp/surreal-restore-${TIMESTAMP}.surql"

    log "SurrealDB restore"
    log "  VM     : ${VM} (${ZONE})"
    log "  NS/DB  : ${NS}/${DB}"
    log "  Source : ${gcs_file}"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "DRY RUN — no changes made."; return
    fi

    check_container

    log "Downloading dump from GCS..."
    gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
        gsutil -q cp ${gcs_file} ${remote_dump} \
        && echo download_ok
    " | grep -q "download_ok" || die "GCS download failed"

    log "Running surreal import inside container..."
    gcloud compute ssh "${VM}" --zone="${ZONE}" --quiet --command="
        docker cp ${remote_dump} ${CONTAINER}:/tmp/restore.surql \
        && docker exec ${CONTAINER} surreal import \
            --conn ${SURREAL_ENDPOINT} \
            --user ${SURREAL_USER} \
            --pass ${SURREAL_PASS} \
            --ns ${NS} \
            --db ${DB} \
            /tmp/restore.surql \
        && docker exec ${CONTAINER} rm -f /tmp/restore.surql \
        && rm -f ${remote_dump} \
        && echo import_ok
    " | grep -q "import_ok" || die "surreal import failed"

    log "Restore complete from: ${gcs_file}"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "$MODE" in
    backup)  do_backup  ;;
    restore) do_restore ;;
    *) echo "Unknown mode: ${MODE}"; usage ;;
esac
