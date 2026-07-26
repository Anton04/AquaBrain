#!/usr/bin/env bash
set -euo pipefail

SENSOR_SERVICE_NAME="aquabrain-sensors.service"
APP_SERVICE_NAME="aquaview.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "AquaBrain update"
echo "Repository: ${SCRIPT_DIR}"
echo

cd "${SCRIPT_DIR}"

echo "Fetching and updating repository with fast-forward only..."
git pull --ff-only
echo

echo "Restarting services..."
sudo systemctl restart \
  "${SENSOR_SERVICE_NAME}" \
  "${APP_SERVICE_NAME}"
echo

echo "The AquaView service also restarts its managed Chromium kiosk."
echo

echo "Current service status:"
systemctl --no-pager --full status \
  "${SENSOR_SERVICE_NAME}" \
  "${APP_SERVICE_NAME}" || true
