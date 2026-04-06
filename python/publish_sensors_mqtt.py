#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print(
        "[ERROR] Missing dependency: paho-mqtt\n"
        "Install it with: pip install paho-mqtt",
        file=sys.stderr,
    )
    sys.exit(1)


W1_BASE_PATH = Path("/sys/bus/w1/devices")
CPU_TEMP_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
FAMILY_NAMES = {
    "10": "ds18s20",
    "22": "ds1822",
    "28": "ds18b20",
    "3b": "ds1825",
}
MIN_PUBLISH_INTERVAL_SECONDS = 3600.0
MIN_TEMP_CHANGE_C = 0.125
CPU_TEMP_TOPIC = "internal/cpu-temp"


@dataclass
class SensorState:
    last_temperature_c: float | None = None
    last_publish_time: float = 0.0


def debug(message: str) -> None:
    print(f"[DEBUG] {message}", flush=True)


def info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def get_sensor_dirs() -> list[Path]:
    if not W1_BASE_PATH.exists():
        error(f"1-Wire base path not found: {W1_BASE_PATH}")
        return []

    sensors = [
        path
        for path in W1_BASE_PATH.iterdir()
        if path.is_dir() and path.name != "w1_bus_master1" and (path / "w1_slave").exists()
    ]
    sensors.sort()
    debug(f"Discovered 1-Wire sensors: {[sensor.name for sensor in sensors]}")
    return sensors


def get_sensor_type(sensor_id: str) -> str:
    family_code = sensor_id.split("-", 1)[0].lower()
    return FAMILY_NAMES.get(family_code, family_code)


def read_temperature(sensor_file: Path) -> float:
    raw = sensor_file.read_text()
    debug(f"Raw data from {sensor_file}:\n{raw.rstrip()}")

    lines = raw.strip().splitlines()
    if len(lines) < 2:
        raise ValueError("Incomplete sensor payload")

    if not lines[0].strip().endswith("YES"):
        raise ValueError("CRC check failed")

    marker = "t="
    if marker not in lines[1]:
        raise ValueError("Temperature marker missing")

    temp_raw = lines[1].split(marker, 1)[1]
    debug(f"Parsed raw temperature value: {temp_raw}")
    return float(temp_raw) / 1000.0


def read_cpu_temperature() -> float:
    if not CPU_TEMP_PATH.exists():
        raise FileNotFoundError(f"CPU temperature path not found: {CPU_TEMP_PATH}")

    temp_raw = CPU_TEMP_PATH.read_text().strip()
    debug(f"Raw CPU temperature value: {temp_raw}")
    return float(temp_raw) / 1000.0


def build_client(host: str, port: int) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    debug(f"Connecting to MQTT broker at {host}:{port}")
    client.connect(host, port, keepalive=60)
    client.loop_start()
    return client


def should_publish(
    state: SensorState,
    temperature_c: float,
    now: float,
    min_publish_interval: float,
    min_temp_change_c: float,
) -> bool:
    if state.last_temperature_c is None:
        return True

    if abs(temperature_c - state.last_temperature_c) > min_temp_change_c:
        return True

    return (now - state.last_publish_time) >= min_publish_interval


def build_payload(temperature_c: float, now: int) -> str:
    return json.dumps(
        {
            "time": now,
            "temperature_c": round(temperature_c, 3),
        },
        separators=(",", ":"),
    )


def publish_temperature(
    client: mqtt.Client,
    topic: str,
    temperature_c: float,
    sensor_states: dict[str, SensorState],
    min_publish_interval: float,
    min_temp_change_c: float,
) -> None:
    now = time.time()
    state = sensor_states.setdefault(topic, SensorState())

    if not should_publish(
        state,
        temperature_c,
        now,
        min_publish_interval,
        min_temp_change_c,
    ):
        debug(
            f"Skipping publish for {topic}; change is <= {min_temp_change_c:.3f} C "
            f"(current {temperature_c:.3f}, previous {state.last_temperature_c:.3f})"
        )
        return

    payload = build_payload(temperature_c, int(now))
    debug(f"Publishing payload {payload} to topic {topic} with retain=true")

    message = client.publish(topic, payload=payload, qos=0, retain=True)
    message.wait_for_publish()
    if message.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT publish failed with rc={message.rc}")

    state.last_temperature_c = temperature_c
    state.last_publish_time = now
    info(f"Published {payload} to {topic}")


def publish_1wire_sensors(
    client: mqtt.Client,
    sensor_states: dict[str, SensorState],
    min_publish_interval: float,
    min_temp_change_c: float,
) -> None:
    sensors = get_sensor_dirs()
    if not sensors:
        error("No 1-Wire sensors found")
        return

    for sensor_dir in sensors:
        sensor_id = sensor_dir.name
        sensor_type = get_sensor_type(sensor_id)
        topic = f"1wire/{sensor_type}/{sensor_id}"
        sensor_file = sensor_dir / "w1_slave"

        try:
            temperature_c = read_temperature(sensor_file)
            publish_temperature(
                client,
                topic,
                temperature_c,
                sensor_states,
                min_publish_interval,
                min_temp_change_c,
            )
        except Exception as exc:
            error(f"{sensor_id}: {exc}")


def publish_cpu_temperature(
    client: mqtt.Client,
    sensor_states: dict[str, SensorState],
    min_publish_interval: float,
    min_temp_change_c: float,
) -> None:
    try:
        temperature_c = read_cpu_temperature()
        publish_temperature(
            client,
            CPU_TEMP_TOPIC,
            temperature_c,
            sensor_states,
            min_publish_interval,
            min_temp_change_c,
        )
    except Exception as exc:
        error(f"cpu-temp: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read local temperatures and publish values to a local MQTT broker."
    )
    parser.add_argument("--host", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between sensor reads",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read and publish one time, then exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = build_client(args.host, args.port)
    sensor_states: dict[str, SensorState] = {}
    try:
        while True:
            publish_1wire_sensors(
                client,
                sensor_states,
                MIN_PUBLISH_INTERVAL_SECONDS,
                MIN_TEMP_CHANGE_C,
            )
            publish_cpu_temperature(
                client,
                sensor_states,
                MIN_PUBLISH_INTERVAL_SECONDS,
                MIN_TEMP_CHANGE_C,
            )

            if args.once:
                break

            debug(f"Sleeping for {args.interval} seconds")
            time.sleep(args.interval)
    finally:
        client.loop_stop()
        client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
