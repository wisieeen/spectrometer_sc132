"""
MQTT output adapter. Publishes spectrum JSON to {state_topic}spectrum/{channel_id}.
"""
import json
from typing import Any, Dict

import paho.mqtt.client as mqtt

from .base import OutputAdapter


class MQTTAdapter(OutputAdapter):
    def __init__(
        self,
        broker: str,
        port: int,
        user: str,
        password: str,
        state_topic: str,
    ):
        self._client = mqtt.Client()
        self._client.username_pw_set(user, password)
        self._client.connect(broker, port, 60)
        self._client.loop_start()
        self._state_topic = state_topic.rstrip("/") + "/"

    def send_spectrum(self, spectrum: Dict[str, Any]) -> None:
        if not isinstance(spectrum, dict):
            return
        if "wavelengths_nm" not in spectrum or "intensities" not in spectrum:
            return
        channel_id = spectrum.get("channel_id", "unknown")
        channel_id = str(channel_id) if channel_id is not None else "unknown"
        topic = f"{self._state_topic}spectrum/{channel_id}"
        payload = json.dumps(spectrum)
        self._client.publish(topic, payload)
