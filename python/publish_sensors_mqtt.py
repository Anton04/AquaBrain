#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import selectors
import struct
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
SCREEN_ENABLED_PATH = Path("/sys/class/drm/card0-DSI-2/enabled")
SCREEN_STATUS_PATH = Path("/sys/class/drm/card0-DSI-2/status")
FAMILY_NAMES = {
    "10": "ds18s20",
    "22": "ds1822",
    "28": "ds18b20",
    "3b": "ds1825",
}
MIN_PUBLISH_INTERVAL_SECONDS = 3600.0
MIN_TEMP_CHANGE_C = 0.125
CPU_TEMP_TOPIC = "properties/cpu-temp"
SCREEN_ACTIVE_TOPIC = "properties/screen_active"
LAST_TOUCH_TIME_TOPIC = "properties/last_touch_time"
SCREEN_POLL_INTERVAL_SECONDS = 0.5
INPUT_EVENT_FORMAT = "llHHI"
INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FORMAT)
EV_KEY = 0x01
EV_ABS = 0x03
BTN_TOUCH = 0x14A
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
TOUCH_DEVICE_KEYWORDS = ("touch", "ft5x06", "goodix", "edt-ft5x06")


@dataclass
class SensorState:
    last_temperature_c: float | None = None
    last_publish_time: float = 0.0


@dataclass
class BooleanState:
    last_value: bool | None = None


@dataclass
class TouchMonitor:
    selector: selectors.BaseSelector
    file_objects: list[object]


def debug(message: str) -> None:
    print(f"[DEBUG] {message}", flush=True)


def info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[WARN] {message}", flush=True)


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


def read_screen_active() -> bool:
    if not SCREEN_ENABLED_PATH.exists():
        raise FileNotFoundError(f"Screen enabled path not found: {SCREEN_ENABLED_PATH}")
    if not SCREEN_STATUS_PATH.exists():
        raise FileNotFoundError(f"Screen status path not found: {SCREEN_STATUS_PATH}")

    enabled = SCREEN_ENABLED_PATH.read_text().strip()
    status = SCREEN_STATUS_PATH.read_text().strip()
    debug(f"Raw screen enabled value: {enabled}")
    debug(f"Raw screen status value: {status}")

    if status != "connected":
        return False

    if enabled == "enabled":
        return True
    if enabled == "disabled":
        return False

    raise ValueError(f"Unexpected screen enabled value: {enabled}")


def find_touch_device_paths() -> list[Path]:
    proc_devices = Path("/proc/bus/input/devices")
    if not proc_devices.exists():
        warn(f"Input device listing not found: {proc_devices}")
        return []

    blocks = proc_devices.read_text().strip().split("\n\n")
    event_paths: list[Path] = []
    for block in blocks:
        lower_block = block.lower()
        if not any(keyword in lower_block for keyword in TOUCH_DEVICE_KEYWORDS):
            continue

        for line in block.splitlines():
            if not line.startswith("H: "):
                continue
            for handler in line.split():
                if handler.startswith("event"):
                    event_paths.append(Path("/dev/input") / handler)

    unique_paths = sorted({path for path in event_paths})
    debug(f"Discovered touch input devices: {[str(path) for path in unique_paths]}")
    return unique_paths


def build_touch_monitor() -> TouchMonitor | None:
    selector = selectors.DefaultSelector()
    file_objects: list[object] = []

    for path in find_touch_device_paths():
        try:
            file_obj = open(path, "rb", buffering=0)
            os.set_blocking(file_obj.fileno(), False)
            selector.register(file_obj, selectors.EVENT_READ)
            file_objects.append(file_obj)
        except OSError as exc:
            warn(f"Could not open touch device {path}: {exc}")

    if not file_objects:
        selector.close()
        warn("No readable touch input devices found; touch topic will stay inactive")
        return None

    return TouchMonitor(selector=selector, file_objects=file_objects)


