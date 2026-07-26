#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(id -un)"
USER_HOME="$(getent passwd "${CURRENT_USER}" | cut -d: -f6)"
DESKTOP_DIR="${USER_HOME}/Desktop"
SHORTCUT_PATH="${DESKTOP_DIR}/AquaBrain.desktop"
LAUNCH_SCRIPT="${REPO_DIR}/launch_aquabrain_kiosk.sh"
ICON_SOURCE_PATH="${REPO_DIR}/assets/aquabrain-fish.svg"
ICON_DIR="${USER_HOME}/.local/share/icons/hicolor/scalable/apps"
ICON_TARGET_PATH="${ICON_DIR}/aquabrain-fish.svg"

if [[ -z "${USER_HOME}" ]]; then
  echo "Could not determine home directory for ${CURRENT_USER}" >&2
  exit 1
fi

mkdir -p "${DESKTOP_DIR}"
mkdir -p "${ICON_DIR}"

if [[ ! -f "${LAUNCH_SCRIPT}" ]]; then
  echo "Missing launcher script at ${LAUNCH_SCRIPT}" >&2
  exit 1
fi

if [[ ! -f "${ICON_SOURCE_PATH}" ]]; then
  echo "Missing icon source at ${ICON_SOURCE_PATH}" >&2
  exit 1
fi

chmod +x "${LAUNCH_SCRIPT}"
rm -f "${SHORTCUT_PATH}"
rm -f "${ICON_TARGET_PATH}"
cp "${ICON_SOURCE_PATH}" "${ICON_TARGET_PATH}"

cat >"${SHORTCUT_PATH}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=AquaBrain
Comment=Start AquaView kiosk via the AquaView backend service
Exec=/bin/bash ${LAUNCH_SCRIPT}
Icon=${ICON_TARGET_PATH}
Terminal=false
Categories=Utility;
EOF

chmod +x "${SHORTCUT_PATH}"

echo "Created desktop shortcut at ${SHORTCUT_PATH}"
echo "Installed icon at ${ICON_TARGET_PATH}"
echo "If your desktop requires trusted launchers, mark the shortcut as trusted in the file manager."
