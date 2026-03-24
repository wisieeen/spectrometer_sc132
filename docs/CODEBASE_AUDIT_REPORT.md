# Codebase Audit: Conflicts, Inconsistencies, Simplification

**Date:** 2025-03-18  
**Scope:** spectrometer_sc132 codebase and documentation  
**Status:** Addressed 2025-03-18

---

## Critical Bug Fixed (2025-03-18)

### `_process_frame_to_dict` used undefined `flat`
- **File:** `spectrometer/scripts/spectrometer_webserver.py`
- **Issue:** Line 66 referenced `flat` in `dark_flat_applied` but `flat` was never passed to the function. Would raise `NameError` when dark/flat correction enabled and spectrum computed.
- **Fix:** Added `flat=None` to signature; callers now pass `flat=flat`.

---

## Resolved (2025-03-18)

### 1.1 `_get_processing_cfg` unified
- **Done:** Added `get_processing_cfg()` to `lib/config.py`. All callers (spectrometer_service, spectrometer_webserver, measure_psf) now use it.

### 1.2 Wiener removed
- **Done:** Wiener deconvolution removed. Deleted `wiener.py`, removed from service, webserver, UI, docs, Home Assistant configs. Richardson–Lucy only.

### 2.1 `env_config` path
- **Done:** MQTT API uses `DEFAULT_ENV_CONFIG` from `lib.env_config`.

### 2.2 Camera config
- **Done:** Added `save_camera_config()` to `lib.env_config`. Webserver uses `load_camera_config` and `save_camera_config` instead of local helpers.

### 2.3 `/api/theme`
- **Done:** Removed unused endpoint.

### 2.4 HLS.js
- **Done:** Added HLS.js CDN script to `index.html` before `app.js`.

### 2.5 Config path
- **Done:** Standardized to `spectrometer_sc132` in AGENT_FRONTEND.md and env_config.example.json.

### 2.6 Spectrum `meta`
- **Done:** Webserver now includes `processing` (frame_average_n, dark_flat_applied, richardson_lucy_applied) in spectrum `meta`. WEBSERVER_API.md and AGENT_FRONTEND.md aligned.

---

## Remaining (lower priority)

### 3.1 Dead code: `frame_average.average_frames`
- **File:** `spectrometer/lib/signal_processing/frame_average.py`
- `average_frames()` is never imported or used. Averaging is done in `camera_capture.capture_frames_averaged()`.
- **Recommendation:** Remove `frame_average.py` or refactor so `capture_frames_averaged` uses it.

### 3.2 Repetitive processing endpoint handlers
- Each processing setting has its own route with the same pattern.
- **Recommendation:** Introduce a generic handler or decorator.

### 3.3 Duplicate I2C exposure/gain logic
- Webserver `_apply_exposure_gain()` vs `camera_capture._configure_device()`.
- **Recommendation:** Move I2C logic into shared helper; call from webserver.

### 3.4 Video tab: fire-and-forget API calls
- **File:** `spectrometer/static/js/app.js` lines 363–368
- Resolution, FPS, shutter, gain, pixel_format `change` handlers call `api()` without `await` or `showStatus`.
- Errors are not surfaced to the user.
- **Recommendation:** Use `apiSilent` or add `await` + error handling.

### 3.5 env_config.json vs mqtt topic naming
- **File:** `env_config.example.json`
- Root `mqtt` section uses `lab/monocamera/cmd/` and `lab/monocamera/state/`; `spectrometer` section uses `lab/spectrometer/cmd/` and `lab/spectrometer/state/`.
- MQTT is shared; monocamera vs spectrometer might be intentional for different services.
- **Note:** No conflict if monocamera is for camera control and spectrometer for spectrometer service.

### 3.6 spectrometer_service `_process_frame` dark parameter
- **File:** `spectrometer/scripts/spectrometer_service.py` line 243
- `_process_frame(frame, spec_cfg, output, pm, dark=dark)` passes `dark` but the function never uses it (only `processing_meta`). The `dark` param is unused.
- **Recommendation:** Remove unused `dark` parameter from `_process_frame`.
