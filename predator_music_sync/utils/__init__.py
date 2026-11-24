"""
Utility modules for Predator Music Sync.
"""
from .autostart import is_autostart_enabled, set_autostart, toggle_autostart
from .power import PowerMonitor, PowerStatus, SYSTEM_POWER_STATUS, set_process_power_throttling

__all__ = [
    "is_autostart_enabled",
    "set_autostart",
    "toggle_autostart",
    "PowerMonitor",
    "PowerStatus",
    "SYSTEM_POWER_STATUS",
    "set_process_power_throttling",
]
