#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENSOR_INSTALL_SCRIPT="${REPO_DIR}/python/server/install_sensor_service.sh"
AQUAVIEW_INSTALL_SCRIPT="${REPO_DIR}/webapp/aquaview/install_aquaview_services.sh"
DESKTOP_SHORTCUT_INSTALL_SCRIPT="${REPO_DIR}/install_desktop_shortcut.sh"
DESKTOP_LAUNCH_SCRIPT="${REPO_DIR}/launch_aquabrain_kiosk.sh"

log() {
  printf '\n==> %s\n' "$1"
}

run_step() {
  local description="$1"
  shift
  log "$description"
  "$@"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Missing required file: ${path}" >&2
    exit 1
  fi
}

print_service_summary() {
  local service_name="$1"
  log "Checking ${service_name}"
  systemctl --no-pager --full status "${service_name}" || true
}

log "Starting AquaBrain installation"
echo "Repository directory: ${REPO_DIR}"
echo "This installer will:"
echo "1. Verify that the component installers exist."
echo "2. Run the sensor service installer."
echo "3. Run the AquaView web app and kiosk installers."
echo "4. Create an AquaBrain shortcut on the desktop."
echo "5. Check that the systemd services were created and started."
echo "6. Print useful follow-up commands if something needs attention."

require_file "${SENSOR_INSTALL_SCRIPT}"
require_file "${AQUAVIEW_INSTALL_SCRIPT}"
require_file "${DESKTOP_SHORTCUT_INSTALL_SCRIPT}"
require_file "${DESKTOP_LAUNCH_SCRIPT}"

chmod +x "${SENSOR_INSTALL_SCRIPT}" "${AQUAVIEW_INSTALL_SCRIPT}" "${DESKTOP_SHORTCUT_INSTALL_SCRIPT}" "${DESKTOP_LAUNCH_SCRIPT}"

run_step \
  "Installing the MQTT sensor publisher service from python/server/install_sensor_service.sh" \
  "${SENSOR_INSTALL_SCRIPT}"

run_step \
  "Installing the AquaView web app and kiosk services from webapp/aquaview/install_aquaview_services.sh" \
  "${AQUAVIEW_INSTALL_SCRIPT}"

run_step \
  "Creating an AquaBrain desktop shortcut from install_desktop_shortcut.sh" \
  "${DESKTOP_SHORTCUT_INSTALL_SCRIPT}"

log "Running post-install checks"
for service in aquabrain-sensors.service aquaview.service aquaview-kiosk.service; do
  if systemctl is-enabled "${service}" >/dev/null 2>&1; then
    echo "${service}: enabled"
  else
    echo "${service}: not enabled"
  fi

  if systemctl is-active "${service}" >/dev/null 2>&1; then
    echo "${service}: active"
  else
    echo "${service}: not active"
  fi
done

print_service_summary "aquabrain-sensors.service"
print_service_summary "aquaview.service"
print_service_summary "aquaview-kiosk.service"

log "Installation finished"
echo "If all three services show as active, AquaBrain is installed."
echo "Useful commands:"
echo "  systemctl status aquabrain-sensors.service"
echo "  systemctl status aquaview.service"
echo "  systemctl status aquaview-kiosk.service"
echo "  journalctl -u aquabrain-sensors.service -f"
echo "  journalctl -u aquaview.service -f"
echo "  journalctl -u aquaview-kiosk.service -f"
