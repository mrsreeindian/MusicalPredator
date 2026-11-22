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
        self._creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
        self._startupinfo = None
        if sys.platform == "win32":
            self._startupinfo = subprocess.STARTUPINFO()
            self._startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self._startupinfo.wShowWindow = subprocess.SW_HIDE
        self._init_wmi()

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

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        """
        Sets a specific zone's color using Acer's SetGamingLEDBehavior command.
        Zone bitmask is shifted by 8 bits, RGB shifted by 16, 24, 32 bits.
        """
        if not (0 <= zone < self.NUM_ZONES):
            return False

        scale = self._brightness / 100.0
        r_sc = int(max(0, min(255, r)) * scale)
        g_sc = int(max(0, min(255, g)) * scale)
        b_sc = int(max(0, min(255, b)) * scale)
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

        scale = self._brightness / 100.0
        for i in range(self.NUM_ZONES):
            r, g, b = colors[i]
            self._current_colors[i] = (
                int(max(0, min(255, r)) * scale),
                int(max(0, min(255, g)) * scale),
                int(max(0, min(255, b)) * scale)
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
