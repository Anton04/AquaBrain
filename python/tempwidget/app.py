from flask import Flask, jsonify, render_template
import glob
import time
import math

app = Flask(__name__)

# -------- 1-Wire config --------

BASE = "/sys/bus/w1/devices/"
start_time = time.time()


def find_sensor():
    devices = glob.glob(BASE + "28-*")
    return devices[0] if devices else None


def read_real_temp(device):
    file = device + "/w1_slave"

    try:
        for _ in range(5):
            with open(file, "r") as f:
                lines = f.readlines()

            if lines and lines[0].strip().endswith("YES"):
                t = lines[1].split("t=")[1]
                return float(t) / 1000.0

            time.sleep(0.2)
    except:
        pass

    return None


# -------- Simulerad fallback --------

def simulated_temp():
    t = time.time() - start_time
    return 22 + math.sin(t / 20) * 1.5


def read_temp():
    device = find_sensor()

    if device:
        temp = read_real_temp(device)
        if temp is not None:
            return temp, False

    return simulated_temp(), True

def read_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read()) / 1000.0
    except:
        return None



# -------- Routes --------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/temp")
def api_temp():
    temp, sim = read_temp()
    cpu = read_cpu_temp()

    return jsonify({
        "room": temp,
        "simulated": sim,
        "cpu": cpu
    })


# -------- Dev run --------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
