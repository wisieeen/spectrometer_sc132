"""
Signal processing modules for spectrometer enhancement.
Each technique is independent and can be toggled via MQTT.
"""
from .dark_flat import apply_dark_flat_frame, load_dark_flat
from .wiener import wiener_deconvolve
from .richardson_lucy import richardson_lucy_deconvolve

__all__ = [
    "apply_dark_flat_frame",
    "load_dark_flat",
    "wiener_deconvolve",
    "richardson_lucy_deconvolve",
]
