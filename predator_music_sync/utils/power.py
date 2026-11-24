"""
Power & Battery Management Subsystem for Windows (Acer Predator Helios Neo 16)
Queries Windows Win32 API 'GetSystemPowerStatus' via kernel32.
Provides zero-overhead background monitoring, dual power profiles (AC vs Battery),
and battery saver auto-suspension to preserve laptop battery life.
"""

import sys
import time
import ctypes
import threading
from ctypes import wintypes
from typing import Optional, Callable, Dict, Any, List


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ('ACLineStatus', wintypes.BYTE),         # 0 = Battery, 1 = AC, 255 = Unknown
        ('BatteryFlag', wintypes.BYTE),          # 1=High, 2=Low, 4=Critical, 8=Charging, 128=No battery
        ('BatteryLifePercent', wintypes.BYTE),   # 0..100, 255 = Unknown
        ('SystemStatusFlag', wintypes.BYTE),     # 1 = Battery Saver ON, 0 = OFF
        ('BatteryLifeTime', wintypes.DWORD),
        ('BatteryFullLifeTime', wintypes.DWORD),
    ]


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ('Version', wintypes.ULONG),
        ('ControlMask', wintypes.ULONG),
        ('StateMask', wintypes.ULONG),
    ]


PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
PROCESS_POWER_THROTTLING_INFORMATION = 4


def set_process_power_throttling(disable_throttling: bool = True) -> bool:
    """
    Opts the current process in or out of Windows 10/11 EcoQoS background throttling
    and timer resolution throttling (which Windows applies when all GUI windows are
    hidden/withdrawn to the system tray).

    When disable_throttling=True, sets ControlMask to EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION
    with StateMask=0 so 60 FPS background audio/LED sync and 1ms timers remain active in tray.
    When disable_throttling=False, clears ControlMask/StateMask to restore OS defaults.
    """
    if sys.platform != "win32":
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL

        mask = (
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION
        ) if disable_throttling else 0
        state = PROCESS_POWER_THROTTLING_STATE(
            Version=PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            ControlMask=mask,
            StateMask=0,
        )
        return bool(
            k32.SetProcessInformation(
                k32.GetCurrentProcess(),
                PROCESS_POWER_THROTTLING_INFORMATION,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        )
    except Exception:
        return False


class PowerStatus:
    """Immutable snapshot of the system's power and battery state."""

    def __init__(
        self,
        ac_line_status: int = 1,
        battery_flag: int = 1,
        battery_life_percent: int = 100,
        system_status_flag: int = 0
    ):
        self.ac_line_status = ac_line_status
        self.battery_flag = battery_flag
        self.battery_life_percent = battery_life_percent
        self.system_status_flag = system_status_flag

    @property
    def is_plugged_in(self) -> bool:
        """True if laptop is connected to AC wall power or status is unknown/desktop."""
        return self.ac_line_status != 0

    @property
    def is_on_battery(self) -> bool:
        """True strictly if laptop is running on DC battery power."""
        return self.ac_line_status == 0

    @property
    def is_battery_saver(self) -> bool:
        """True if Windows 10/11 Battery Saver mode is currently active."""
        return self.system_status_flag == 1

    @property
    def battery_percent(self) -> int:
        """Battery charge level (0-100), or -1 if unknown or no battery."""
        return int(self.battery_life_percent) if self.battery_life_percent <= 100 else -1

    @property
    def status_label(self) -> str:
        """Human-readable status label for UI and tray tooltip."""
        if self.is_battery_saver:
            return "Battery Saver (Suspended)"
        if self.is_on_battery:
            pct = self.battery_percent
            return f"On Battery ({pct}%)" if pct >= 0 else "On Battery"
        return "Plugged In"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_plugged_in": self.is_plugged_in,
            "is_on_battery": self.is_on_battery,
            "is_battery_saver": self.is_battery_saver,
            "battery_percent": self.battery_percent,
            "ac_line_status": self.ac_line_status,
            "battery_flag": self.battery_flag,
            "system_status_flag": self.system_status_flag,
            "status_label": self.status_label
        }

    def __repr__(self) -> str:
        return f"<PowerStatus {self.status_label} (AC={self.ac_line_status}, Batt={self.battery_percent}%, Saver={self.is_battery_saver})>"


