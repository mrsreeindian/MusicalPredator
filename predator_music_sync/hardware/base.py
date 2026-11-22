"""
Base Hardware Controller Interface for 4-Zone RGB Keyboards
Target: Acer Predator Helios Neo 16 (PHN16-71) & compatible models.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple

class KeyboardControllerBase(ABC):
    """
    Abstract interface for 4-zone RGB keyboard hardware backends.
    Zones are 0-indexed:
      0: Zone 1 (Left - WASD area)
      1: Zone 2 (Center-Left - Middle area 1)
      2: Zone 3 (Center-Right - Middle area 2)
      3: Zone 4 (Right - Numpad area)
    """

    NUM_ZONES = 4

    def __init__(self):
        self._current_colors: List[Tuple[int, int, int]] = [(0, 0, 0)] * self.NUM_ZONES
        self._brightness: int = 100
        self._is_connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def current_colors(self) -> List[Tuple[int, int, int]]:
        return list(self._current_colors)

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        self._brightness = max(0, min(100, int(value)))

    @abstractmethod
    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> bool:
        """Set RGB color for a specific zone (0 to 3)."""
        pass

    @abstractmethod
    def set_all_zones(self, colors: List[Tuple[int, int, int]], is_beat: bool = False, sync: bool = False, **kwargs) -> bool:
        """Set RGB colors for all 4 zones at once: [Zone1, Zone2, Zone3, Zone4]."""
        pass

    @abstractmethod
    def set_hardware_mode(self, mode: int, speed: int, brightness: int, direction: int, r: int, g: int, b: int) -> bool:
        """Set built-in hardware lighting mode (Static, Breathing, Wave, etc.)."""
        pass

    @abstractmethod
    def close(self):
        """Release any hardware handles or resources."""
        pass
