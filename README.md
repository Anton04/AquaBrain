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
  Shows the fish feeder, schedule, counters, connection/clock warnings and manual feed control.

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
- lets the AquaView web app service manage the kiosk process
- creates an `AquaBrain.desktop` launcher on the current user's desktop
- installs an AquaBrain fish icon for the desktop launcher
- checks the resulting `systemd` services

## Services

The installation creates these services:

- `aquabrain-sensors.service`
- `aquaview.service`

Useful commands:

```bash
systemctl status aquabrain-sensors.service
systemctl status aquaview.service

journalctl -u aquabrain-sensors.service -f
journalctl -u aquaview.service -f
```

## Project Layout

```text
python/server/             Sensor publisher and server-side install script
webapp/aquaview/           AquaView Flask app, kiosk launcher, web install script
install_aquabrain.sh       Top-level installer for the full system
install_desktop_shortcut.sh Creates an AquaBrain desktop shortcut
launch_aquabrain_kiosk.sh  Starts the kiosk through the AquaView backend
```

## AquaView MQTT commands

The AquaView backend listens on the local AquaBrain MQTT broker:

| Topic | Payload | Purpose |
|---|---|---|
| `app/aquaview/commands/update` | Any non-retained payload | Pull the current branch with fast-forward only and restart AquaBrain |
| `app/aquaview/properties/update-result` | JSON | Retained result from the latest MQTT update request |
| `app/aquaview/events/manual-feed-requested` | JSON | Audit event for every manual-feed button request |

The update command refuses to run if the worktree is dirty, the local branch is
ahead of origin, or the branches have diverged. Never publish the update command
as a retained MQTT message.

## Fish feeder MQTT broker

AquaView uses a separate MQTT connection for the fish feeder:

- AquaBrain events and commands: `AQUAVIEW_MQTT_HOST` (default `127.0.0.1`)
- Fish feeder properties and commands: `AQUAVIEW_FEEDER_MQTT_HOST` (default `192.168.0.143`)
- Fish feeder port: `AQUAVIEW_FEEDER_MQTT_PORT` (default `1883`)
- Fish feeder ID: `AQUAVIEW_FEEDER_DEVICE_ID` (default `fishfeeder-c78f`)

After an application update, the browser detects the restarted backend through
a new application instance ID and reloads the page to fetch the new frontend.
