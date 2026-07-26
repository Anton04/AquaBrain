#!/usr/bin/env bash
set -euo pipefail

BACKEND_STOP_URL="http://127.0.0.1:8100/api/kiosk/stop"

log() {
  printf '%s\n' "$1"
}

stop_via_backend() {
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi

  curl \
    --silent \
    --show-error \
    --fail \
    -X POST \
    "${BACKEND_STOP_URL}" >/dev/null
}

log "Stopping AquaBrain kiosk"

if stop_via_backend; then
  log "Stopping AquaBrain kiosk via the local web backend..."
  exit 0
fi

log "Backend stop failed. Check aquaview.service and try again."
exit 1
