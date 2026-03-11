# Webserver REST API

Base path: `/api`

## Spectrometer

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/spectrometer/start` | Start continuous capture |
| POST | `/spectrometer/stop` | Stop continuous |
| POST | `/spectrometer/single` | Single spectrum |
| GET/POST | `/spectrometer/interval_ms` | Get/set interval (ms) |
| GET/POST | `/spectrometer/processing_frame_average_n` | Frame average count |
| GET/POST | `/spectrometer/processing_dark_flat_enabled` | Dark/flat correction |
| GET/POST | `/spectrometer/processing_wiener_enabled` | Wiener deconvolution |
| GET/POST | `/spectrometer/processing_wiener_psf_sigma` | Wiener PSF sigma |
| GET/POST | `/spectrometer/processing_wiener_regularization` | Wiener regularization |
| POST | `/spectrometer/preview` | Trigger preview |
| GET | `/spectrometer/status` | Status, channels, processing |
| GET | `/spectrometer/spectrum/{channel_id}` | Last spectrum JSON |

## Camera / Stream

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/camera/config` | Camera config (resolution, fps, shutter, gain, pixel_format) |
| POST | `/camera/rtsp` | `{action: "on"|"off"}` Start/stop stream |
| POST | `/camera/resolution` | `{value: "1080x640"}` |
| POST | `/camera/fps` | `{value: 5}` |
| POST | `/camera/shutter` | `{value: 4100}` (µs) |
| POST | `/camera/gain` | `{value: 1.0}` (dB) |
| POST | `/camera/pixel_format` | `{value: "Y8"|"Y10"|"Y10P"}` |
| GET | `/stream/url` | `{hls, rtsp}` stream URLs |

## Config

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/config/wifi` | WiFi credentials (SSID, password) |
| GET/POST | `/config/mqtt` | MQTT broker config |

## Spectrum Payload

```json
{
  "channel_id": "ch0",
  "timestamp": "2025-03-10T12:00:00.000Z",
  "wavelengths_nm": [400.0, 401.0, ...],
  "intensities": [0.1, 0.2, ...],
  "meta": {
    "shutter_us": 4100,
    "gain_db": 1.0
  }
}
```
