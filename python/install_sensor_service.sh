#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="aquabrain-sensors.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_DIR}/.venv/bin/python"
SCRIPT_PATH="${SCRIPT_DIR}/publish_sensors_mqtt.py"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
CURRENT_USER="$(id -un)"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing virtualenv python at ${PYTHON_BIN}" >&2
  echo "Create it first with: python3 -m venv ${REPO_DIR}/.venv" >&2
  exit 1
fi

if [[ ! -f "${SCRIPT_PATH}" ]]; then
  echo "Missing script at ${SCRIPT_PATH}" >&2
  exit 1
fi

sudo tee "${SERVICE_PATH}" >/dev/null <<EOF
[Unit]
Description=AquaBrain Sensor MQTT Publisher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${PYTHON_BIN} ${SCRIPT_PATH}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "Installed and started ${SERVICE_NAME}"
echo "Check status with: systemctl status ${SERVICE_NAME}"
