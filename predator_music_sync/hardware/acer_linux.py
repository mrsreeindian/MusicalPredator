"""
Linux Keyboard Backend for Acer Predator Helios Laptops
Compatible with the 'acer-predator-turbo-and-rgb-keyboard-linux-module' (facer / acer-wmi)
"""

import os
from typing import List, Tuple
from .base import KeyboardControllerBase

class LinuxAcerBackend(KeyboardControllerBase):
    """
    Communicates with the Linux kernel module character device or sysfs nodes.
    Supports /dev/acer-gkbbl-static and /sys/devices/platform/acer-wmi/.
    """

    CHAR_DEV_PATH = "/dev/acer-gkbbl-static"
    SYSFS_BASE = "/sys/devices/platform/acer-wmi"

    def __init__(self):
        super().__init__()
        self._dev_fd = None
        self._init_driver()

    def _init_driver(self):
        try:
            if os.path.exists(self.CHAR_DEV_PATH):
                self._dev_fd = open(self.CHAR_DEV_PATH, "wb", buffering=0)
                self._is_connected = True
            elif os.path.exists(self.SYSFS_BASE):
                self._is_connected = True
        except Exception:
            self._is_connected = False

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        if not (0 <= zone < self.NUM_ZONES):
            return False

        scale = self._brightness / 100.0
        r_sc = int(max(0, min(255, r)) * scale)
        g_sc = int(max(0, min(255, g)) * scale)
        b_sc = int(max(0, min(255, b)) * scale)
        self._current_colors[zone] = (r_sc, g_sc, b_sc)

        if self._dev_fd:
            try:
                # 4-byte payload: [zone_mask, R, G, B]
                zone_mask = 1 << zone
                payload = bytes([zone_mask, r_sc, g_sc, b_sc])
                self._dev_fd.write(payload)
                return True
            except Exception:
                return False
        return False

    def set_all_zones(self, colors: List[Tuple[int, int, int]]) -> bool:
        if len(colors) < self.NUM_ZONES:
            return False

        ok = True
        for z in range(self.NUM_ZONES):
            r, g, b = colors[z]
            if not self.set_zone_color(z, r, g, b):
                ok = False
        return ok

    def set_hardware_mode(self, mode: int, speed: int, brightness: int, direction: int, r: int, g: int, b: int) -> bool:
        self._brightness = brightness
        # On Linux with character devices, effects can be controlled via /dev/acer-gkbbl-effect or sysfs
        effect_node = "/dev/acer-gkbbl-effect"
        if os.path.exists(effect_node):
            try:
                with open(effect_node, "wb") as f:
                    payload = bytes([mode, speed, brightness, direction, r, g, b])
                    f.write(payload)
                return True
            except Exception:
                pass
        return False

    def close(self):
        if self._dev_fd:
            try:
                self._dev_fd.close()
            except Exception:
                pass
            self._dev_fd = None
        self._is_connected = False
