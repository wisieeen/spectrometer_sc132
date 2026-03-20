"""MQTT-driven camera controller for spectrometer streams.

Subscribes to the configured MQTT command topic and starts/stops RTSP streaming (mediamtx + rtsp-camera),
applies camera exposure/gain via I2C, and updates camera configuration values by writing JSON to disk.
"""

import paho.mqtt.client as mqtt
import json
import os
import subprocess

ENV_CONFIG_FILE = os.environ.get("ENV_CONFIG", "/home/raspberry/env_config.json")


def _load_env():
    """Load the environment config JSON specified by `ENV_CONFIG_FILE`.

    Inputs:
        None (uses `ENV_CONFIG_FILE` constant).
    Output:
        Parsed environment dict (must include `mqtt`, `paths`, `device`, and `services` keys).
    Transformation:
        Deserializes JSON from disk into a Python dict.
    """
    with open(ENV_CONFIG_FILE) as f:
        return json.load(f)


_ENV = _load_env()

BROKER = _ENV["mqtt"]["broker"]
PORT = int(_ENV["mqtt"]["port"])
USER = _ENV["mqtt"]["user"]
PASS = _ENV["mqtt"]["pass"]
CMD_TOPIC = _ENV["mqtt"]["cmd_topic"]
STATE_TOPIC = _ENV["mqtt"]["state_topic"]
RTSP_ALIAS_TOPIC = _ENV["mqtt"]["cmd_topic"].rstrip("/") + "/rtsp"

CONFIG_FILE = _ENV["paths"]["camera_config"]
I2C_TOOL = _ENV["paths"]["i2c_tool"]
I2C_TOOL_DIR = os.path.dirname(I2C_TOOL)
I2C_BUS = str(_ENV["device"]["i2c_bus"])
MEDIAMTX_SERVICE = _ENV["services"]["mediamtx"]
RTSP_CAMERA_SERVICE = _ENV["services"]["rtsp_camera"]

DEBUG = _ENV.get("debug", False)


def load_config():
    """Load the camera configuration JSON from disk.

    Inputs:
        None (uses `CONFIG_FILE` constant).
    Output:
        Parsed JSON dict representing the camera configuration.
    Transformation:
        Reads `CONFIG_FILE` and deserializes via `json.load`.
    """
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg):
    """Save the camera configuration JSON to disk.

    Inputs:
        cfg: Camera configuration dict to persist.
    Output:
        None (writes file contents).
    Transformation:
        Serializes `cfg` as JSON with indentation and writes to `CONFIG_FILE`.
    """
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def publish_all_states(client, cfg):
    """Publish all configuration values to MQTT as retained state messages.

    Inputs:
        client: MQTT client instance with `.publish(...)`.
        cfg: Camera configuration dict.
    Output:
        None (side-effect publishes to `STATE_TOPIC + key`).
    Transformation:
        Iterates over keys in `cfg` and publishes each as a retained MQTT message.
    """
    for key, val in cfg.items():
        client.publish(STATE_TOPIC + key, str(val), retain=True)


def _systemctl(action, unit):
    """Run `sudo systemctl <action> <unit>` best-effort.

    Inputs:
        action: systemctl action (start/stop/restart).
        unit: systemd unit name.
    Output:
        None (errors are ignored because `check=False`).
    Transformation:
        Invokes systemctl via subprocess.
    """
    subprocess.run(["sudo", "systemctl", action, unit], check=False, timeout=15)


def start_stream():
    """Start mediamtx (RTSP server) then camera publisher. Use on RTSP ON."""
    _systemctl("start", MEDIAMTX_SERVICE)
    _systemctl("start", RTSP_CAMERA_SERVICE)


def stop_stream():
    """Stop camera publisher then mediamtx. Use on RTSP OFF."""
    _systemctl("stop", RTSP_CAMERA_SERVICE)
    _systemctl("stop", MEDIAMTX_SERVICE)


def restart_stream():
    _systemctl("restart", RTSP_CAMERA_SERVICE)


def safe_shutdown():
    """Stop stream, then power off the device. Use on MQTT shutdown command."""
    if DEBUG:
        print("[mqtt_camera] Shutdown requested: stopping stream, then powering off")
    stop_stream()
    subprocess.run(["sudo", "shutdown", "-h", "now"], check=False, timeout=5)


def safe_reboot():
    """Stop stream, then reboot the device. Use on MQTT reboot command."""
    if DEBUG:
        print("[mqtt_camera] Reboot requested: stopping stream, then rebooting")
    stop_stream()
    subprocess.run(["sudo", "shutdown", "-r", "now"], check=False, timeout=5)


