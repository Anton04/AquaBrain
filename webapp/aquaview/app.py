from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, jsonify, render_template, request
import paho.mqtt.client as mqtt

app = Flask(__name__)

MQTT_HOST = os.environ.get("AQUAVIEW_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("AQUAVIEW_MQTT_PORT", "1883"))

BASE_TOPIC = "app/aquaview"
VIEW_PROPERTY_TOPIC = f"{BASE_TOPIC}/properties/current-view"
VIEW_COMMAND_TOPIC = f"{BASE_TOPIC}/commands/view/set"
SCREEN_COMMAND_TOPIC = f"{BASE_TOPIC}/commands/screen/set"

CPU_TOPIC = os.environ.get("AQUAVIEW_CPU_TOPIC", "properties/cpu-temp")
ROOM_TOPIC = os.environ.get("AQUAVIEW_ROOM_TOPIC", "").strip()
AQUARIUM_TOPIC = os.environ.get("AQUAVIEW_AQUARIUM_TOPIC", "").strip()

DISPLAY_ENV = os.environ.get("AQUAVIEW_DISPLAY", ":0")
XAUTHORITY_ENV = os.environ.get("AQUAVIEW_XAUTHORITY", "/home/anton/.Xauthority")

VIEW_NAMES = ["room", "aquarium", "cpu"]


@dataclass
class AppState:
    current_view_index: int = 0
    sensor_values: dict[str, dict] = field(default_factory=dict)


state = AppState()
state_lock = threading.Lock()
mqtt_client: mqtt.Client | None = None


def debug(message: str) -> None:
    print(f"[DEBUG] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[WARN] {message}", flush=True)


def parse_temperature_payload(payload: bytes) -> dict | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if "temperature_c" not in data:
        return None

    return data


def parse_view_command(payload: bytes) -> int | None:
    text = payload.decode("utf-8", errors="ignore").strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "index" in data:
                text = str(data["index"])
            elif "view" in data:
                text = str(data["view"])
    except json.JSONDecodeError:
        pass

    if text.isdigit():
        index = int(text)
        if 0 <= index < len(VIEW_NAMES):
            return index

    lowered = text.lower()
    if lowered in VIEW_NAMES:
        return VIEW_NAMES.index(lowered)

    return None


def parse_screen_command(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="ignore").strip().lower()
    if not text:
        return None

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "state" in data:
            text = str(data["state"]).strip().lower()
    except json.JSONDecodeError:
        pass

    if text in {"on", "true", "1"}:
        return "on"
    if text in {"off", "false", "0"}:
        return "off"

    return None


def set_screen_state(command: str) -> None:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY_ENV
    env["XAUTHORITY"] = XAUTHORITY_ENV
    debug(f"Setting screen {command} via xset on display {DISPLAY_ENV}")
    subprocess.run(
        ["xset", "dpms", "force", command],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def get_ordered_1wire_topics() -> list[str]:
    with state_lock:
        topics = sorted(topic for topic in state.sensor_values if topic.startswith("1wire/"))
    return topics


def resolve_room_topic() -> str | None:
    if ROOM_TOPIC:
        return ROOM_TOPIC

    topics = get_ordered_1wire_topics()
    return topics[1] if len(topics) > 1 else None


def resolve_aquarium_topic() -> str | None:
    if AQUARIUM_TOPIC:
        return AQUARIUM_TOPIC

    topics = get_ordered_1wire_topics()
    return topics[0] if topics else None


def get_sensor_snapshot(topic: str | None) -> dict | None:
    if not topic:
        return None

    with state_lock:
        payload = state.sensor_values.get(topic)
    return payload


def build_metric(topic: str | None, fallback_status: str) -> dict:
    payload = get_sensor_snapshot(topic)
    if not payload:
        return {"value": None, "status": fallback_status, "topic": topic}

    return {
        "value": payload.get("temperature_c"),
        "status": "Live MQTT",
        "topic": topic,
    }


def publish_current_view(index: int) -> None:
    if mqtt_client is None:
        return

    payload = json.dumps(
        {
            "time": int(time.time()),
            "index": index,
            "view": VIEW_NAMES[index],
        },
        separators=(",", ":"),
    )
    debug(f"Publishing current view payload {payload} to {VIEW_PROPERTY_TOPIC}")
    mqtt_client.publish(VIEW_PROPERTY_TOPIC, payload=payload, qos=0, retain=True)


def set_current_view(index: int) -> None:
    with state_lock:
        state.current_view_index = index
    publish_current_view(index)


def on_connect(client: mqtt.Client, _userdata, _flags, reason_code, _properties=None) -> None:
    debug(f"Connected to MQTT broker with rc={reason_code}")
    subscriptions = [
        ("1wire/#", 0),
        (CPU_TOPIC, 0),
        (VIEW_COMMAND_TOPIC, 0),
        (SCREEN_COMMAND_TOPIC, 0),
    ]
    if ROOM_TOPIC:
        subscriptions.append((ROOM_TOPIC, 0))
    if AQUARIUM_TOPIC:
        subscriptions.append((AQUARIUM_TOPIC, 0))
    client.subscribe(subscriptions)
    publish_current_view(state.current_view_index)


def on_message(_client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
    topic = message.topic
    payload = message.payload
    debug(f"Received MQTT message on {topic}")

    if topic == VIEW_COMMAND_TOPIC:
        index = parse_view_command(payload)
        if index is None:
            warn(f"Ignoring invalid view command payload: {payload!r}")
            return
        set_current_view(index)
        return

    if topic == SCREEN_COMMAND_TOPIC:
        command = parse_screen_command(payload)
        if command is None:
            warn(f"Ignoring invalid screen command payload: {payload!r}")
            return
        try:
            set_screen_state(command)
        except subprocess.CalledProcessError as exc:
            warn(f"Failed to set screen {command}: {exc.stderr or exc}")
        return

    parsed = parse_temperature_payload(payload)
    if parsed is None:
        return

    with state_lock:
        state.sensor_values[topic] = parsed


def start_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    debug(f"Connecting AquaView MQTT client to {MQTT_HOST}:{MQTT_PORT}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    room_topic = resolve_room_topic()
    aquarium_topic = resolve_aquarium_topic()

    room = build_metric(room_topic, "No MQTT source")
    aquarium = build_metric(aquarium_topic, "No MQTT source")
    cpu = build_metric(CPU_TOPIC, "No MQTT source")

    with state_lock:
        current_view_index = state.current_view_index

    return jsonify(
        {
            "room": room,
            "aquarium": aquarium,
            "cpu": cpu,
            "currentView": {
                "index": current_view_index,
                "name": VIEW_NAMES[current_view_index],
            },
        }
    )


@app.post("/api/view")
def api_view():
    payload = request.get_json(silent=True) or {}
    index = payload.get("index")
    if not isinstance(index, int) or not (0 <= index < len(VIEW_NAMES)):
        return jsonify({"error": "invalid view index"}), 400

    set_current_view(index)
    return jsonify({"ok": True})


mqtt_client = start_mqtt()


if __name__ == "__main__":
    port = int(os.environ.get("AQUAVIEW_PORT", "8100"))
    app.run(host="0.0.0.0", port=port)
