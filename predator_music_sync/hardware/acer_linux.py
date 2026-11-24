"""
Linux Keyboard Backend for Acer Predator Helios Laptops
Compatible with the 'acer-predator-turbo-and-rgb-keyboard-linux-module' (facer / acer-wmi)
"""

import glob
import os
from typing import List, Optional, Tuple
from .base import KeyboardControllerBase

class LinuxAcerBackend(KeyboardControllerBase):
    """
    Communicates with the Linux kernel module character device or sysfs nodes.
    Supports /dev/acer-gkbbl-static, /sys/devices/platform/acer-wmi/,
    and Linux LED sysfs keyboard backlight brightness nodes.
    """

    CHAR_DEV_PATH = "/dev/acer-gkbbl-static"
    SYSFS_BASE = "/sys/devices/platform/acer-wmi"
    SYSFS_KBD_BACKLIGHT_GLOB = "/sys/class/leds/*kbd_backlight"

    def __init__(self):
        super().__init__()
        self._dev_fd = None
        self._sysfs_led_dir: Optional[str] = None
        self._init_driver()

    def _init_driver(self):
        try:
            if os.path.exists(self.CHAR_DEV_PATH):
                self._dev_fd = open(self.CHAR_DEV_PATH, "wb", buffering=0)
                self._is_connected = True
            elif os.path.exists(self.SYSFS_BASE):
                self._is_connected = True
            candidates = glob.glob(self.SYSFS_KBD_BACKLIGHT_GLOB)
            if candidates:
                self._sysfs_led_dir = candidates[0]
                hw_b = self.get_hardware_brightness()
                if hw_b is not None:
                    self._hw_brightness_level = hw_b
                    self._brightness = hw_b
        except Exception:
            self._is_connected = False

    @property
    def supports_hardware_brightness(self) -> bool:
        return bool(self._sysfs_led_dir or os.path.exists("/dev/acer-gkbbl-effect"))

    def get_hardware_brightness(self) -> Optional[int]:
        if not self._sysfs_led_dir:
            return None
        try:
            b_path = os.path.join(self._sysfs_led_dir, "brightness")
            m_path = os.path.join(self._sysfs_led_dir, "max_brightness")
            with open(b_path, "r", encoding="utf-8") as f:
                cur = int(f.read().strip())
            max_b = 100
            if os.path.exists(m_path):
                with open(m_path, "r", encoding="utf-8") as f:
                    max_b = max(1, int(f.read().strip()))
            pct = max(0, min(100, int(round((cur / float(max_b)) * 100.0))))
            self._hw_brightness_level = pct
            return pct
        except Exception:
            return None

    def set_hardware_brightness(self, level: int) -> bool:
        val = max(0, min(100, int(level)))
        self._brightness = val
        if self._sysfs_led_dir:
            try:
                b_path = os.path.join(self._sysfs_led_dir, "brightness")
                m_path = os.path.join(self._sysfs_led_dir, "max_brightness")
                max_b = 100
                if os.path.exists(m_path):
                    with open(m_path, "r", encoding="utf-8") as f:
                        max_b = max(1, int(f.read().strip()))
                raw_val = int(round((val / 100.0) * max_b))
                with open(b_path, "w", encoding="utf-8") as f:
                    f.write(str(raw_val))
                self._hw_brightness_level = val
                return True
            except Exception:
                return False
        return False

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        val = max(0, min(100, int(value)))
        if val != self._brightness:
            self._brightness = val
            if self.physical_brightness_enabled and self._sysfs_led_dir:
                self.set_hardware_brightness(val)

    def _effective_scale(self) -> float:
        if self._brightness <= 0:
            return 0.0
        hw_b = getattr(self, "_hw_brightness_level", None)
        if self.physical_brightness_enabled and hw_b is not None and hw_b > 0:
            return min(1.0, self._brightness / float(hw_b))
        return self._brightness / 100.0

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        if not (0 <= zone < self.NUM_ZONES):
            return False

        scale = self._effective_scale()
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
