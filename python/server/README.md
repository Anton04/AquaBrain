# Sensor MQTT Publisher

`publish_sensors_mqtt.py` reads local sensor and display state on a Raspberry Pi and publishes them to a local MQTT broker.

Published topics:

- `1wire/<sensor_type>/<sensor_id>`
- `properties/cpu-temp`
- `properties/screen_active`
- `properties/last_touch_time`

Temperature payload format:

```json
{"time":1712419200,"temperature_c":24.875}
```

Boolean payload format:

```json
{"time":1712419200,"value":true}
```

Touch payload format:

```json
{"time":1712419200}
```

Behavior:

- Publishes with MQTT retain enabled.
- Publishes immediately on process start.
- Publishes again when temperature changes by more than `0.125 C`.
- Publishes at least once per hour even if the value does not change.
- Polls screen state every `0.5` seconds by default.
- Publishes `properties/last_touch_time` whenever a touch event is received from Linux input devices.

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
/home/anton/server/.venv/bin/python /home/anton/server/python/server/publish_sensors_mqtt.py
```

Adjust polling intervals if needed:

```bash
/home/anton/server/.venv/bin/python /home/anton/server/python/server/publish_sensors_mqtt.py --screen-interval 0.5 --sensor-interval 5
```

## Install As Service

Use the installation script:

```bash
cd /home/anton/server
chmod +x python/server/install_sensor_service.sh
./python/server/install_sensor_service.sh
```

This creates `aquabrain-sensors.service`, enables it at boot, and starts it immediately.

Useful commands:

```bash
sudo systemctl restart aquabrain-sensors.service
systemctl status aquabrain-sensors.service
journalctl -u aquabrain-sensors.service -f
```
