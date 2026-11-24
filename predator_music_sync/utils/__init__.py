"""
Utility modules for Predator Music Sync.
"""
from .autostart import is_autostart_enabled, set_autostart, toggle_autostart
from .power import PowerMonitor, PowerStatus, SYSTEM_POWER_STATUS, set_process_power_throttling
from .updater import (
    RuntimeMode,
    SemVer,
    ReleaseAsset,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateConfig,
    UpdateManager,
    UpdateError,
    UpdateNetworkError,
    UpdateRateLimitError,
    UpdateNotFoundError,
    UpdateVerificationError,
    UpdateCancelledError,
    parse_version,
    is_newer_version,
    detect_runtime_mode,
)

__all__ = [
    "is_autostart_enabled",
    "set_autostart",
    "toggle_autostart",
    "PowerMonitor",
    "PowerStatus",
    "SYSTEM_POWER_STATUS",
    "set_process_power_throttling",
    "RuntimeMode",
    "SemVer",
    "ReleaseAsset",
    "ReleaseInfo",
    "UpdateCheckResult",
    "UpdateConfig",
    "UpdateManager",
    "UpdateError",
    "UpdateNetworkError",
    "UpdateRateLimitError",
    "UpdateNotFoundError",
    "UpdateVerificationError",
    "UpdateCancelledError",
    "parse_version",
    "is_newer_version",
    "detect_runtime_mode",
]
