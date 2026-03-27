# GPIO Mode Selection

GPIO pins (BCM numbering, internal pull-up) are read at boot to select WiFi mode, webserver, and MQTT.

## Pin Assignment

| Pin (BCM) | Function   | Pull-up logic                  |
|-----------|------------|--------------------------------|
| GPIO 5    | WiFi mode  | LOW = AP, HIGH = STA           |
| GPIO 6    | Webserver  | LOW = enabled, HIGH = disabled |
| GPIO 7    | MQTT       | LOW = enabled, HIGH = disabled |

Pins are configurable in `env_config.json` under `gpio`:

```json
{
  "gpio": {
    "wifi_mode_pin": 5,
    "webserver_pin": 6,
    "mqtt_pin": 7
  }
}
```

Avoid GPIO 4 if UPS_Lite is used.

## Mode Combinations

- **AP + webserver**: Pi creates hotspot; user connects and uses web UI. No MQTT broker needed.
- **STA + webserver**: Pi connects to existing WiFi; web UI available.
- **AP/STA + MQTT**: Standard MQTT camera/spectrometer control.
- **Webserver + MQTT**: Both interfaces active; spectrometer runs in webserver (spectrometer.service does not run when webserver is enabled).
