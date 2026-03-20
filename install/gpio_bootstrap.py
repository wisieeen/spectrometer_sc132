#!/usr/bin/env python3
"""
GPIO bootstrap: read mode pins at boot, write /run/spectrometer-boot-mode.json
and flag files for systemd conditional services.
Configures network for AP or STA mode based on GPIO.
AP mode uses NetworkManager (nmcli) — the recommended approach on Bookworm.
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
AP_FLAG = "/run/spectrometer-ap-enabled"

NM_AP_CON_NAME = "spectrometer-ap"
NM_AP_CON_FILE = f"/etc/NetworkManager/system-connections/{NM_AP_CON_NAME}.nmconnection"


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
        return (True, True, True)

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
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return defaults


def _systemctl(*args):
    """Run `systemctl` with best-effort semantics.

    Inputs:
        *args: Arguments passed to `systemctl` (e.g. "start", "service-name").
    Output:
        None (does not raise on failures; captures output is enabled).
    Transformation:
        Invokes `systemctl` via subprocess with a short timeout and ignores errors.
    """
    subprocess.run(["systemctl"] + list(args), check=False, timeout=10, capture_output=True)


LOG_PATHS = ("/boot/firmware/spectrometer-bootstrap.log", "/boot/spectrometer-bootstrap.log")


def _log(msg: str):
    """Append to boot partition log (visible when SD card read on another computer)."""
    for path in LOG_PATHS:
        boot_dir = os.path.dirname(path)
        if os.path.isdir(boot_dir):
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except OSError:
                pass
            return


def _write_ap_nmconnection(wifi_cfg, autoconnect=True):
    """Write NetworkManager connection file for AP mode.

    NM reads this when it starts. autoconnect=True means NM activates it automatically.
    ipv4.method=shared provides built-in DHCP + NAT (no dnsmasq needed).
    """
    import uuid as _uuid

    existing_uuid = None
    if os.path.isfile(NM_AP_CON_FILE):
        try:
            with open(NM_AP_CON_FILE) as f:
                for line in f:
                    if line.startswith("uuid="):
                        existing_uuid = line.strip().split("=", 1)[1]
                        break
        except OSError:
            pass

    con_uuid = existing_uuid or str(_uuid.uuid4())
    ac = "true" if autoconnect else "false"

    content = f"""[connection]
id={NM_AP_CON_NAME}
uuid={con_uuid}
type=wifi
interface-name=wlan0
autoconnect={ac}
autoconnect-priority=100

[wifi]
mode=ap
ssid={wifi_cfg['ap_ssid']}
band=bg
channel={wifi_cfg['ap_channel']}

[wifi-security]
key-mgmt=wpa-psk
psk={wifi_cfg['ap_passphrase']}

[ipv4]
method=shared
address1=192.168.4.1/24

