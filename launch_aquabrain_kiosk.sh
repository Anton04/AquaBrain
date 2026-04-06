#!/usr/bin/env bash
set -euo pipefail

KIOSK_SERVICE_NAME="aquaview-kiosk.service"
DIRECT_LAUNCH_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/webapp/aquaview/start_kiosk.sh"

log() {
  printf '%s\n' "$1"
}

restart_via_service() {
  if command -v pkexec >/dev/null 2>&1; then
    pkexec /bin/systemctl restart "${KIOSK_SERVICE_NAME}"
    return 0
  fi

  sudo systemctl restart "${KIOSK_SERVICE_NAME}"
}

if systemctl list-unit-files "${KIOSK_SERVICE_NAME}" >/dev/null 2>&1; then
  log "Starting AquaBrain kiosk via ${KIOSK_SERVICE_NAME}..."
  restart_via_service
  exit 0
fi

log "Kiosk service not installed; falling back to direct launcher."
exec /bin/bash "${DIRECT_LAUNCH_SCRIPT}"
