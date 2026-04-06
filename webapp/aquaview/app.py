from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from flask import Flask, jsonify, render_template, request
import paho.mqtt.client as mqtt

app = Flask(__name__)

MQTT_HOST = os.environ.get("AQUAVIEW_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("AQUAVIEW_MQTT_PORT", "1883"))

BASE_TOPIC = "app/aquaview"
VIEW_PROPERTY_TOPIC = f"{BASE_TOPIC}/properties/current-view"
KIOSK_PROPERTY_TOPIC = f"{BASE_TOPIC}/properties/kiosk"
VIEW_COMMAND_TOPIC = f"{BASE_TOPIC}/commands/view/set"
SCREEN_COMMAND_TOPIC = f"{BASE_TOPIC}/commands/screen/set"
KIOSK_COMMAND_TOPIC = f"{BASE_TOPIC}/commands/kiosk/set"

CPU_TOPIC = os.environ.get("AQUAVIEW_CPU_TOPIC", "properties/cpu-temp")
ROOM_TOPIC = os.environ.get("AQUAVIEW_ROOM_TOPIC", "").strip()
AQUARIUM_TOPIC = os.environ.get("AQUAVIEW_AQUARIUM_TOPIC", "").strip()

DISPLAY_ENV = os.environ.get("AQUAVIEW_DISPLAY", ":0")
XAUTHORITY_ENV = os.environ.get("AQUAVIEW_XAUTHORITY", "/home/anton/.Xauthority")

REPO_DIR = Path(__file__).resolve().parents[2]
APP_SERVICE_NAME = "aquaview.service"
SENSOR_SERVICE_NAME = "aquabrain-sensors.service"
KIOSK_LAUNCH_SCRIPT = REPO_DIR / "webapp/aquaview/start_kiosk.sh"
KIOSK_STATE_PATH = REPO_DIR / ".aquaview-kiosk-state.json"
KIOSK_WATCHDOG_INTERVAL_SECONDS = 60.0

VIEW_NAMES = ["aquarium", "room", "cpu", "admin"]


@dataclass
class AppState:
    current_view_index: int = 0
    sensor_values: dict[str, dict] = field(default_factory=dict)
    kiosk_enabled: bool = True
    kiosk_pid: int | None = None
    kiosk_pgid: int | None = None


state = AppState()
state_lock = threading.Lock()
kiosk_control_lock = threading.Lock()
mqtt_client: mqtt.Client | None = None


def debug(message: str) -> None:
    print(f"[DEBUG] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[WARN] {message}", flush=True)


def run_command(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    debug(f"Running command: {' '.join(command)}")
    return subprocess.run(
        command,
        check=check,
        cwd=REPO_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


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


def parse_kiosk_command(payload: bytes) -> bool | None:
    text = payload.decode("utf-8", errors="ignore").strip().lower()
    if not text:
        return None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "enabled" in data:
                text = str(data["enabled"]).strip().lower()
            elif "state" in data:
                text = str(data["state"]).strip().lower()
    except json.JSONDecodeError:
        pass

    if text in {"on", "true", "1", "start", "enabled"}:
        return True
    if text in {"off", "false", "0", "stop", "disabled"}:
        return False

    return None


def set_screen_state(command: str) -> None:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY_ENV
    env["XAUTHORITY"] = XAUTHORITY_ENV
    debug(f"Setting screen {command} via xset on display {DISPLAY_ENV}")
    run_command(["xset", "dpms", "force", command], env=env)


def short_commit(commit: str | None) -> str | None:
    if not commit:
        return None
    return commit[:7]


def git_output(*args: str) -> str:
    result = run_command(["git", *args])
    return result.stdout.strip()


def get_git_status() -> dict:
    branch = git_output("rev-parse", "--abbrev-ref", "HEAD")
    local_commit = git_output("rev-parse", "HEAD")
    worktree_clean = git_output("status", "--porcelain") == ""

    try:
        run_command(["git", "fetch", "--quiet", "origin", branch])
        remote_commit = git_output("rev-parse", f"origin/{branch}")
        merge_base = git_output("merge-base", "HEAD", f"origin/{branch}")
    except subprocess.CalledProcessError as exc:
        return {
            "branch": branch,
            "localCommit": local_commit,
            "localCommitShort": short_commit(local_commit),
            "remoteCommit": None,
            "remoteCommitShort": None,
            "worktreeClean": worktree_clean,
            "updateAvailable": False,
            "state": "unknown",
            "summary": f"Kunde inte kontrollera origin/{branch}: {exc.stderr.strip() or exc}",
        }

    if local_commit == remote_commit:
        status_state = "up-to-date"
        summary = "Den här installationen är uppdaterad."
        update_available = False
    elif local_commit == merge_base:
        status_state = "behind"
        summary = "Det finns en nyare version på GitHub."
        update_available = True
    elif remote_commit == merge_base:
        status_state = "ahead"
        summary = "Den här installationen har lokala commits som inte finns på origin."
        update_available = False
    else:
        status_state = "diverged"
        summary = "Lokal branch och origin har divergerat."
        update_available = False

    if not worktree_clean:
        summary = f"{summary} Arbetskatalogen har också lokala ändringar."

    return {
        "branch": branch,
        "localCommit": local_commit,
        "localCommitShort": short_commit(local_commit),
        "remoteCommit": remote_commit,
        "remoteCommitShort": short_commit(remote_commit),
        "worktreeClean": worktree_clean,
        "updateAvailable": update_available,
        "state": status_state,
        "summary": summary,
    }


def run_sudo_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return run_command(["sudo", "-n", "systemctl", *args])


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kiosk_process_is_running(*, pid: int | None, pgid: int | None) -> bool:
    if pgid is not None and process_group_exists(pgid):
        return True
    if pid is not None and process_exists(pid):
        return True
    return False


def build_kiosk_snapshot() -> dict:
    with state_lock:
        enabled = state.kiosk_enabled
        pid = state.kiosk_pid
        pgid = state.kiosk_pgid

    running = kiosk_process_is_running(pid=pid, pgid=pgid)
    return {
        "enabled": enabled,
        "running": running,
        "pid": pid if running else None,
        "pgid": pgid if running else None,
    }


def persist_kiosk_state() -> None:
    with state_lock:
        payload = {
            "enabled": state.kiosk_enabled,
            "pid": state.kiosk_pid,
            "pgid": state.kiosk_pgid,
        }
    KIOSK_STATE_PATH.write_text(json.dumps(payload, separators=(",", ":")))


def publish_kiosk_state() -> None:
    if mqtt_client is None:
        return

    payload = json.dumps(
        {"time": int(time.time()), **build_kiosk_snapshot()},
        separators=(",", ":"),
    )
    debug(f"Publishing kiosk payload {payload} to {KIOSK_PROPERTY_TOPIC}")
    mqtt_client.publish(KIOSK_PROPERTY_TOPIC, payload=payload, qos=0, retain=True)


def load_kiosk_state() -> None:
    if not KIOSK_STATE_PATH.exists():
        persist_kiosk_state()
        return

    try:
        payload = json.loads(KIOSK_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"Failed to load kiosk state: {exc}")
        persist_kiosk_state()
        return

    with state_lock:
        state.kiosk_enabled = bool(payload.get("enabled", True))
        state.kiosk_pid = payload.get("pid")
        state.kiosk_pgid = payload.get("pgid")


def set_kiosk_enabled(enabled: bool) -> None:
    with state_lock:
        state.kiosk_enabled = enabled
    persist_kiosk_state()
    publish_kiosk_state()


def record_kiosk_process(pid: int, pgid: int) -> None:
    with state_lock:
        state.kiosk_pid = pid
        state.kiosk_pgid = pgid
    persist_kiosk_state()
    publish_kiosk_state()


def clear_kiosk_process() -> None:
    with state_lock:
        state.kiosk_pid = None
        state.kiosk_pgid = None
    persist_kiosk_state()
    publish_kiosk_state()


def sync_kiosk_process_state() -> None:
    with state_lock:
        pid = state.kiosk_pid
        pgid = state.kiosk_pgid

    if pid is None and pgid is None:
        return

    if kiosk_process_is_running(pid=pid, pgid=pgid):
        return

    clear_kiosk_process()


def start_kiosk_direct() -> str:
    if not KIOSK_LAUNCH_SCRIPT.exists():
        raise RuntimeError(f"Kiosk script not found: {KIOSK_LAUNCH_SCRIPT}")

    sync_kiosk_process_state()
    snapshot = build_kiosk_snapshot()
    if snapshot["running"]:
        return "Kiosken ar redan igang."

    process = subprocess.Popen(
        ["/bin/bash", str(KIOSK_LAUNCH_SCRIPT)],
        cwd=REPO_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.5)
    if process.poll() is not None:
        raise RuntimeError("Kiosken avslutades direkt efter start.")

    record_kiosk_process(process.pid, os.getpgid(process.pid))
    return "Kiosken startades."


def ensure_kiosk_running() -> str:
    with kiosk_control_lock:
        set_kiosk_enabled(True)
        return start_kiosk_direct()


def stop_tracked_kiosk_process() -> str:
    with state_lock:
        pid = state.kiosk_pid
        pgid = state.kiosk_pgid

    if pid is None and pgid is None:
        return "Kiosken ar avstangd och kommer inte att startas om."

    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            clear_kiosk_process()
            return "Kiosken ar avstangd och kommer inte att startas om."
    elif pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            clear_kiosk_process()
            return "Kiosken ar avstangd och kommer inte att startas om."

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not kiosk_process_is_running(pid=pid, pgid=pgid):
            clear_kiosk_process()
            return "Kiosken stoppades och kommer inte att startas om."
        time.sleep(0.2)

    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif pid is not None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    clear_kiosk_process()
    return "Kiosken tvingades att stoppas och kommer inte att startas om."


def minimize_kiosk() -> str:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY_ENV
    env["XAUTHORITY"] = XAUTHORITY_ENV

    attempts: list[tuple[list[str], str]] = [
        (["wlrctl", "toplevel", "minimize", "focused"], "wlrctl"),
        (["xdotool", "getactivewindow", "windowminimize"], "xdotool"),
    ]

    for command, label in attempts:
        if which(command[0]) is None:
            continue
        try:
            run_command(command, env=env)
            return f"Minimerade kioskfönstret via {label}."
        except subprocess.CalledProcessError as exc:
            warn(f"Failed to minimize kiosk with {label}: {exc.stderr.strip() or exc}")

    raise RuntimeError(
        "Ingen stödd metod hittades för att minimera Chromium på den här Pi:n."
    )


def close_kiosk() -> str:
    with kiosk_control_lock:
        set_kiosk_enabled(False)
        sync_kiosk_process_state()
        return stop_tracked_kiosk_process()


def reconcile_kiosk_state() -> None:
    sync_kiosk_process_state()

    with state_lock:
        enabled = state.kiosk_enabled
        pid = state.kiosk_pid
        pgid = state.kiosk_pgid

    if enabled and not kiosk_process_is_running(pid=pid, pgid=pgid):
        try:
            message = start_kiosk_direct()
            debug(message)
        except RuntimeError as exc:
            warn(f"Failed to ensure kiosk is running: {exc}")


def start_kiosk_watchdog() -> None:
    def worker() -> None:
        reconcile_kiosk_state()
        while True:
            time.sleep(KIOSK_WATCHDOG_INTERVAL_SECONDS)
            reconcile_kiosk_state()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def restart_services_async() -> None:
    def worker() -> None:
        time.sleep(1)
        try:
            run_sudo_systemctl("restart", SENSOR_SERVICE_NAME, APP_SERVICE_NAME)
        except subprocess.CalledProcessError as exc:
            warn(f"Failed to restart services after update: {exc.stderr.strip() or exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def update_repo_and_restart() -> str:
    git_status = get_git_status()
    if not git_status["worktreeClean"]:
        raise RuntimeError("Kan inte uppdatera eftersom arbetskatalogen har lokala ändringar.")

    if git_status["state"] == "diverged":
        raise RuntimeError("Kan inte köra git pull automatiskt när branchen har divergerat.")

    if git_status["state"] == "ahead":
        raise RuntimeError("Kan inte köra git pull eftersom lokala commits saknas på origin.")

    run_command(["git", "pull", "--ff-only"])
    restart_services_async()
    return "Ny version neddragen. Tjänsterna startas om."


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
        (KIOSK_COMMAND_TOPIC, 0),
    ]
    if ROOM_TOPIC:
        subscriptions.append((ROOM_TOPIC, 0))
    if AQUARIUM_TOPIC:
        subscriptions.append((AQUARIUM_TOPIC, 0))
    client.subscribe(subscriptions)
    publish_current_view(state.current_view_index)
    publish_kiosk_state()


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

    if topic == KIOSK_COMMAND_TOPIC:
        enabled = parse_kiosk_command(payload)
        if enabled is None:
            warn(f"Ignoring invalid kiosk command payload: {payload!r}")
            return
        try:
            if enabled:
                ensure_kiosk_running()
            else:
                close_kiosk()
        except RuntimeError as exc:
            warn(f"Failed to apply kiosk command: {exc}")
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
            "kiosk": build_kiosk_snapshot(),
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


@app.get("/api/admin/status")
def api_admin_status():
    return jsonify(
        {
            "ok": True,
            "system": get_git_status(),
            "kiosk": build_kiosk_snapshot(),
        }
    )


@app.post("/api/admin/action")
def api_admin_action():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip().lower()

    try:
        if action == "minimize":
            message = minimize_kiosk()
        elif action == "close":
            message = close_kiosk()
        elif action == "start":
            message = ensure_kiosk_running()
        elif action == "update":
            message = update_repo_and_restart()
        else:
            return jsonify({"error": "invalid action"}), 400
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        return jsonify({"ok": False, "error": stderr}), 500
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": message})


@app.post("/api/kiosk/start")
def api_kiosk_start():
    try:
        message = ensure_kiosk_running()
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": message})


@app.post("/api/kiosk/stop")
def api_kiosk_stop():
    try:
        message = close_kiosk()
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": message})


load_kiosk_state()
mqtt_client = start_mqtt()
start_kiosk_watchdog()


if __name__ == "__main__":
    port = int(os.environ.get("AQUAVIEW_PORT", "8100"))
    app.run(host="0.0.0.0", port=port)
