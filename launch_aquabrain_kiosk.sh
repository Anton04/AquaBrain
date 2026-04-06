#!/usr/bin/env bash
set -euo pipefail

BACKEND_START_URL="http://127.0.0.1:8100/api/kiosk/start"
DIRECT_LAUNCH_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/webapp/aquaview/start_kiosk.sh"

log() {
  printf '%s\n' "$1"
}

start_via_backend() {
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi

  curl \
    --silent \
    --show-error \
    --fail \
    -X POST \
    "${BACKEND_START_URL}" >/dev/null
}

if start_via_backend; then
  log "Starting AquaBrain kiosk via the local web backend..."
  exit 0
fi

log "Backend start failed; falling back to direct launcher."
exec /bin/bash "${DIRECT_LAUNCH_SCRIPT}"
