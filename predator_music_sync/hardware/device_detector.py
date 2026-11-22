"""
Universal Hardware Device Detector for Acer Predator & Nitro Laptops
Detects laptop model family and keyboard hardware capabilities:
- Predator Helios series (Helios Neo 16/18, Helios 16/18, Helios 300/500/700)
- Predator Triton series (Triton 14, 16, 17, 300, 500, 700, 900)
- Nitro series (Nitro 16, 17, Nitro 5, Nitro 7)
Determines RGB layout: 4-Zone RGB vs Per-Key RGB vs 3-Zone vs 1-Zone,
plus auxiliary devices (Rear Lightbar, Lid Logo).
"""

import os
import re
import sys
import winreg
import subprocess
from enum import Enum
from typing import Optional, List, Dict, Tuple, Any


class KeyboardType(Enum):
    ONE_ZONE_RGB = "1-Zone RGB"
    THREE_ZONE_RGB = "3-Zone RGB"
    FOUR_ZONE_RGB = "4-Zone RGB"
    PER_KEY_RGB = "Per-Key RGB"


class LaptopModelInfo:
    """Detailed specifications and capabilities for the detected laptop model."""

    def __init__(
        self,
        model_name: str,
        series: str,
        keyboard_type: KeyboardType,
        zone_count: int,
        key_count: int = 84,
        has_rear_lightbar: bool = False,
        has_lid_logo: bool = False,
        raw_product_name: str = "",
        is_predator: bool = True
    ):
        self.model_name = model_name
        self.series = series
        self.keyboard_type = keyboard_type
        self.zone_count = zone_count
        self.key_count = key_count
        self.has_rear_lightbar = has_rear_lightbar
        self.has_lid_logo = has_lid_logo
        self.raw_product_name = raw_product_name
        self.is_predator = is_predator

    @property
    def display_name(self) -> str:
        return f"{self.model_name} • {self.keyboard_type.value}"

    @property
    def is_per_key(self) -> bool:
        return self.keyboard_type == KeyboardType.PER_KEY_RGB

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "series": self.series,
            "keyboard_type": self.keyboard_type.value,
            "zone_count": self.zone_count,
            "key_count": self.key_count,
            "has_rear_lightbar": self.has_rear_lightbar,
            "has_lid_logo": self.has_lid_logo,
            "raw_product_name": self.raw_product_name,
            "is_predator": self.is_predator,
            "display_name": self.display_name
        }

    def __repr__(self) -> str:
        return f"<LaptopModelInfo {self.display_name} (zones={self.zone_count}, lightbar={self.has_rear_lightbar})>"


# Test mock state
_mock_model_info: Optional[LaptopModelInfo] = None


def set_mock_laptop_model(model_name: str):
    """Allows unit tests to simulate any Predator or Nitro laptop model."""
    global _mock_model_info
    _mock_model_info = parse_model_string(model_name)


def clear_mock_laptop_model():
    """Clears the mock model and reverts to live hardware detection."""
    global _mock_model_info
    _mock_model_info = None


def get_raw_system_product_name() -> str:
    """Queries Windows Registry for the system BIOS product name."""
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
                name, _ = winreg.QueryValueEx(key, "SystemProductName")
                if name:
                    return str(name).strip()
        except Exception:
            pass

        # Fallback to CIM query
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).Name"]
            out = subprocess.check_output(cmd, text=True, timeout=2.0).strip()
            if out:
                return out
        except Exception:
            pass

    return "Predator PHN16-71"


