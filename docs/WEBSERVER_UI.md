# Webserver Interface Layout

## Tabs

1. **Spectrometer** – spectrum chart + controls
2. **Video stream** – stream display + camera controls
3. **Configuration** – WiFi, MQTT broker

## Spectrometer Tab

- **Top**: Spectrum chart (X = wavelength nm, Y = intensity)
- **Bottom**: Parameter controls (start/stop/single, interval, frame average, dark/flat, Richardson–Lucy, preview)

**Spectrum chart**:
- Local maxima: wavelength label above each peak, rotated 75°
- Max 1 label per 20 nm (highest peak in each window)
- Interactive cursor: vertical line follows mouse/touch; shows wavelength and intensity
- Touch support

## Video Stream Tab

- **Top**: Video element, fullscreen button
- **Bottom**: RTSP on/off, resolution, FPS, shutter, gain, pixel format

**Stream**: Browsers do not support RTSP. Use mediamtx HLS (port 8888) or similar. The `/api/stream/url` endpoint returns HLS URL derived from RTSP config.

## Configuration Tab

- **WiFi**: SSID, password (for STA mode). Save writes to `wifi_credentials.conf`.
- **MQTT**: Broker, port, username, password. Save updates `env_config.json`.

## Themes

- **Light** – light background, dark text
- **Dark** – dark background, light text
- **High contrast** – black/white
- **Green military** – dark background, green/amber (terminal style)

Theme choice stored in `localStorage` as `spectrometer-theme`.
