"""
Virtual Simulated 4-Zone RGB Keyboard Backend
Used for real-time visualization, testing, multi-pass benchmarking, and fallback.
"""

import time
from typing import List, Tuple, Optional, Callable, Dict, Any
from .base import KeyboardControllerBase
from .device_detector import (
    detect_laptop_model,
    KeyboardType,
    LaptopModelInfo,
    map_4zone_to_n,
    map_auxiliary_device_colors
)

class VirtualKeyboardBackend(KeyboardControllerBase):
    """
    Virtual in-memory 4-zone RGB keyboard with precise telemetry,
    callback notifications for GUI rendering, and dispatch benchmarking.
    Supports dynamic laptop model profiles (Per-Key RGB, 4-Zone, 3-Zone, 1-Zone, and auxiliary devices).
    """

    map_4zone_to_n = staticmethod(map_4zone_to_n)
    map_auxiliary_device_colors = staticmethod(map_auxiliary_device_colors)

    def __init__(self, on_update_callback: Optional[Callable[[List[Tuple[int, int, int]]], None]] = None):
        super().__init__()
        self._is_connected = True
        self._on_update = on_update_callback
        self._frame_count: int = 0
        self._last_dispatch_time: float = 0.0
        self._dispatch_latencies: List[float] = []
        self._current_mode: int = 0  # 0: custom/static

        # Dynamic model info & device expansion
        self.model_info: LaptopModelInfo = detect_laptop_model()
        self.sync_auxiliary: bool = True
        self.devices: List[Dict[str, Any]] = []
        self.primary_led_count: int = self.model_info.zone_count
        self.refresh_devices()

    def refresh_devices(self):
        """Refreshes simulated devices matching the active laptop model."""
        self.model_info = detect_laptop_model()
        kb_zones = self.model_info.zone_count if self.model_info else 4
        self.devices = [{
            "index": 0,
            "name": "Keyboard",
            "type": "Keyboard",
            "led_count": kb_zones,
            "is_per_key": (kb_zones > 4)
        }]
        if self.model_info and self.model_info.has_rear_lightbar:
            self.devices.append({
                "index": 1,
                "name": "Rear Lightbar",
                "type": "Lightbar",
                "led_count": 12,
                "is_per_key": False
            })
        if self.model_info and self.model_info.has_lid_logo:
            self.devices.append({
                "index": 2,
                "name": "Lid Logo",
                "type": "Logo",
                "led_count": 1,
                "is_per_key": False
            })
        self.primary_led_count = kb_zones

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def average_latency_ms(self) -> float:
        if not self._dispatch_latencies:
            return 0.0
        return (sum(self._dispatch_latencies) / len(self._dispatch_latencies)) * 1000.0

    def set_update_callback(self, callback: Callable[[List[Tuple[int, int, int]]], None]):
        self._on_update = callback

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        t0 = time.perf_counter()
        if 0 <= zone < self.NUM_ZONES:
            scale = self._brightness / 100.0
            r_scaled = int(max(0, min(255, r)) * scale)
            g_scaled = int(max(0, min(255, g)) * scale)
            b_scaled = int(max(0, min(255, b)) * scale)
            self._current_colors[zone] = (r_scaled, g_scaled, b_scaled)
            self._frame_count += 1
            if self._on_update:
                self._on_update(list(self._current_colors))
            lat = time.perf_counter() - t0
            self._dispatch_latencies.append(lat)
            if len(self._dispatch_latencies) > 200:
                self._dispatch_latencies.pop(0)
            return True
        return False

    def set_all_zones(self, colors: List[Tuple[int, int, int]], is_beat: bool = False, sync: bool = False, **kwargs) -> bool:
        t0 = time.perf_counter()
        scale = self._brightness / 100.0
        for i in range(min(self.NUM_ZONES, len(colors))):
            r, g, b = colors[i]
            r_scaled = int(max(0, min(255, r)) * scale)
            g_scaled = int(max(0, min(255, g)) * scale)
            b_scaled = int(max(0, min(255, b)) * scale)
            self._current_colors[i] = (r_scaled, g_scaled, b_scaled)
        self._frame_count += 1
        if self._on_update:
            self._on_update(list(self._current_colors))
        lat = time.perf_counter() - t0
        self._dispatch_latencies.append(lat)
        if len(self._dispatch_latencies) > 200:
            self._dispatch_latencies.pop(0)
        return True

    def set_hardware_mode(self, mode: int, speed: int, brightness: int, direction: int, r: int, g: int, b: int) -> bool:
        self._current_mode = mode
        self._brightness = brightness
        return True

    def close(self):
        self._is_connected = False
