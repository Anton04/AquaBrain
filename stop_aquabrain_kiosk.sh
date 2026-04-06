#!/usr/bin/env bash
set -euo pipefail

KIOSK_SERVICE_NAME="aquaview-kiosk.service"
KIOSK_URL="http://127.0.0.1:8100/"
KIOSK_USER_DATA_DIR="/tmp/chromium-aquaview"
KIOSK_LAUNCHER="webapp/aquaview/start_kiosk.sh"

log() {
  printf '%s\n' "$1"
}

stop_service_if_present() {
  if systemctl list-unit-files "${KIOSK_SERVICE_NAME}" >/dev/null 2>&1; then
    log "Stopping ${KIOSK_SERVICE_NAME} if it is running..."
    sudo systemctl stop "${KIOSK_SERVICE_NAME}" || true
  fi
}

kill_pattern() {
  local pattern="$1"
  local description="$2"

  if pgrep -af "${pattern}" >/dev/null 2>&1; then
    log "Stopping ${description}..."
    pkill -f "${pattern}" || true
  fi
}

log "Stopping AquaBrain kiosk"

stop_service_if_present
kill_pattern "${KIOSK_LAUNCHER}" "launcher script processes"
kill_pattern "${KIOSK_USER_DATA_DIR}" "Chromium kiosk processes using the AquaView profile"
kill_pattern "${KIOSK_URL}" "Chromium kiosk processes using the AquaView URL"

log "Done. Remaining matching processes:"
pgrep -af "chromium|${KIOSK_LAUNCHER}|${KIOSK_USER_DATA_DIR}|${KIOSK_URL}" || true