def parse_model_string(product_str: str) -> LaptopModelInfo:
    """
    Parses DMI product strings like 'Predator PHN16-71', 'Predator PH16-72',
    'Nitro AN515-58', 'Predator PT16-71' into model capabilities.
    """
    p_upper = product_str.upper()

    # =========================================================================
    # 1. PREDATOR HELIOS 16 / 18 (Flagship - Per-Key RGB + Rear Lightbar)
    # =========================================================================
    if re.search(r"PH16-\d+|PH18-\d+|HELIOS\s*(16|18)(?!\s*NEO)", p_upper):
        model_name = "Predator Helios 18" if "18" in p_upper else "Predator Helios 16"
        return LaptopModelInfo(
            model_name=model_name,
            series="Helios Flagship",
            keyboard_type=KeyboardType.PER_KEY_RGB,
            zone_count=84,
            key_count=84,
            has_rear_lightbar=True,
            has_lid_logo=True,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 2. PREDATOR HELIOS NEO 16 / 18 (Performance - 4-Zone RGB)
    # =========================================================================
    if re.search(r"PHN16-\d+|PHN18-\d+|HELIOS\s*NEO", p_upper):
        model_name = "Predator Helios Neo 18" if "18" in p_upper else "Predator Helios Neo 16"
        return LaptopModelInfo(
            model_name=model_name,
            series="Helios Neo",
            keyboard_type=KeyboardType.FOUR_ZONE_RGB,
            zone_count=4,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=False,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 3. PREDATOR HELIOS 500 / 700 (Ultra Desktop Replacement - Per-Key RGB)
    # =========================================================================
    if re.search(r"PH517|PH717|HELIOS\s*(500|700)", p_upper):
        model_name = "Predator Helios 700" if "7" in p_upper else "Predator Helios 500"
        return LaptopModelInfo(
            model_name=model_name,
            series="Helios Extreme",
            keyboard_type=KeyboardType.PER_KEY_RGB,
            zone_count=84,
            key_count=84,
            has_rear_lightbar=True,
            has_lid_logo=True,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 4. PREDATOR HELIOS 300 (Classic - 4-Zone RGB)
    # =========================================================================
    if re.search(r"PH315|PH317|HELIOS\s*300", p_upper):
        return LaptopModelInfo(
            model_name="Predator Helios 300",
            series="Helios 300",
            keyboard_type=KeyboardType.FOUR_ZONE_RGB,
            zone_count=4,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=False,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 5. PREDATOR TRITON 16 / 17 / 500 / 900 (Per-Key RGB)
    # =========================================================================
    if re.search(r"PT16|PT17|PT515|PT516|PT715|PT917|TRITON\s*(16|17|500|900)", p_upper):
        return LaptopModelInfo(
            model_name="Predator Triton 16/500",
            series="Triton",
            keyboard_type=KeyboardType.PER_KEY_RGB,
            zone_count=84,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=True,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 6. PREDATOR TRITON 14 / 300 / 300 SE (3-Zone RGB)
    # =========================================================================
    if re.search(r"PT14|PT314|PT315|TRITON\s*(14|300)", p_upper):
        return LaptopModelInfo(
            model_name="Predator Triton 300",
            series="Triton",
            keyboard_type=KeyboardType.THREE_ZONE_RGB,
            zone_count=3,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=False,
            raw_product_name=product_str,
            is_predator=True
        )

    # =========================================================================
    # 7. NITRO 16 / 17 (4-Zone RGB)
    # =========================================================================
    if re.search(r"AN16|AN17|NITRO\s*(16|17)", p_upper):
        model_name = "Acer Nitro 17" if "17" in p_upper else "Acer Nitro 16"
        return LaptopModelInfo(
            model_name=model_name,
            series="Nitro",
            keyboard_type=KeyboardType.FOUR_ZONE_RGB,
            zone_count=4,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=False,
            raw_product_name=product_str,
            is_predator=False
        )

    # =========================================================================
    # 8. NITRO 5 / 7 (4-Zone RGB or 1-Zone)
    # =========================================================================
    if re.search(r"AN515|AN517|AN715|NITRO\s*5|NITRO\s*7", p_upper):
        return LaptopModelInfo(
            model_name="Acer Nitro 5",
            series="Nitro",
            keyboard_type=KeyboardType.FOUR_ZONE_RGB,
            zone_count=4,
            key_count=84,
            has_rear_lightbar=False,
            has_lid_logo=False,
            raw_product_name=product_str,
            is_predator=False
        )

    # Default fallback: Predator Helios Neo 16
    return LaptopModelInfo(
        model_name="Predator Helios Neo 16",
        series="Helios Neo",
        keyboard_type=KeyboardType.FOUR_ZONE_RGB,
        zone_count=4,
        key_count=84,
        has_rear_lightbar=False,
        has_lid_logo=False,
        raw_product_name=product_str,
        is_predator=True
    )


def detect_laptop_model() -> LaptopModelInfo:
    """Auto-detects the active laptop model and hardware lighting capabilities."""
    global _mock_model_info
    if _mock_model_info is not None:
        return _mock_model_info

    product_name = get_raw_system_product_name()
    return parse_model_string(product_name)


def map_4zone_to_n(
    colors: List[Tuple[int, int, int]],
    n: int
) -> List[Tuple[int, int, int]]:
    """
    Dynamically maps 4 animation zone colors [Z1, Z2, Z3, Z4] across N physical device LEDs.

    Supports:
    - 4-Zone Keyboards (n = 4): direct 1:1 mapping [Z1, Z2, Z3, Z4]
    - 1-Zone Keyboards (n = 1): unified weighted average of all 4 zones
    - 3-Zone Keyboards (n = 3): [Z1, blend(Z2, Z3), Z4]
    - 2-Zone devices (n = 2): [blend(Z1, Z2), blend(Z3, Z4)]
    - Per-Key RGB Keyboards (n > 4, typically ~84 keys):
      Continuous spatial horizontal gradient mapping across the keyboard width using
      smoothstep Hermite interpolation (w = u^2 * (3 - 2u)) for fluid, natural color
      propagation across physical key rows without seams.
    """
    if n <= 0:
        return []
    if not colors:
        return [(0, 0, 0)] * n

    # Pad colors to at least 4 zones if fewer provided
    padded_colors = list(colors)
    while len(padded_colors) < 4:
        padded_colors.append(padded_colors[-1] if padded_colors else (0, 0, 0))

    # 1. 4-Zone Direct Mapping
    if n == 4:
        return [padded_colors[i] for i in range(4)]

    # 2. 1-Zone Unified Mapping
    if n == 1:
        r_avg = int(round(sum(padded_colors[i][0] for i in range(4)) / 4.0))
        g_avg = int(round(sum(padded_colors[i][1] for i in range(4)) / 4.0))
        b_avg = int(round(sum(padded_colors[i][2] for i in range(4)) / 4.0))
        return [(max(0, min(255, r_avg)), max(0, min(255, g_avg)), max(0, min(255, b_avg)))]

    # 3. 3-Zone Mapping (Triton 14, Triton 300, etc.)
    if n == 3:
        z0 = padded_colors[0]
        r_mid = int(round((padded_colors[1][0] + padded_colors[2][0]) / 2.0))
        g_mid = int(round((padded_colors[1][1] + padded_colors[2][1]) / 2.0))
        b_mid = int(round((padded_colors[1][2] + padded_colors[2][2]) / 2.0))
        z1 = (max(0, min(255, r_mid)), max(0, min(255, g_mid)), max(0, min(255, b_mid)))
        z2 = padded_colors[3]
        return [z0, z1, z2]

    # 4. 2-Zone Mapping
    if n == 2:
        r0 = int(round((padded_colors[0][0] + padded_colors[1][0]) / 2.0))
        g0 = int(round((padded_colors[0][1] + padded_colors[1][1]) / 2.0))
        b0 = int(round((padded_colors[0][2] + padded_colors[1][2]) / 2.0))
        r1 = int(round((padded_colors[2][0] + padded_colors[3][0]) / 2.0))
        g1 = int(round((padded_colors[2][1] + padded_colors[3][1]) / 2.0))
        b1 = int(round((padded_colors[2][2] + padded_colors[3][2]) / 2.0))
        return [
            (max(0, min(255, r0)), max(0, min(255, g0)), max(0, min(255, b0))),
            (max(0, min(255, r1)), max(0, min(255, g1)), max(0, min(255, b1)))
        ]

    # 5. Per-Key RGB Mapping (n > 4 keys, e.g. 84 or 104 keys)
    # Piecewise smoothstep gradient across normalized keyboard width [0.0, 1.0]
    out: List[Tuple[int, int, int]] = []
    denom = float(n - 1)

    for k in range(n):
        t = k / denom  # 0.0 to 1.0

        if t <= (1.0 / 3.0):
            u = t * 3.0
            c_from = padded_colors[0]
            c_to = padded_colors[1]
        elif t <= (2.0 / 3.0):
            u = (t - (1.0 / 3.0)) * 3.0
            c_from = padded_colors[1]
            c_to = padded_colors[2]
        else:
            u = (t - (2.0 / 3.0)) * 3.0
            c_from = padded_colors[2]
            c_to = padded_colors[3]

        # Smoothstep curve for seamless transition across physical keys
        u_clamped = max(0.0, min(1.0, u))
        w = u_clamped * u_clamped * (3.0 - 2.0 * u_clamped)

        r = int(round(c_from[0] + (c_to[0] - c_from[0]) * w))
        g = int(round(c_from[1] + (c_to[1] - c_from[1]) * w))
        b = int(round(c_from[2] + (c_to[2] - c_from[2]) * w))

        out.append((max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))))

    return out


def map_auxiliary_device_colors(
    colors: List[Tuple[int, int, int]],
    led_count: int,
    is_beat: bool = False
) -> List[Tuple[int, int, int]]:
    """
    Maps colors for auxiliary devices (Rear Lightbar, Lid Logo).
    - If is_beat is True: pulses energetically with primary beat color (Zone 2).
    - Rear Lightbar (multi-LED): renders a symmetric gradient centered on Zone 2/3.
    - Lid Logo (single-LED): synchronizes to primary beat/accent color (Zone 2).
    """
    if led_count <= 0:
        return []
    if not colors:
        return [(0, 0, 0)] * led_count

    padded_colors = list(colors)
    while len(padded_colors) < 4:
        padded_colors.append(padded_colors[-1] if padded_colors else (0, 0, 0))

    primary_accent = padded_colors[1]  # Zone 2 (Center-Left / Beat Transient)
    secondary_accent = padded_colors[2]  # Zone 3 (Center-Right / Mid Harmonic)

    if led_count <= 1:
        return [primary_accent]

    # Multi-LED auxiliary device (e.g. 12-LED or 16-LED Rear Lightbar)
    # If beat: intense flash of primary accent
    if is_beat:
        return [primary_accent] * led_count

    # Symmetric sweep/gradient centered at middle of the lightbar
    out: List[Tuple[int, int, int]] = []
    denom = float(max(1, led_count - 1))

    for i in range(led_count):
        norm_pos = i / denom
        dist_from_center = abs(norm_pos - 0.5) * 2.0  # 0.0 (center) to 1.0 (edge)

        # Center is primary_accent (Zone 2), edges blend towards secondary_accent (Zone 3)
        w = dist_from_center * dist_from_center  # Quadratic falloff
        r = int(round(primary_accent[0] + (secondary_accent[0] - primary_accent[0]) * w))
        g = int(round(primary_accent[1] + (secondary_accent[1] - primary_accent[1]) * w))
        b = int(round(primary_accent[2] + (secondary_accent[2] - primary_accent[2]) * w))
        out.append((max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))))

    return out

