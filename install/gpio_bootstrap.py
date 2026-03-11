#!/usr/bin/env python3
"""
GPIO bootstrap: read mode pins at boot, write /run/spectrometer-boot-mode.json
and flag files for systemd conditional services.
Configures network for AP or STA mode based on GPIO.
Pins use internal pull-up: LOW = active/selected.
"""
import json
import os
import subprocess
import sys

ENV_CONFIG = os.environ.get("ENV_CONFIG", "/home/raspberry/env_config.json")
MODE_FILE = "/run/spectrometer-boot-mode.json"
MQTT_FLAG = "/run/spectrometer-mqtt-enabled"
WEBSERVER_FLAG = "/run/spectrometer-webserver-enabled"


def load_gpio_config():
    """Load GPIO pin numbers from env_config. Defaults: 5=wifi, 6=webserver, 7=mqtt."""
    defaults = {"wifi_mode_pin": 5, "webserver_pin": 6, "mqtt_pin": 7}
    if not os.path.isfile(ENV_CONFIG):
        return defaults
    try:
        with open(ENV_CONFIG) as f:
            cfg = json.load(f)
        gpio = cfg.get("gpio", {}) or {}
        return {
            "wifi_mode_pin": int(gpio.get("wifi_mode_pin", defaults["wifi_mode_pin"])),
            "webserver_pin": int(gpio.get("webserver_pin", defaults["webserver_pin"])),
            "mqtt_pin": int(gpio.get("mqtt_pin", defaults["mqtt_pin"])),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return defaults


def read_gpio_pins(pins):
    """Read GPIO pins. Returns (wifi_ap, webserver, mqtt). LOW = True."""
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        # Not on Raspberry Pi - use defaults for development
        return (True, True, True)  # AP, webserver, mqtt all "enabled" for dev

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for pin in (pins["wifi_mode_pin"], pins["webserver_pin"], pins["mqtt_pin"]):
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    wifi_low = GPIO.input(pins["wifi_mode_pin"]) == GPIO.LOW
    webserver_low = GPIO.input(pins["webserver_pin"]) == GPIO.LOW
    mqtt_low = GPIO.input(pins["mqtt_pin"]) == GPIO.LOW

    GPIO.cleanup()
    return (wifi_low, webserver_low, mqtt_low)


def load_wifi_config():
    """Load WiFi config from env_config for AP/STA setup."""
    defaults = {
        "ap_ssid": "Spectrometer-AP",
        "ap_passphrase": "changeme",
        "ap_channel": 6,
        "sta_config_path": "/etc/wpa_supplicant/wpa_supplicant.conf",
    }
    if not os.path.isfile(ENV_CONFIG):
        return defaults
    try:
        with open(ENV_CONFIG) as f:
            cfg = json.load(f)
        w = cfg.get("wifi", {}) or {}
        return {
            "ap_ssid": str(w.get("ap_ssid", defaults["ap_ssid"])),
            "ap_passphrase": str(w.get("ap_passphrase", defaults["ap_passphrase"])),
            "ap_channel": int(w.get("ap_channel", defaults["ap_channel"])),
            "sta_config_path": str(w.get("sta_config_path", defaults["sta_config_path"])),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return defaults


def _systemctl(*args):
    subprocess.run(["systemctl"] + list(args), check=False, timeout=10, capture_output=True)


def configure_network_ap(wifi_cfg):
    """Configure and enable AP mode (hostapd + dnsmasq)."""
    hostapd_cfg = "/etc/hostapd/hostapd.conf"
    dnsmasq_cfg = "/etc/dnsmasq.d/spectrometer-ap.conf"
    try:
        os.makedirs(os.path.dirname(hostapd_cfg), exist_ok=True)
        with open(hostapd_cfg, "w") as f:
            f.write(f"""interface=wlan0
driver=nl80211
ssid={wifi_cfg['ap_ssid']}
hw_mode=g
channel={wifi_cfg['ap_channel']}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={wifi_cfg['ap_passphrase']}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
""")
        os.makedirs(os.path.dirname(dnsmasq_cfg), exist_ok=True)
        with open(dnsmasq_cfg, "w") as f:
            f.write("""interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
""")
        _systemctl("stop", "wpa_supplicant@wlan0.service")
        _systemctl("mask", "wpa_supplicant@wlan0.service")
        _systemctl("unmask", "hostapd.service")
        _systemctl("enable", "hostapd.service")
        _systemctl("unmask", "dnsmasq.service")
        _systemctl("enable", "dnsmasq.service")
    except Exception as e:
        if os.environ.get("DEBUG"):
            print(f"AP config error: {e}", file=sys.stderr)


def configure_network_sta(wifi_cfg):
    """Configure and enable STA mode (wpa_supplicant)."""
    try:
        _systemctl("stop", "hostapd.service")
        _systemctl("stop", "dnsmasq.service")
        _systemctl("disable", "hostapd.service")
        _systemctl("disable", "dnsmasq.service")
        _systemctl("unmask", "wpa_supplicant@wlan0.service")
        _systemctl("enable", "wpa_supplicant@wlan0.service")
        # Copy project wifi_credentials.conf to sta_config_path if present
        project_home = "/home/raspberry"
        if os.path.isfile(ENV_CONFIG):
            with open(ENV_CONFIG) as f:
                cfg = json.load(f)
            project_home = cfg.get("paths", {}).get("home", project_home)
        creds = os.path.join(project_home, "wifi_credentials.conf")
        if os.path.isfile(creds):
            try:
                import shutil
                shutil.copy(creds, wifi_cfg["sta_config_path"])
            except Exception:
                pass
    except Exception as e:
        if os.environ.get("DEBUG"):
            print(f"STA config error: {e}", file=sys.stderr)


def main():
    pins = load_gpio_config()
    wifi_ap, webserver, mqtt = read_gpio_pins(pins)

    mode = {
        "wifi_mode": "ap" if wifi_ap else "sta",
        "webserver": bool(webserver),
        "mqtt": bool(mqtt),
    }

    with open(MODE_FILE, "w") as f:
        json.dump(mode, f, indent=2)

    if mqtt:
        open(MQTT_FLAG, "a").close()
    else:
        try:
            os.remove(MQTT_FLAG)
        except FileNotFoundError:
            pass

    if webserver:
        open(WEBSERVER_FLAG, "a").close()
    else:
        try:
            os.remove(WEBSERVER_FLAG)
        except FileNotFoundError:
            pass

    wifi_cfg = load_wifi_config()
    if wifi_ap:
        configure_network_ap(wifi_cfg)
    else:
        configure_network_sta(wifi_cfg)

    if os.environ.get("DEBUG"):
        print(f"spectrometer-bootstrap: {mode}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
