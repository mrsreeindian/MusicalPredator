"""
Windows Acer WMI Keyboard Backend
Reverse-engineered and adapted from Acer-P-Helper (WmiController.cs)
Controls 4-zone RGB lighting on Acer Predator Helios Neo 16 (PHN16-71) via root\\WMI AcerGamingFunction.
"""

import time
import sys
import subprocess
from typing import List, Tuple, Optional
from .base import KeyboardControllerBase

class WindowsAcerWmiBackend(KeyboardControllerBase):
    r"""
    Communicates with Acer ACPI-WMI driver via AcerGamingFunction.
    Requires Administrator privileges on Windows for direct root\WMI access.
    """

    ZONE_MASKS = {
        0: 0x01,  # Zone 1 (Far Left / WASD)
        1: 0x02,  # Zone 2 (Center Left)
        2: 0x04,  # Zone 3 (Center Right)
        3: 0x08,  # Zone 4 (Far Right / Numpad)
        "middle": 0x06,  # Zones 2 & 3 (0x02 | 0x04)
        "outer": 0x09,   # Zones 1 & 4 (0x01 | 0x08)
        "all": 0x0F      # All 4 zones
    }

    def __init__(self):
        super().__init__()
        self._wmi_available = False
        self._unscaled_colors: List[Tuple[int, int, int]] = [(0, 0, 0)] * self.NUM_ZONES
        self._creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
        self._startupinfo = None
        if sys.platform == "win32":
            self._startupinfo = subprocess.STARTUPINFO()
            self._startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self._startupinfo.wShowWindow = subprocess.SW_HIDE
        self._init_wmi()
        if self._wmi_available:
            hw_b = self.get_hardware_brightness()
            if hw_b is not None:
                self._hw_brightness_level = hw_b
                self._brightness = hw_b

    @property
    def supports_hardware_brightness(self) -> bool:
        return self._wmi_available

    def _effective_scale(self) -> float:
        if self._brightness <= 0:
            return 0.0
        hw_b = getattr(self, "_hw_brightness_level", None)
        if self.physical_brightness_enabled and hw_b is not None and hw_b > 0:
            return min(1.0, self._brightness / float(hw_b))
        return self._brightness / 100.0

    def get_hardware_brightness(self) -> Optional[int]:
        """Queries physical EC keyboard backlight brightness via AcerGamingFunction.GetGamingKBBacklight."""
        if not self._wmi_available:
            return None
        ps_script = r"""
        $obj = Get-CimInstance -Namespace 'root\WMI' -ClassName 'AcerGamingFunction' -ErrorAction Stop
        $bytes = [byte[]](0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)
        $res = Invoke-CimMethod -InputObject $obj -MethodName 'GetGamingKBBacklight' -Arguments @{ gmInput = $bytes }
        if ($res.gmReturn -ne $null -and [int]$res.gmReturn -ne 0) { exit 1 }
        $out = [byte[]]$res.gmOutput
        if ($out.Length -ge 3) { Write-Output ([int]$out[2]); exit 0 }
        exit 1
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=self._creationflags,
                startupinfo=self._startupinfo
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                val = max(0, min(100, int(res.stdout.strip())))
                self._hw_brightness_level = val
                return val
        except Exception:
            pass
        return None

    def set_hardware_brightness(self, level: int) -> bool:
        """Sets physical EC keyboard backlight brightness via SetGamingKBBacklight."""
        val = max(0, min(100, int(level)))
        self._brightness = val
        if not self._wmi_available:
            return False
        primary = self._unscaled_colors[1] if len(self._unscaled_colors) > 1 else (255, 255, 255)
        ok = self.set_hardware_mode(0, 5, val, 1, primary[0], primary[1], primary[2])
        if ok:
            self._hw_brightness_level = val
        return ok

    def _init_wmi(self):
        r"""Test if root\WMI AcerGamingFunction is accessible."""
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                r"try { $o = Get-CimInstance -Namespace 'root\WMI' -ClassName 'AcerGamingFunction' -ErrorAction Stop; if ($o) { exit 0 } } catch { exit 1 }"
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=3,
                creationflags=self._creationflags,
                startupinfo=self._startupinfo
            )
            if res.returncode == 0:
                self._wmi_available = True
                self._is_connected = True
            else:
                self._wmi_available = False
                self._is_connected = False
        except Exception:
            self._wmi_available = False
            self._is_connected = False

    def _invoke_wmi_method(self, method_name: str, gm_input: int) -> bool:
        """Execute a WMI method on AcerGamingFunction with 64-bit uint input."""
        if not self._wmi_available:
            return False
        ps_script = f"""
        $obj = Get-CimInstance -Namespace 'root\\WMI' -ClassName 'AcerGamingFunction'
        $inParams = @{{ gmInput = [uint64]{gm_input} }}
        $res = Invoke-CimMethod -InputObject $obj -MethodName '{method_name}' -Arguments $inParams
        $out = [uint64]$res.gmOutput
        exit [int]($out -band 0xFF)
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=2,
                creationflags=self._creationflags,
                startupinfo=self._startupinfo
            )
            return res.returncode == 0
        except Exception:
            return False

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        val = max(0, min(100, int(value)))
        if val != self._brightness:
            self._brightness = val
            if self._wmi_available and self.physical_brightness_enabled:
                self.set_hardware_brightness(val)

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        """
        Sets a specific zone's color using Acer's SetGamingLEDBehavior command.
        Zone bitmask is shifted by 8 bits, RGB shifted by 16, 24, 32 bits.
        """
        if not (0 <= zone < self.NUM_ZONES):
            return False

        self._unscaled_colors[zone] = (
            max(0, min(255, int(r))),
            max(0, min(255, int(g))),
            max(0, min(255, int(b))),
        )
        scale = self._effective_scale()
        r_sc = int(self._unscaled_colors[zone][0] * scale)
        g_sc = int(self._unscaled_colors[zone][1] * scale)
        b_sc = int(self._unscaled_colors[zone][2] * scale)
        self._current_colors[zone] = (r_sc, g_sc, b_sc)

        mask = self.ZONE_MASKS[zone]
        # Command 0x06ul | (mask << 8) | (R << 16) | (G << 24) | (B << 32)
        payload = 0x06 | (mask << 8) | (r_sc << 16) | (g_sc << 24) | (b_sc << 32)
        return self._invoke_wmi_method("SetGamingLEDBehavior", payload)

    def set_all_zones(self, colors: List[Tuple[int, int, int]], is_beat: bool = False, sync: bool = False, **kwargs) -> bool:
        """
        Sets all 4 zones.
        First updates middle zones (Zone 2 & Zone 3), then outer zones (Zone 1 & Zone 4).
        """
        if len(colors) < self.NUM_ZONES:
            return False

        scale = self._effective_scale()
        for i in range(self.NUM_ZONES):
            r, g, b = colors[i]
            self._unscaled_colors[i] = (
                max(0, min(255, int(r))),
                max(0, min(255, int(g))),
                max(0, min(255, int(b))),
            )
            self._current_colors[i] = (
                int(self._unscaled_colors[i][0] * scale),
                int(self._unscaled_colors[i][1] * scale),
                int(self._unscaled_colors[i][2] * scale)
            )

        # First activate mode 7
        self._invoke_wmi_method("SetGamingLEDBehavior", 0x07)

        # Set individual zones 0, 1, 2, 3
        ok = True
        for z in range(self.NUM_ZONES):
            r, g, b = self._current_colors[z]
            mask = self.ZONE_MASKS[z]
            payload = 0x06 | (mask << 8) | (r << 16) | (g << 24) | (b << 32)
            if not self._invoke_wmi_method("SetGamingLEDBehavior", payload):
                ok = False
        return ok

    def set_hardware_mode(self, mode: int, speed: int, brightness: int, direction: int, r: int, g: int, b: int) -> bool:
        """
        Sets Acer hardware animation mode (0: Static, 1: Breathing, 2: Neon, 3: Wave,
        4: Shifting, 5: Zoom, 6: Meteor, 7: Twinkling) via SetGamingKBBacklight.
        """
        if not self._wmi_available:
            return False
        
        self._brightness = brightness
        # Reset behavior
        self._invoke_wmi_method("SetGamingLEDBehavior", 0x07)

        # Send byte array payload via PowerShell
        payload_bytes = [mode, speed, brightness, direction, 0, r, g, b, 0, 1] + [0] * 6
        bytes_str = ",".join(str(x) for x in payload_bytes)
        ps_script = f"""
        $obj = Get-CimInstance -Namespace 'root\\WMI' -ClassName 'AcerGamingFunction'
        $bytes = [byte[]]@({bytes_str})
        $inParams = @{{ gmInput = $bytes }}
        $res = Invoke-CimMethod -InputObject $obj -MethodName 'SetGamingKBBacklight' -Arguments $inParams
        $out = [uint64]$res.gmOutput
        exit [int]($out -band 0xFF)
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=2,
                creationflags=self._creationflags,
                startupinfo=self._startupinfo
            )
            return res.returncode == 0
        except Exception:
            return False

    def close(self):
        self._is_connected = False
