# Timing Benchmark Report (2026-03-26)

## Scope

Dataset: `time_log.csv`  
Run shape: 90 scenarios = `5 frame_average_n` x `3 channel modes` x `2 RL modes` x `3 repeats`.

Factors analyzed:

- `frame_average_n`: 1, 2, 4, 8, 16
- Active channels: `ch0`, `ch2`, `ch0+ch2`
- Richardson-Lucy (RL): `off`, `on`

Fixed conditions visible in log:

- `dark_flat_enabled=true` for all scenarios
- `channels_configured=2`
- Interval parameter logged as `1000` (single-shot benchmark still uses `_single_*` step totals)

Additional parameters:

- Gain 10dB
- Shutter 1000us
- ch0 line thickness=10px, ch2=5px
- Richardson-Lucy iterations=15, custom PSF has 100px

## Data Integrity

- Rows in CSV: `1446`
- Unique measurement cycles: `90`
- Every cycle contains `_single_acquire_frame_total` and `_single_process_frame_total`, so cycle totals are complete.
- Repeat consistency is good:
  - Repeat 1 mean total: `1284.40 ms`
  - Repeat 2 mean total: `1287.46 ms`
  - Repeat 3 mean total: `1272.61 ms`

## Single-shot vs Continuous Operation

This benchmark is driven by `POST /api/spectrometer/single` (one-shot capture per scenario).

In single-shot mode, the server intentionally does more per request:
- It invalidates capture context (`invalidate_capture_context_cache()`).
- It forces dark/flat reload by calling the dark/flat loader with `force_reload=True` (even if calibration is unchanged).
- It re-loads processing/spectrometer configuration for that one-shot.

In continuous operation (`POST /api/spectrometer/start` -> the background `_capture_loop()`), dark/flat frames are typically served from the in-memory cache, so the per-frame calibration/config overhead is much lower.

Empirical note from your measurements: continuous operation is about `~540 ms` faster per frame capture than the timing numbers reported in this single-shot dataset. Effectively, single cycle takes around `180ms` on tested hardware (RPI Zero 2 W)

## Main Findings

### 1) Frame averaging dominates end-to-end timing

Mean cycle total (`_single_acquire_frame_total + _single_process_frame_total`) by `frame_average_n`:


| frame_average_n | mean total [ms] | std [ms] |
| --------------- | --------------- | -------- |
| 1               | 874.66          | 77.94    |
| 2               | 998.76          | 90.21    |
| 4               | 1180.90         | 134.45   |
| 8               | 1408.10         | 82.17    |
| 16              | 1945.05         | 75.46    |


Interpretation:

- `frame_average_n` is the strongest performance lever.
- Moving from `1 -> 16` adds about `+1070 ms` on average.

### 2) Acquisition stage is the primary bottleneck

Mean across all 90 cycles:

- `_single_acquire_frame_total`: `1068.58 ms`
- `_single_process_frame_total`: `212.91 ms`


Acquisition growth with averaging:

- Avg=1: `662.25 ms`
- Avg=2: `786.40 ms`
- Avg=4: `967.22 ms`
- Avg=8: `1193.64 ms`
- Avg=16: `1733.38 ms`

### 3) Active channel count impacts processing time as expected

Mean cycle total by channel mode:

| channel mode | mean total [ms] | std [ms] | line thickness |
| ------------ | --------------- | -------- | -------------- |
| ch2          | 1195.61         | 379.42   | 5px            |
| ch0          | 1274.30         | 387.36   | 10px           |
| ch0+ch2      | 1374.57         | 379.33   | sum=15px       |


Supporting step-level evidence:

- `extract_line_profile` mean by channel:
  - `ch0`: `173.99 ms`
  - `ch2`: `119.86 ms`
- `ch0` extraction is consistently slower than `ch2` due to larger thickness. Numbers suggest additional `10.8ms` per pixel of thickness.

### 4) RL overhead is measurable but secondary

Overall mean cycle total:

- RL off: `1268.16 ms`
- RL on:  `1294.82 ms`
- Delta:  `+26.66 ms` (~2.1%)

RL overhead trends:

- Usually positive (extra cost), especially at higher averaging and dual-channel mode.
- Mean `richardson_lucy_deconvolve` step:
  - `ch0`: `22.45 ms`
  - `ch2`: `21.96 ms`
independent of linewidth (expected).