[ipv6]
method=ignore
"""
    os.makedirs(os.path.dirname(NM_AP_CON_FILE), exist_ok=True)
    with open(NM_AP_CON_FILE, "w") as f:
        f.write(content)
    os.chmod(NM_AP_CON_FILE, 0o600)


def _set_ap_autoconnect(enable):
    """Toggle autoconnect in an existing AP nmconnection file."""
    if not os.path.isfile(NM_AP_CON_FILE):
        return
    try:
        with open(NM_AP_CON_FILE) as f:
            lines = f.readlines()
        new_val = "true" if enable else "false"
        out = []
        for line in lines:
            if line.startswith("autoconnect="):
                out.append(f"autoconnect={new_val}\n")
            else:
                out.append(line)
        with open(NM_AP_CON_FILE, "w") as f:
            f.writelines(out)
        os.chmod(NM_AP_CON_FILE, 0o600)
    except (OSError, PermissionError):
        pass


def _nm_is_active():
    r = subprocess.run(
        ["systemctl", "is-active", "NetworkManager"],
        capture_output=True, text=True, timeout=5,
    )
    return (r.stdout or "").strip() == "active"


def _cleanup_legacy_ap_config():
    """Remove artifacts from the old hostapd/dnsmasq AP approach."""
    _systemctl("stop", "hostapd.service")
    _systemctl("stop", "dnsmasq.service")
    _systemctl("disable", "hostapd.service")
    _systemctl("disable", "dnsmasq.service")

    for path in (
        "/etc/NetworkManager/conf.d/99-spectrometer-ap.conf",
        "/etc/systemd/system/wpa_supplicant@wlan0.service.d/spectrometer-ap.conf",
    ):
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        os.rmdir("/etc/systemd/system/wpa_supplicant@wlan0.service.d")
    except OSError:
        pass

    dhcpcd_conf = "/etc/dhcpcd.conf"
    marker = "# spectrometer-bootstrap AP: deny wlan0"
    if os.path.isfile(dhcpcd_conf):
        try:
            with open(dhcpcd_conf) as f:
                lines = f.readlines()
            out, i = [], 0
            skip = ("denyinterfaces wlan0", "interface wlan0", "nohook wpa_supplicant")
            while i < len(lines):
                if marker in lines[i]:
                    i += 1
                    while i < len(lines) and any(p in lines[i] for p in skip):
                        i += 1
                    continue
                out.append(lines[i])
                i += 1
            with open(dhcpcd_conf, "w") as f:
                f.writelines(out)
        except (OSError, PermissionError):
            pass


def configure_network_ap(wifi_cfg):
    """Configure AP mode via NetworkManager connection file.

    Writes spectrometer-ap.nmconnection with autoconnect=true and creates the
    AP flag. NetworkManager's ExecStartPost hook (nm_ap_sta_hook.sh) reloads
    and brings the connection up after NM starts; the dispatcher only adjusts
    firewall rules to avoid reconnect loops.
    """
    try:
        _cleanup_legacy_ap_config()
        _write_ap_nmconnection(wifi_cfg, autoconnect=True)
        open(AP_FLAG, "a").close()
    except Exception:
        pass


def configure_network_sta(_wifi_cfg):
    """Configure STA mode: disable AP autoconnect, remove AP flag; NM hook downs AP."""
    try:
        _set_ap_autoconnect(False)
        try:
            os.remove(AP_FLAG)
        except FileNotFoundError:
            pass
    except Exception:
        pass


RECOVERY_TRIGGER_NAMES = ("spectrometer-network-recovery", "spectrometer-network-recovery.txt")
BOOT_PATHS = ("/boot/firmware", "/boot")


def _log_diagnostics(mode, wifi_ap, skip_network, errors):
    """Write diagnostic block to boot partition log."""
    from datetime import datetime

    lines = [
        f"=== {datetime.now().isoformat()} ===",
        f"mode: {json.dumps(mode)}",
        f"skip_network: {skip_network}",
        f"network_config: {'ap' if wifi_ap else 'sta'}",
    ]
    try:
        nm_active = (
            subprocess.run(
                ["systemctl", "is-active", "NetworkManager"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() == "active"
        )
        lines.append(f"NetworkManager_active: {nm_active}")
    except Exception:
        lines.append("NetworkManager_active: unknown")
    try:
        lines.append(f"ap_nmconnection_exists: {os.path.isfile(NM_AP_CON_FILE)}")
        if os.path.isfile(NM_AP_CON_FILE):
            with open(NM_AP_CON_FILE) as f:
                for line in f:
                    if line.startswith("autoconnect="):
                        lines.append(f"ap_autoconnect: {line.strip().split('=',1)[1]}")
                        break
    except Exception:
        pass
    try:
        ip_out = subprocess.run(
            ["ip", "-4", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=5,
        ).stdout or ""
        addrs = [l.strip() for l in ip_out.split("\n") if "inet " in l]
        lines.append(f"wlan0_addrs: {addrs}")
    except Exception:
        lines.append("wlan0_addrs: unknown")
    if errors:
        lines.append(f"errors: {errors}")
    _log("\n".join(lines))


def _run_network_recovery():
    """Remove spectrometer network overrides and reboot. Called when trigger file exists in boot partition."""
    for boot in BOOT_PATHS:
        for name in RECOVERY_TRIGGER_NAMES:
            trigger = os.path.join(boot, name)
            if os.path.isfile(trigger):
                try:
                    os.remove(trigger)
                except OSError:
                    pass
                try:
                    os.remove(NM_AP_CON_FILE)
                except OSError:
                    pass
                _cleanup_legacy_ap_config()
                if _nm_is_active():
                    subprocess.run(["nmcli", "con", "reload"], check=False, timeout=10, capture_output=True)
                _systemctl("disable", "spectrometer-bootstrap.service")
                subprocess.run(["systemctl", "daemon-reload"], check=False, timeout=10, capture_output=True)
                subprocess.run(["reboot"], check=False, timeout=5)
                return True
    return False


def main():
    """Bootstrapping entrypoint: decide AP/STA and conditional services.

    Inputs:
        None (reads GPIO state and environment config from disk/system files).
    Output:
        Process exit code 0; writes `/run/spectrometer-boot-mode.json` and boot flag files.
    Transformation:
        - Performs optional network recovery when recovery trigger files exist in the boot partition.
        - Reads GPIO mode pins to decide which flags to create:
            * `/run/spectrometer-mqtt-enabled`
            * `/run/spectrometer-webserver-enabled`
            * `/run/spectrometer-ap-enabled` (for AP mode)
        - Configures NetworkManager for AP or STA mode unless `spectrometer-skip-network` is present.
        - Writes diagnostic info to the boot log.
    """
    if _run_network_recovery():
        _log("=== recovery triggered, rebooting ===")
        return 0
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
    skip_network = os.path.exists("/boot/firmware/spectrometer-skip-network") or os.path.exists(
        "/boot/spectrometer-skip-network"
    )
    errors = []
    if not skip_network:
        try:
            if wifi_ap:
                configure_network_ap(wifi_cfg)
            else:
                configure_network_sta(wifi_cfg)
        except Exception as e:
            errors.append(str(e))

    _log_diagnostics(mode, wifi_ap, skip_network, errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
