#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(id -un)"
USER_HOME="$(getent passwd "${CURRENT_USER}" | cut -d: -f6)"
DESKTOP_DIR="${USER_HOME}/Desktop"
SHORTCUT_PATH="${DESKTOP_DIR}/AquaBrain.desktop"
KIOSK_SCRIPT="${REPO_DIR}/webapp/aquaview/start_kiosk.sh"

if [[ -z "${USER_HOME}" ]]; then
  echo "Could not determine home directory for ${CURRENT_USER}" >&2
  exit 1
fi

mkdir -p "${DESKTOP_DIR}"

cat >"${SHORTCUT_PATH}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=AquaBrain
Comment=Open AquaView in Chromium kiosk mode
Exec=/bin/bash ${KIOSK_SCRIPT}
Icon=web-browser
Terminal=false
Categories=Utility;
EOF

chmod +x "${SHORTCUT_PATH}"

echo "Created desktop shortcut at ${SHORTCUT_PATH}"
echo "If your desktop requires trusted launchers, mark the shortcut as trusted in the file manager."
