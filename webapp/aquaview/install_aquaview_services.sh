#!/usr/bin/env bash
set -euo pipefail

APP_SERVICE_NAME="aquaview.service"
KIOSK_SERVICE_NAME="aquaview-kiosk.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${REPO_DIR}/.venv/bin/python"
PIP_BIN="${REPO_DIR}/.venv/bin/pip"
APP_PATH="${SCRIPT_DIR}/app.py"
KIOSK_PATH="${SCRIPT_DIR}/start_kiosk.sh"
REQUIREMENTS_PATH="${SCRIPT_DIR}/requirements.txt"
APP_SERVICE_PATH="/etc/systemd/system/${APP_SERVICE_NAME}"
KIOSK_SERVICE_PATH="/etc/systemd/system/${KIOSK_SERVICE_NAME}"
CURRENT_USER="$(id -un)"
USER_HOME="$(getent passwd "${CURRENT_USER}" | cut -d: -f6)"
DISPLAY_VALUE="${DISPLAY:-:0}"
XAUTHORITY_VALUE="${XAUTHORITY:-${USER_HOME}/.Xauthority}"

if [[ ! -f "${REQUIREMENTS_PATH}" ]]; then
  echo "Missing requirements file at ${REQUIREMENTS_PATH}" >&2
  exit 1
fi

if [[ ! -f "${APP_PATH}" ]]; then
  echo "Missing app at ${APP_PATH}" >&2
  exit 1
fi

if [[ ! -f "${KIOSK_PATH}" ]]; then
  echo "Missing kiosk script at ${KIOSK_PATH}" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Creating virtualenv at ${REPO_DIR}/.venv"
  python3 -m venv "${REPO_DIR}/.venv"
fi

"${PIP_BIN}" install --upgrade pip
"${PIP_BIN}" install -r "${REQUIREMENTS_PATH}"

chmod +x "${KIOSK_PATH}"

sudo tee "${APP_SERVICE_PATH}" >/dev/null <<EOF
[Unit]
Description=AquaView Web App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${PYTHON_BIN} ${APP_PATH}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee "${KIOSK_SERVICE_PATH}" >/dev/null <<EOF
[Unit]
Description=AquaView Chromium Kiosk
After=graphical.target ${APP_SERVICE_NAME}
Requires=${APP_SERVICE_NAME}

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=DISPLAY=${DISPLAY_VALUE}
Environment=XAUTHORITY=${XAUTHORITY_VALUE}
ExecStart=/bin/bash ${KIOSK_PATH}
Restart=always
RestartSec=10

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${APP_SERVICE_NAME}" "${KIOSK_SERVICE_NAME}"
sudo systemctl restart "${APP_SERVICE_NAME}" "${KIOSK_SERVICE_NAME}"

echo "Installed and started ${APP_SERVICE_NAME} and ${KIOSK_SERVICE_NAME}"
echo "Check app status with: systemctl status ${APP_SERVICE_NAME}"
echo "Check kiosk status with: systemctl status ${KIOSK_SERVICE_NAME}"
