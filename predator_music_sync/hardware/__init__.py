from .base import KeyboardControllerBase
from .virtual_keyboard import VirtualKeyboardBackend
from .acer_pipe_windows import AcerLightingNamedPipeBackend
from .acer_wmi_windows import WindowsAcerWmiBackend
from .acer_linux import LinuxAcerBackend
from .factory import get_keyboard_controller, get_detected_model_info
from .device_detector import (
    detect_laptop_model,
    set_mock_laptop_model,
    clear_mock_laptop_model,
    KeyboardType,
    LaptopModelInfo,
    map_4zone_to_n,
    map_auxiliary_device_colors
)

__all__ = [
    "KeyboardControllerBase",
    "VirtualKeyboardBackend",
    "AcerLightingNamedPipeBackend",
    "WindowsAcerWmiBackend",
    "LinuxAcerBackend",
    "get_keyboard_controller",
    "get_detected_model_info",
    "detect_laptop_model",
    "set_mock_laptop_model",
    "clear_mock_laptop_model",
    "KeyboardType",
    "LaptopModelInfo",
    "map_4zone_to_n",
    "map_auxiliary_device_colors"
]