def apply_exposure_and_gain(cfg):
    """Apply shutter/exposure and gain to the camera using the configured I2C tool.

    Inputs:
        cfg: Camera config dict; expected keys:
            - `fps` (int)
            - `shutter` (int microseconds)
            - `gain` (float or number)
    Output:
        None (side-effect: calls external I2C tool when available).
    Transformation:
        - Computes maximum exposure from fps and clamps shutter if necessary.
        - Uses the I2C tool to set `expmode`, `gainmode`, and optionally `metime`/`mgain`.
        - Silently returns when I2C tool is missing or not executable.
    """
    if not os.path.isfile(I2C_TOOL) or not os.access(I2C_TOOL, os.X_OK):
        if DEBUG:
            print(f"[mqtt_camera] I2C tool not executable at {I2C_TOOL}, skipping exposure/gain")
        return

    fps = int(cfg.get("fps", 1)) or 1
    shutter = int(cfg.get("shutter", 0))
    gain = cfg.get("gain", 0.0)

    max_exposure = 1000000 // fps
    if shutter > max_exposure:
        if DEBUG:
            print(f"[mqtt_camera] Requested shutter {shutter}us > max {max_exposure}us at {fps}fps, clamping")
        shutter = max_exposure

    if DEBUG:
        print(f"[mqtt_camera] Applying exposure/gain via I2C: fps={fps}, shutter={shutter}us, gain={gain}dB")

    try:
        subprocess.run(
            [I2C_TOOL, "-w", "expmode", "0", "-b", I2C_BUS],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=I2C_TOOL_DIR,
        )
        subprocess.run(
            [I2C_TOOL, "-w", "gainmode", "0", "-b", I2C_BUS],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=I2C_TOOL_DIR,
        )
        if shutter > 0:
            subprocess.run(
                [I2C_TOOL, "-w", "metime", str(shutter), "-b", I2C_BUS],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=I2C_TOOL_DIR,
            )
        if gain is not None:
            subprocess.run(
                [I2C_TOOL, "-w", "mgain", str(gain), "-b", I2C_BUS],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=I2C_TOOL_DIR,
            )
    except Exception:
        if DEBUG:
            print("[mqtt_camera] Error while applying exposure/gain via I2C")


def on_message(client, userdata, msg):
    """MQTT callback: decode commands and update streaming/camera configuration.

    Inputs:
        client: MQTT client instance.
        userdata: Unused callback userdata.
        msg: MQTT message containing `.topic` and `.payload`.
    Output:
        None (side-effect: starts/stops services, writes config, applies I2C, publishes retained state).
    Transformation:
        - Resolves the command name from `msg.topic` (and `RTSP_ALIAS_TOPIC`).
        - Dispatches commands:
            * rtsp ON/OFF -> start/stop stream
            * shutdown/reboot -> power control and returns early
            * resolution/fps/shutter/gain/pixel_format -> updates config and applies/restarts
        - Publishes the updated full config via retained state messages.
    """
    full_topic = msg.topic
    payload = msg.payload.decode()
    if DEBUG:
        print(f"[mqtt_camera] MQTT message: topic='{full_topic}', payload='{payload}'")

    cfg = load_config()

    if full_topic == RTSP_ALIAS_TOPIC:
        topic = "rtsp"
    else:
        topic = full_topic.replace(CMD_TOPIC, "")

    if DEBUG:
        print(f"[mqtt_camera] Resolved command topic='{topic}'")

    if topic == "rtsp":
        if payload.upper() == "ON":
            if DEBUG:
                print("[mqtt_camera] RTSP ON requested (starting mediamtx then rtsp-camera)")
            start_stream()
        elif payload.upper() == "OFF":
            if DEBUG:
                print("[mqtt_camera] RTSP OFF requested (stopping rtsp-camera then mediamtx)")
            stop_stream()

    elif topic == "shutdown":
        if payload.upper() in ("ON", "1", "true", "yes"):
            safe_shutdown()
            return  # Device will power off; no need to publish state

    elif topic == "reboot":
        if payload.upper() in ("ON", "1", "true", "yes"):
            safe_reboot()
            return  # Device will reboot; no need to publish state

    elif topic == "resolution":
        cfg["resolution"] = payload
        save_config(cfg)
        if DEBUG:
            print(f"[mqtt_camera] Resolution set to {cfg['resolution']}, restarting stream")
        restart_stream()

    elif topic == "fps":
        cfg["fps"] = int(payload)
        save_config(cfg)
        if DEBUG:
            print(f"[mqtt_camera] FPS set to {cfg['fps']}, reapplying exposure/gain and restarting stream")
        apply_exposure_and_gain(cfg)
        restart_stream()

    elif topic == "shutter":
        cfg["shutter"] = int(payload)
        save_config(cfg)
        if DEBUG:
            print(f"[mqtt_camera] Shutter set to {cfg['shutter']}us, applying live")
        apply_exposure_and_gain(cfg)

    elif topic == "gain":
        cfg["gain"] = float(payload)
        save_config(cfg)
        if DEBUG:
            print(f"[mqtt_camera] Gain set to {cfg['gain']}dB, applying live")
        apply_exposure_and_gain(cfg)

    elif topic == "pixel_format" or topic == "bit_depth":
        val = payload.strip().upper()
        if topic == "bit_depth":
            if val in ("8", "8BIT"):
                val = "Y8"
            elif val in ("10", "10BIT"):
                val = "Y10"
            else:
                if DEBUG:
                    print(f"[mqtt_camera] bit_depth: invalid payload '{payload}', use 8 or 10")
                return
        if val in ("Y8", "GREY", "GREY8"):
            val = "Y8"
        elif val in ("Y10", "Y10P"):
            pass
        else:
            if DEBUG:
                print(f"[mqtt_camera] pixel_format: invalid payload '{payload}', use Y8, Y10, or Y10P")
            return
        cfg["pixel_format"] = val
        save_config(cfg)
        if DEBUG:
            print(f"[mqtt_camera] Pixel format (bit depth) set to {val}, restarting stream")
        restart_stream()

    save_config(cfg)
    if DEBUG:
        print(f"[mqtt_camera] Publishing state: {cfg}")
    publish_all_states(client, cfg)


client = mqtt.Client()
client.username_pw_set(USER, PASS)
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.subscribe(CMD_TOPIC + "#")
client.subscribe(RTSP_ALIAS_TOPIC)
client.loop_forever()