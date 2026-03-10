"""
Modular output layer. Implement OutputAdapter for MQTT, WebSocket, REST, etc.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class OutputAdapter(ABC):
    @abstractmethod
    def send_spectrum(self, spectrum: Dict[str, Any]) -> None:
        """Send spectrum data. spectrum: {channel_id, timestamp, wavelengths_nm, intensities, meta}."""
        pass
