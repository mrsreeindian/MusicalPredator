"""
Hardware Controller Factory
Detects the OS and hardware platform, returning the appropriate 4-zone RGB controller.
Prioritizes the zero-elevation AcerLightingNamedPipeBackend on Windows.
"""

import sys
import platform
from typing import Optional, Callable, List, Tuple
from .base import KeyboardControllerBase
from .virtual_keyboard import VirtualKeyboardBackend
from .device_detector import detect_laptop_model, LaptopModelInfo

def get_detected_model_info() -> LaptopModelInfo:
    """Returns the auto-detected laptop model profile."""
    return detect_laptop_model()

def get_keyboard_controller(
    prefer_virtual: bool = False,
    on_update_callback: Optional[Callable[[List[Tuple[int, int, int]]], None]] = None
) -> KeyboardControllerBase:
    """
    Factory function to get the appropriate keyboard controller.
    Detects hardware laptop model and configures the controller profile.
    """
    model_info = detect_laptop_model()

    if prefer_virtual:
        vk = VirtualKeyboardBackend(on_update_callback=on_update_callback)
        vk.model_info = model_info
        return vk

    system = platform.system().lower()

    if "windows" in system:
        # 1. Primary: Direct Named Pipe client to Acer Lighting Service (No Admin required!)
        try:
            from .acer_pipe_windows import AcerLightingNamedPipeBackend
            pipe_backend = AcerLightingNamedPipeBackend()
            pipe_backend.model_info = model_info
            if pipe_backend.is_connected:
                return pipe_backend
        except Exception:
            pass

        # 2. Secondary: Acer WMI backend (requires elevation)
        try:
            from .acer_wmi_windows import WindowsAcerWmiBackend
            wmi_backend = WindowsAcerWmiBackend()
            wmi_backend.model_info = model_info
            if wmi_backend.is_connected:
                return wmi_backend
        except Exception:
            pass

    elif "linux" in system:
        try:
            from .acer_linux import LinuxAcerBackend
            backend = LinuxAcerBackend()
            backend.model_info = model_info
            if backend.is_connected:
                return backend
        except Exception:
            pass

    # Fallback to Virtual Controller
    vk = VirtualKeyboardBackend(on_update_callback=on_update_callback)
    vk.model_info = model_info
    return vk