class PowerMonitor:
    """
    Thread-safe, zero-overhead background monitor for system power changes.
    Polls Windows GetSystemPowerStatus every 1.5 seconds (~0.00% CPU)
    and dispatches callbacks on state transitions.
    """

    def __init__(
        self,
        poll_interval: float = 1.5,
        on_ac_power_change: Optional[Callable[[bool], None]] = None,
        on_battery_saver_change: Optional[Callable[[bool], None]] = None,
        on_battery_percent_change: Optional[Callable[[int], None]] = None,
        on_system_resume: Optional[Callable[[], None]] = None,
    ):
        self.poll_interval = max(0.5, float(poll_interval))

        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._ac_callbacks: List[Callable[[bool], None]] = []
        if on_ac_power_change:
            self._ac_callbacks.append(on_ac_power_change)

        self._saver_callbacks: List[Callable[[bool], None]] = []
        if on_battery_saver_change:
            self._saver_callbacks.append(on_battery_saver_change)

        self._percent_callbacks: List[Callable[[int], None]] = []
        if on_battery_percent_change:
            self._percent_callbacks.append(on_battery_percent_change)

        self._resume_callbacks: List[Callable[[], None]] = []
        if on_system_resume:
            self._resume_callbacks.append(on_system_resume)

        self._last_status: Optional[PowerStatus] = None
        self._mock_status: Optional[PowerStatus] = None

    def add_resume_callback(self, cb: Callable[[], None]):
        with self._lock:
            if cb not in self._resume_callbacks:
                self._resume_callbacks.append(cb)

    def add_ac_power_callback(self, cb: Callable[[bool], None]):
        with self._lock:
            if cb not in self._ac_callbacks:
                self._ac_callbacks.append(cb)

    def add_battery_saver_callback(self, cb: Callable[[bool], None]):
        with self._lock:
            if cb not in self._saver_callbacks:
                self._saver_callbacks.append(cb)

    def add_battery_percent_callback(self, cb: Callable[[int], None]):
        with self._lock:
            if cb not in self._percent_callbacks:
                self._percent_callbacks.append(cb)

    def set_mock_status(
        self,
        is_plugged: bool,
        is_battery_saver: bool = False,
        percent: int = 100,
        battery_flag: int = 1
    ):
        """Allows test suites to mock Windows power states cleanly without hardware changes."""
        mock = PowerStatus(
            ac_line_status=1 if is_plugged else 0,
            battery_flag=battery_flag,
            battery_life_percent=percent,
            system_status_flag=1 if is_battery_saver else 0
        )
        with self._lock:
            self._mock_status = mock
        self._evaluate_state(mock)

    def clear_mock(self):
        """Clears test mock and reverts to live hardware Win32 queries."""
        with self._lock:
            self._mock_status = None
        current = self.get_status()
        self._evaluate_state(current)

    def _query_win32_power(self) -> PowerStatus:
        """Direct kernel32 GetSystemPowerStatus query."""
        if sys.platform != "win32":
            return PowerStatus(ac_line_status=1, battery_flag=1, battery_life_percent=100, system_status_flag=0)

        sps = SYSTEM_POWER_STATUS()
        try:
            res = ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps))
            if res:
                return PowerStatus(
                    ac_line_status=int(sps.ACLineStatus),
                    battery_flag=int(sps.BatteryFlag),
                    battery_life_percent=int(sps.BatteryLifePercent),
                    system_status_flag=int(sps.SystemStatusFlag)
                )
        except Exception:
            pass

        return PowerStatus(ac_line_status=1, battery_flag=1, battery_life_percent=100, system_status_flag=0)

    def get_status(self) -> PowerStatus:
        """Returns the current PowerStatus snapshot."""
        with self._lock:
            if self._mock_status is not None:
                return self._mock_status
        return self._query_win32_power()

    def start(self):
        """Starts the background power monitoring thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._last_status = self.get_status()
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="PowerMonitorThread")
            self._thread.start()

    def stop(self):
        """Stops the power monitoring thread cleanly."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=0.5)

    def _notify_resume(self):
        with self._lock:
            cbs = list(self._resume_callbacks)
        for cb in cbs:
            try:
                cb()
            except Exception:
                pass

    def _monitor_loop(self):
        prev_mono = time.monotonic()
        prev_wall = time.time()
        while True:
            with self._lock:
                if not self._running:
                    break
                interval = self.poll_interval

            # Sleep in small slices for instant shutdown
            slices = max(1, int(interval / 0.15))
            for _ in range(slices):
                time.sleep(0.15)
                with self._lock:
                    if not self._running:
                        return

            now_mono = time.monotonic()
            now_wall = time.time()
            mono_elapsed = now_mono - prev_mono
            wall_elapsed = now_wall - prev_wall
            prev_mono = now_mono
            prev_wall = now_wall

            # Detect S3 sleep / Modern Standby resume via monotonic jump or wall-clock drift
            if mono_elapsed > max(5.0, interval * 3.0) or abs(wall_elapsed - mono_elapsed) > 4.0:
                self._notify_resume()

            status = self.get_status()
            self._evaluate_state(status)

    def _evaluate_state(self, status: PowerStatus):
        """Compares current status against previous status and fires transition callbacks."""
        with self._lock:
            prev = self._last_status
            self._last_status = status
            ac_cbs = list(self._ac_callbacks)
            saver_cbs = list(self._saver_callbacks)
            pct_cbs = list(self._percent_callbacks)

        if prev is None:
            # First evaluation
            for cb in ac_cbs:
                try:
                    cb(status.is_plugged_in)
                except Exception:
                    pass
            for cb in saver_cbs:
                try:
                    cb(status.is_battery_saver)
                except Exception:
                    pass
            for cb in pct_cbs:
                try:
                    cb(status.battery_percent)
                except Exception:
                    pass
            return

        # Fire AC change if toggled
        if status.is_plugged_in != prev.is_plugged_in:
            for cb in ac_cbs:
                try:
                    cb(status.is_plugged_in)
                except Exception:
                    pass

        # Fire Battery Saver change if toggled
        if status.is_battery_saver != prev.is_battery_saver:
            for cb in saver_cbs:
                try:
                    cb(status.is_battery_saver)
                except Exception:
                    pass

        # Fire Battery Percent change if updated
        if status.battery_percent != prev.battery_percent:
            for cb in pct_cbs:
                try:
                    cb(status.battery_percent)
                except Exception:
                    pass
