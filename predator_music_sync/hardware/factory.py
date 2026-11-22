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

def get_keyboard_controller(
    prefer_virtual: bool = False,
    on_update_callback: Optional[Callable[[List[Tuple[int, int, int]]], None]] = None
) -> KeyboardControllerBase:
    """
    Factory function to get the appropriate keyboard controller.
    """
    if prefer_virtual:
        return VirtualKeyboardBackend(on_update_callback=on_update_callback)

    system = platform.system().lower()

    if "windows" in system:
        # 1. Primary: Direct Named Pipe client to Acer Lighting Service (No Admin required!)
        try:
            from .acer_pipe_windows import AcerLightingNamedPipeBackend
            pipe_backend = AcerLightingNamedPipeBackend()
            if pipe_backend.is_connected:
                return pipe_backend
        except Exception:
            pass

        # 2. Secondary: Acer WMI backend (requires elevation)
        try:
            from .acer_wmi_windows import WindowsAcerWmiBackend
            wmi_backend = WindowsAcerWmiBackend()
            if wmi_backend.is_connected:
                return wmi_backend
        except Exception:
            pass

    elif "linux" in system:
        try:
            from .acer_linux import LinuxAcerBackend
            backend = LinuxAcerBackend()
            if backend.is_connected:
                return backend
        except Exception:
            pass

    # Fallback to Virtual Controller
    return VirtualKeyboardBackend(on_update_callback=on_update_callback)
