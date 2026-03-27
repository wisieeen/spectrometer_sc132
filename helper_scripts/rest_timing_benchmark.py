#!/usr/bin/env python3
"""
REST benchmark driver for spectrometer timing experiments.

This script does not implement custom timing metrics. It only:
1) updates spectrometer processing/channel parameters via REST,
2) requests one measurement,
3) waits until a new spectrum is available before continuing.

Use together with the existing server-side timing CSV profiler.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple


CHANNEL_PRESETS = {
    "ch0": ("ch0",),
    "ch2": ("ch2",),
    "both": ("ch0", "ch2"),
}


def _parse_csv_ints(raw: str) -> List[int]:
    values = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token))
    if not values:
        raise ValueError("at least one integer value is required")
    return values


def _parse_csv_strings(raw: str) -> List[str]:
    values = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not values:
        raise ValueError("at least one value is required")
    return values


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


class RestClient:
    def __init__(self, base_url: str, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _call(self, method: str, endpoint: str, payload: Dict = None) -> Dict:
        url = self.base_url + endpoint
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {method} {endpoint}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Request failed for {method} {endpoint}: {exc}") from exc

    def get(self, endpoint: str) -> Dict:
        return self._call("GET", endpoint)

    def post(self, endpoint: str, payload: Dict = None) -> Dict:
        return self._call("POST", endpoint, payload=payload)


def _raise_connectivity_hint(base_url: str, err: Exception) -> None:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or ""
    hint_lines = [
        f"Cannot reach REST API at {base_url}.",
        f"Original error: {err}",
        "Checks:",
        "- Verify webserver is running (spectrometer_webserver.py / service).",
        "- Verify host+port are correct and reachable from this machine.",
    ]
    if host in ("192.168.10.1", "localhost", "127.0.0.1"):
        hint_lines.append("- If benchmark runs on the same Raspberry Pi as webserver, prefer --base-url http://127.0.0.1:8080")
    else:
        hint_lines.append("- If benchmark runs on the same Raspberry Pi as webserver, use --base-url http://127.0.0.1:8080")
    raise RuntimeError("\n".join(hint_lines))


def _preflight_api(client: RestClient) -> None:
    try:
        client.get("/api/spectrometer/status")
    except Exception as exc:
        _raise_connectivity_hint(client.base_url, exc)


def _set_channels(client: RestClient, active_channels: Tuple[str, ...]) -> None:
    for ch in ("ch0", "ch2"):
        client.post("/api/spectrometer/channel_active", {"channel_id": ch, "active": (ch in active_channels)})


def _wait_for_new_spectrum_timestamp(
    client: RestClient,
    channel_id: str,
    previous_ts: str,
    poll_interval_s: float,
    timeout_s: float,
) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            payload = client.get(f"/api/spectrometer/spectrum/{urllib.parse.quote(channel_id)}")
        except RuntimeError:
            time.sleep(poll_interval_s)
            continue
        ts = str(payload.get("timestamp", "")).strip()
        if ts and ts != previous_ts:
            return ts
        time.sleep(poll_interval_s)
    raise TimeoutError(f"timeout waiting for new spectrum on {channel_id}")


def _build_scenarios(
    frame_averages: List[int],
    channel_modes: List[str],
    rl_modes: List[str],
    repeats: int,
) -> List[Dict]:
    scenarios = []
    for _ in range(repeats):
        for avg in frame_averages:
            for ch_mode in channel_modes:
                for rl_mode in rl_modes:
                    if ch_mode not in CHANNEL_PRESETS:
                        raise ValueError(f"Unsupported channel mode: {ch_mode}")
                    if rl_mode not in ("on", "off"):
                        raise ValueError(f"Unsupported RL mode: {rl_mode}")
                    scenarios.append(
                        {
                            "frame_average_n": int(avg),
                            "active_channels": CHANNEL_PRESETS[ch_mode],
                            "rl_enabled": (rl_mode == "on"),
                            "channel_mode": ch_mode,
                        }
                    )
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark driver for REST spectrometer API. "
            "Applies scenario parameters and requests one measurement per scenario."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Webserver base URL, e.g. http://192.168.10.1:8080")
    parser.add_argument("--frame-averages", default="1,2,4,8,16", help="Comma-separated processing_frame_average_n values")
    parser.add_argument("--channel-modes", default="ch0,ch2,both", help="Comma-separated channel modes: ch0,ch2,both")
    parser.add_argument("--rl-modes", default="off,on", help="Comma-separated RL modes: off,on")
    parser.add_argument("--rl-iterations", type=int, default=15, help="RL iterations value used when RL is enabled")
    parser.add_argument("--repeats", type=int, default=1, help="How many times to repeat full scenario matrix")
    parser.add_argument("--poll-interval", type=float, default=0.1, help="Polling interval for /spectrum/<channel_id> waits")
    parser.add_argument("--wait-timeout", type=float, default=20.0, help="Timeout for waiting on a new spectrum timestamp")
    parser.add_argument("--request-timeout", type=float, default=10.0, help="HTTP request timeout (seconds)")
    args = parser.parse_args()

    try:
        frame_averages = _parse_csv_ints(args.frame_averages)
        channel_modes = _parse_csv_strings(args.channel_modes)
        rl_modes = _parse_csv_strings(args.rl_modes)
        scenarios = _build_scenarios(frame_averages, channel_modes, rl_modes, max(1, args.repeats))
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2

    client = RestClient(args.base_url, timeout_s=max(1.0, float(args.request_timeout)))
    _preflight_api(client)

    # Avoid mixed capture modes before single-shot benchmark loop.
    try:
        client.post("/api/spectrometer/stop", {})
    except Exception as exc:
        _raise_connectivity_hint(args.base_url, exc)

    last_timestamp = {"ch0": "", "ch2": ""}

    print(f"Running {len(scenarios)} measurement scenarios")
    for idx, sc in enumerate(scenarios, start=1):
        avg = sc["frame_average_n"]
        active = sc["active_channels"]
        rl_enabled = sc["rl_enabled"]
        watch_channel = active[0]

        client.post("/api/spectrometer/processing_frame_average_n", {"value": avg})
        _set_channels(client, active)
        client.post("/api/spectrometer/processing_richardson_lucy_enabled", {"value": _bool_text(rl_enabled)})
        if rl_enabled:
            client.post("/api/spectrometer/processing_richardson_lucy_iterations", {"value": int(args.rl_iterations)})

        client.post("/api/spectrometer/single", {})
        new_ts = _wait_for_new_spectrum_timestamp(
            client=client,
            channel_id=watch_channel,
            previous_ts=last_timestamp.get(watch_channel, ""),
            poll_interval_s=max(0.01, args.poll_interval),
            timeout_s=max(1.0, args.wait_timeout),
        )
        last_timestamp[watch_channel] = new_ts

        print(
            f"[{idx:03d}/{len(scenarios):03d}] "
            f"avg={avg:<4d} channels={'+'.join(active):<7s} "
            f"rl={'on' if rl_enabled else 'off':<3s} "
            f"ts={new_ts}"
        )

    print("Benchmark scenario loop complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
