# AquaBrain

AquaBrain is a Raspberry Pi project for aquarium monitoring and display.

The repository currently contains two main runtime parts:

- `python/server`
  Publishes local sensor state to MQTT.
  Reads 1-Wire sensors, CPU temperature, screen state, and touch activity.
- `webapp/aquaview`
  Displays the aquarium UI in a browser kiosk.
  Reads sensor values from MQTT through a local Flask backend.
  Publishes the current view and listens for MQTT commands to change view and control the screen.

## Clone

For a public clone on the Raspberry Pi:

```bash
git clone https://github.com/Anton04/AquaBrain.git
cd AquaBrain
```

This creates the directory `~/AquaBrain` if you run it from your home directory.

## Install

The simplest installation path is the top-level installer:

```bash
chmod +x install_aquabrain.sh
./install_aquabrain.sh
```

This script:

- creates `.venv` if needed
- installs Python dependencies
- installs and starts the sensor service
- installs and starts the AquaView web app service
- installs and starts the AquaView kiosk service
- creates an `AquaBrain.desktop` launcher on the current user's desktop
- installs an AquaBrain fish icon for the desktop launcher
- checks the resulting `systemd` services

## Services

The installation creates these services:

- `aquabrain-sensors.service`
- `aquaview.service`
- `aquaview-kiosk.service`

Useful commands:

```bash
systemctl status aquabrain-sensors.service
systemctl status aquaview.service
systemctl status aquaview-kiosk.service

journalctl -u aquabrain-sensors.service -f
journalctl -u aquaview.service -f
journalctl -u aquaview-kiosk.service -f
```

## Project Layout

```text
python/server/             Sensor publisher and server-side install script
webapp/aquaview/           AquaView Flask app, kiosk launcher, web install script
install_aquabrain.sh       Top-level installer for the full system
install_desktop_shortcut.sh Creates an AquaBrain desktop shortcut
launch_aquabrain_kiosk.sh  Starts the kiosk through the installed systemd service
```
