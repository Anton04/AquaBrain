# Sensor MQTT Publisher

`publish_sensors_mqtt.py` reads local temperatures on a Raspberry Pi and publishes them to a local MQTT broker.

Published topics:

- `1wire/<sensor_type>/<sensor_id>`
- `internal/cpu-temp`

Payload format:

```json
{"time":1712419200,"temperature_c":24.875}
```

Behavior:

- Publishes with MQTT retain enabled.
- Publishes immediately on process start.
- Publishes again when temperature changes by more than `0.125 C`.
- Publishes at least once per hour even if the value does not change.

## Setup

Create a virtual environment and install the dependency:

```bash
cd /home/anton/server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install paho-mqtt
```

Run manually:

```bash
/home/anton/server/.venv/bin/python /home/anton/server/python/publish_sensors_mqtt.py
```

## Install As Service

Use the installation script:

```bash
cd /home/anton/server
chmod +x python/install_sensor_service.sh
./python/install_sensor_service.sh
```

This creates `aquabrain-sensors.service`, enables it at boot, and starts it immediately.

Useful commands:

```bash
sudo systemctl restart aquabrain-sensors.service
systemctl status aquabrain-sensors.service
journalctl -u aquabrain-sensors.service -f
```