def close_touch_monitor(touch_monitor: TouchMonitor | None) -> None:
    if touch_monitor is None:
        return

    for file_obj in touch_monitor.file_objects:
        try:
            touch_monitor.selector.unregister(file_obj)
        except Exception:
            pass
        file_obj.close()
    touch_monitor.selector.close()


def publish_timestamp(
    client: mqtt.Client,
    topic: str,
    timestamp: int,
) -> None:
    payload = json.dumps({"time": timestamp}, separators=(",", ":"))
    debug(f"Publishing payload {payload} to topic {topic} with retain=true")

    message = client.publish(topic, payload=payload, qos=0, retain=True)
    message.wait_for_publish()
    if message.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT publish failed with rc={message.rc}")

    info(f"Published {payload} to {topic}")


def drain_touch_events(touch_monitor: TouchMonitor | None) -> int | None:
    if touch_monitor is None:
        return None

    latest_touch_time: int | None = None
    for key, _ in touch_monitor.selector.select(timeout=0):
        file_obj = key.fileobj
        while True:
            try:
                event = file_obj.read(INPUT_EVENT_SIZE)
            except BlockingIOError:
                break

            if not event:
                break
            if len(event) < INPUT_EVENT_SIZE:
                break

            sec, usec, event_type, code, value = struct.unpack(INPUT_EVENT_FORMAT, event)
            is_touch_press = event_type == EV_KEY and code == BTN_TOUCH and value == 1
            is_touch_position = (
                event_type == EV_ABS
                and code in (ABS_X, ABS_Y, ABS_MT_POSITION_X, ABS_MT_POSITION_Y)
            )
            if is_touch_press or is_touch_position:
                latest_touch_time = sec
                debug(
                    f"Detected touch event at {sec}.{usec:06d} "
                    f"(type={event_type}, code={code}, value={value})"
                )

    return latest_touch_time


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


def publish_boolean_state(
    client: mqtt.Client,
    topic: str,
    value: bool,
    boolean_states: dict[str, BooleanState],
) -> None:
    state = boolean_states.setdefault(topic, BooleanState())
    if state.last_value is value:
        debug(f"Skipping publish for {topic}; value unchanged at {value}")
        return

    payload = json.dumps({"time": int(time.time()), "value": value}, separators=(",", ":"))
    debug(f"Publishing payload {payload} to topic {topic} with retain=true")

    message = client.publish(topic, payload=payload, qos=0, retain=True)
    message.wait_for_publish()
    if message.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT publish failed with rc={message.rc}")

    state.last_value = value
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


def publish_screen_active(
    client: mqtt.Client,
    boolean_states: dict[str, BooleanState],
) -> None:
    try:
        is_active = read_screen_active()
        publish_boolean_state(client, SCREEN_ACTIVE_TOPIC, is_active, boolean_states)
    except Exception as exc:
        error(f"screen_active: {exc}")


def publish_touch_activity(
    client: mqtt.Client,
    touch_monitor: TouchMonitor | None,
) -> None:
    try:
        latest_touch_time = drain_touch_events(touch_monitor)
        if latest_touch_time is None:
            return
        publish_timestamp(client, LAST_TOUCH_TIME_TOPIC, latest_touch_time)
    except Exception as exc:
        error(f"last_touch_time: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read local temperatures and publish values to a local MQTT broker."
    )
    parser.add_argument("--host", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--sensor-interval",
        type=float,
        default=5.0,
        help="Seconds between temperature sensor reads",
    )
    parser.add_argument(
        "--screen-interval",
        type=float,
        default=SCREEN_POLL_INTERVAL_SECONDS,
        help="Seconds between screen status checks",
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
    boolean_states: dict[str, BooleanState] = {}
    touch_monitor = build_touch_monitor()
    next_sensor_poll = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= next_sensor_poll:
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
                next_sensor_poll = now + args.sensor_interval

            publish_screen_active(client, boolean_states)
            publish_touch_activity(client, touch_monitor)

            if args.once:
                break

            debug(f"Sleeping for {args.screen_interval} seconds")
            time.sleep(args.screen_interval)
    finally:
        close_touch_monitor(touch_monitor)
        client.loop_stop()
        client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
