"""
Windows Acer Lighting Service Named Pipe Controller
Communicates directly with \\\\.\\pipe\\AcerLightingService_NamedPipe to control
the 4-zone RGB keyboard on Acer Predator Helios Neo 16 (PHN16-71) in user space without requiring Administrator privileges.

Features:
- Ultra-responsive, non-blocking hardware transmitter (<0.01ms dispatch latency).
- Zero-lag latest-frame sampling: worker thread always transmits the freshest animation state.
- Proactive beat-latching: locks audio beat transients so 120-160ms ACPI EC transactions never drop musical beats.
- Smooth delta interpolation: eliminates stepped color jumping between EC updates for fluid 60 FPS visual continuity.
- High-efficiency adaptive dirty checking with auto-settling to eliminate bus saturation while guaranteeing 0-error resting colors.
- Thread-safe atomic pipe operations with robust 64-bit handle validation and auto-recovery.
"""

import os
import sys
import struct
import ctypes
import threading
import time
import math
from ctypes import wintypes
from typing import List, Tuple, Optional, Dict, Any
from .base import KeyboardControllerBase
from .device_detector import (
    detect_laptop_model,
    KeyboardType,
    LaptopModelInfo,
    map_4zone_to_n,
    map_auxiliary_device_colors
)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3

kernel32 = ctypes.windll.kernel32

# Configure ctypes prototypes for 64-bit Windows compatibility
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p
]
kernel32.WriteFile.restype = wintypes.BOOL

kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p
]
kernel32.ReadFile.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.PeekNamedPipe.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.PeekNamedPipe.restype = wintypes.BOOL

kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel32.WaitNamedPipeW.restype = wintypes.BOOL

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class AcerLightingNamedPipeBackend(KeyboardControllerBase):
    """
    Direct client for AcerLightingService_NamedPipe with zero-latency priority frame dispatch,
    proactive beat latching, smooth delta interpolation between hardware EC bus writes,
    and dynamic zone expansion across all Predator and Nitro laptop models.
    """

    PIPE_NAME = r"\\.\pipe\AcerLightingService_NamedPipe"

    map_4zone_to_n = staticmethod(map_4zone_to_n)
    map_auxiliary_device_colors = staticmethod(map_auxiliary_device_colors)

    def __init__(self, device_index: int = 0):
        super().__init__()
        self.device_index = device_index
        self._pipe_handle = INVALID_HANDLE_VALUE
        self._is_connected = False

        # Model detection & dynamic device enumeration
        self.model_info: LaptopModelInfo = detect_laptop_model()
        self.devices: List[Dict[str, Any]] = []
        self.primary_led_count: int = self.model_info.zone_count
        self.sync_auxiliary: bool = True

        # Thread synchronization
        self._pipe_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._frame_ready_event = threading.Event()

        # Frame states & latching
        self._target_colors: Optional[List[Tuple[int, int, int]]] = None
        self._has_pending_beat: bool = False
        self._latched_beat_frame: Optional[List[Tuple[int, int, int]]] = None
        self._latched_beat_time: float = 0.0

        # Hardware tracking
        self._smoothed_colors: List[Tuple[int, int, int]] = [(0, 0, 0)] * self.NUM_ZONES
        self._last_sent_scaled: List[Tuple[int, int, int]] = [(0, 0, 0)] * self.NUM_ZONES
        self._last_sent_scale: Optional[float] = None
        self._last_send_time: float = 0.0
        self._last_beat_dispatch_time: float = 0.0
        self._last_reconnect_time: float = 0.0
        self._last_pipe_health_check: float = 0.0
        self._force_resync: bool = False
        self._is_static_mode: bool = False
        self._static_locked_color: Optional[Tuple[int, int, int]] = None
        self._static_locked_brightness: Optional[int] = None

        # Physical EC brightness synchronization (Command 1 read + debounced Command 2 write)
        self._has_initial_hw_sync: bool = False
        self._pending_hw_brightness: Optional[int] = None
        self._pending_hw_brightness_deadline: float = 0.0
        self._last_hw_brightness_poll: float = 0.0
        self._last_hw_brightness_write_time: float = 0.0

        # Background worker
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        self.refresh_devices()
        self._init_pipe()
        # Always launch background worker to handle frame pacing and automatic service reconnection
        self._start_worker()

    def refresh_devices(self):
        """Re-evaluates detected laptop model and enumerates active lighting devices."""
        self.model_info = detect_laptop_model()
        if self._is_connected:
            self.devices = self._enumerate_devices()
        else:
            self.devices = self._fallback_devices()
        self.primary_led_count = self.devices[0]["led_count"] if self.devices else self.model_info.zone_count

    def _fallback_devices(self) -> List[Dict[str, Any]]:
        """Constructs device profiles from model_info when pipe is offline."""
        kb_zones = self.model_info.zone_count if self.model_info else 4
        devs = [{
            "index": 0,
            "name": "Keyboard",
            "type": "Keyboard",
            "led_count": kb_zones,
            "is_per_key": (kb_zones > 4)
        }]
        if self.model_info and self.model_info.has_rear_lightbar:
            devs.append({
                "index": 1,
                "name": "Rear Lightbar",
                "type": "Lightbar",
                "led_count": 12,
                "is_per_key": False
            })
        if self.model_info and self.model_info.has_lid_logo:
            devs.append({
                "index": 2,
                "name": "Lid Logo",
                "type": "Logo",
                "led_count": 1,
                "is_per_key": False
            })
        return devs

    def _enumerate_devices(self) -> List[Dict[str, Any]]:
        """
        Dynamically enumerates lighting devices using Acer Lighting Service Named Pipe.
        Command 0: get_devicecount -> returns number of lighting devices.
        Command 1: get_deviceinfo(dev_idx) -> returns LED count, device type, and metadata.
        """
        cnt = self._get_device_count()
        if cnt <= 0:
            return self._fallback_devices()
        cnt = min(cnt, 4)

        devs = []
        for idx in range(cnt):
            info = self._get_device_info(idx)
            devs.append(info)
        return devs

    def _get_device_info(self, device_index: int) -> Dict[str, Any]:
        """
        Queries device info and hardware LED count for a specific lighting device index.
        For primary keyboard (device_index 0), queries Command 6 (get_hardware_leds)
        to extract true physical LED count, falling back to model_info.zone_count.
        """
        p0 = struct.pack('<I', device_index)
        default_leds = self.model_info.zone_count if device_index == 0 else (12 if device_index == 1 else 1)

        if device_index == 0:
            name = "Keyboard"
            dev_type = "Keyboard"
            # Query Command 6 to inspect active physical LED count reported by hardware driver
            cmd6_resp = self._send_command(6, [p0])
            if cmd6_resp and len(cmd6_resp) >= 9:
                try:
                    c6_count = struct.unpack('<I', cmd6_resp[5:9])[0]
                    if 1 <= c6_count <= 128:
                        led_count = c6_count
                    else:
                        led_count = self.model_info.zone_count
                except Exception:
                    led_count = self.model_info.zone_count
            else:
                led_count = self.model_info.zone_count
            is_per_key = (self.model_info.is_per_key or led_count > 4)
        else:
            name = f"Auxiliary Device {device_index}"
            dev_type = "Auxiliary"
            is_per_key = False
            if self.model_info and self.model_info.has_rear_lightbar and device_index == 1:
                led_count = 12
                name = "Rear Lightbar"
            elif self.model_info and self.model_info.has_lid_logo:
                led_count = 1
                name = "Lid Logo"
            else:
                led_count = 1

        return {
            "index": device_index,
            "name": name,
            "type": dev_type,
            "led_count": led_count,
            "is_per_key": is_per_key
        }

    @property
    def supports_hardware_brightness(self) -> bool:
        return True

    @KeyboardControllerBase.physical_brightness_enabled.setter
    def physical_brightness_enabled(self, enabled: bool):
        val = bool(enabled)
        with self._state_lock:
            self._physical_brightness_enabled = val
            if val:
                self._pending_hw_brightness = self._brightness
                self._pending_hw_brightness_deadline = 0.0
            else:
                self._pending_hw_brightness = None
                self._hw_brightness_level = None
            self._force_resync = True
        self._frame_ready_event.set()

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        val = max(0, min(100, int(value)))
        with self._state_lock:
            changed = (val != self._brightness)
            self._brightness = val
            if changed and getattr(self, "_physical_brightness_enabled", True):
                self._pending_hw_brightness = val
                self._pending_hw_brightness_deadline = time.perf_counter() + 0.12
        if changed:
            # Wake worker to immediately push updated brightness to hardware
            self._frame_ready_event.set()

    @staticmethod
    def _parse_device_info(resp: Optional[bytes]) -> Optional[Dict[str, Any]]:
        """Parses Command 1 (get_deviceinfo) TLV packet from AcerLightingService."""
        if not resp or len(resp) < 9:
            return None
        try:
            field_count = resp[0]
            if field_count < 6:
                return None
            off = 1
            fields: List[bytes] = []
            for _ in range(field_count):
                if off + 4 > len(resp):
                    return None
                field_len = struct.unpack('<I', resp[off:off + 4])[0]
                off += 4
                if off + field_len > len(resp):
                    return None
                fields.append(resp[off:off + field_len])
                off += field_len

            if len(fields[2]) != 4 or len(fields[3]) != 4 or len(fields[4]) != 4 or len(fields[5]) != 4:
                return None

            return {
                "name": fields[1].split(b"\x00")[0].decode("ascii", errors="ignore"),
                "device_type": struct.unpack('<I', fields[2])[0],
                "mode_count": struct.unpack('<I', fields[3])[0],
                "active_mode": struct.unpack('<I', fields[4])[0],
                "brightness": max(0, min(100, int(struct.unpack('<I', fields[5])[0]))),
            }
        except Exception:
            return None

    def get_hardware_brightness(self) -> Optional[int]:
        """Reads the live physical EC keyboard brightness (0-100) via Command 1 (get_deviceinfo)."""
        p0 = struct.pack('<I', self.device_index)
        resp = self._send_command(1, [p0])
        info = self._parse_device_info(resp)
        if info is None:
            return None
        return info["brightness"]

    def _apply_hardware_brightness(self, level: int) -> bool:
        """Applies physical EC keyboard backlight brightness via Command 2 while preserving Direct RGB colors."""
        val = max(0, min(100, int(level)))
        with self._state_lock:
            ref = self._static_locked_color
            if ref is None:
                colors = self._current_colors or [(0, 0, 0)] * self.NUM_ZONES
                ref = colors[1] if len(colors) > 1 else colors[0]

        ok = self.set_hardware_mode(
            mode=0,
            speed=5,
            brightness=val,
            direction=1,
            r=ref[0],
            g=ref[1],
            b=ref[2],
            _from_hw_sync=True
        )
        if ok:
            with self._state_lock:
                self._hw_brightness_level = val
                self._last_hw_brightness_write_time = time.perf_counter()
                if self._is_static_mode:
                    self._static_locked_brightness = val
                self._force_resync = True
        return ok

    def set_hardware_brightness(self, level: int, sync: bool = False) -> bool:
        """Sets physical EC keyboard backlight brightness (0-100) immediately."""
        val = max(0, min(100, int(level)))
        with self._state_lock:
            self._brightness = val
            self._pending_hw_brightness = None
        ok = self._apply_hardware_brightness(val)
        if sync and self._target_colors is not None:
            self._write_hardware_sync(list(self._target_colors))
        else:
            self._frame_ready_event.set()
        return ok

    def _get_effective_rgb_scale(self) -> float:
        """
        Computes software RGB multiplier so software + hardware EC brightness never double-dim.
        When EC hardware brightness matches target brightness, RGB is sent at full 1.0 scale.
        """
        b = getattr(self, "_brightness", 100)
        if b <= 0:
            return 0.0
        hw_b = getattr(self, "_hw_brightness_level", None)
        if getattr(self, "_physical_brightness_enabled", True) and hw_b is not None and hw_b > 0:
            return min(1.0, b / float(hw_b))
        return b / 100.0

    def _poll_hardware_brightness(self, now: float):
        """Detects external physical brightness changes (e.g. Fn+F9 / Fn+F10) and syncs back."""
        if not getattr(self, "_physical_brightness_enabled", True):
            return
        with self._state_lock:
            if self._pending_hw_brightness is not None:
                return
            if (now - self._last_hw_brightness_write_time) < 0.65:
                return

        hw_b = self.get_hardware_brightness()
        if hw_b is None:
            return

        notify_val: Optional[int] = None
        with self._state_lock:
            if self._pending_hw_brightness is not None:
                return
            if hw_b != self._hw_brightness_level:
                self._hw_brightness_level = hw_b
                if hw_b != self._brightness:
                    self._brightness = hw_b
                    if self._is_static_mode:
                        self._static_locked_brightness = hw_b
                    self._force_resync = True
                    notify_val = hw_b
        if notify_val is not None:
            self._notify_brightness_listeners(notify_val, source="hardware")
            self._frame_ready_event.set()

    def _init_pipe_handle(self) -> bool:
        """Opens the named pipe handle without querying devices."""
        try:
            h = kernel32.CreateFileW(
                self.PIPE_NAME,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                0,
                None
            )
            if h in (None, 0, INVALID_HANDLE_VALUE, -1):
                err = kernel32.GetLastError()
                if err == 231:  # ERROR_PIPE_BUSY
                    if kernel32.WaitNamedPipeW(self.PIPE_NAME, 150):
                        h = kernel32.CreateFileW(
                            self.PIPE_NAME,
                            GENERIC_READ | GENERIC_WRITE,
                            0,
                            None,
                            OPEN_EXISTING,
                            0,
                            None,
                        )
                if h in (None, 0, INVALID_HANDLE_VALUE, -1):
                    self._pipe_handle = INVALID_HANDLE_VALUE
                    return False
            self._pipe_handle = h
            return True
        except Exception:
            self._pipe_handle = INVALID_HANDLE_VALUE
            return False

    def _init_pipe(self) -> bool:
        with self._pipe_lock:
            if not self._init_pipe_handle():
                self._is_connected = False
                self.devices = self._fallback_devices()
                self.primary_led_count = self.model_info.zone_count
                return False

            cnt = self._get_device_count()
            if cnt > 0:
                self._is_connected = True
                self.devices = self._enumerate_devices()
                self.primary_led_count = self.devices[0]["led_count"] if self.devices else self.model_info.zone_count
                self.get_hardware_leds()
                hw_b = self.get_hardware_brightness()
                if hw_b is not None:
                    notify_hw: Optional[int] = None
                    with self._state_lock:
                        self._hw_brightness_level = hw_b
                        if not getattr(self, "_has_initial_hw_sync", False) and getattr(self, "_pending_hw_brightness", None) is None:
                            self._has_initial_hw_sync = True
                            if hw_b != self._brightness:
                                self._brightness = hw_b
                                notify_hw = hw_b
                        elif getattr(self, "_physical_brightness_enabled", True) and hw_b != self._brightness:
                            self._pending_hw_brightness = self._brightness
                            self._pending_hw_brightness_deadline = 0.0
                    if notify_hw is not None:
                        self._notify_brightness_listeners(notify_hw, source="hardware")
                self._static_locked_color = None
                self._static_locked_brightness = None
                self._force_resync = True
                self._frame_ready_event.set()
                return True
            else:
                # Never call self.close() here: _init_pipe() runs on _worker_thread and close()
                # would set _running=False, permanently killing the reconnection loop.
                self._handle_pipe_error()
                self.devices = self._fallback_devices()
                self.primary_led_count = self.model_info.zone_count
                return False

    def _handle_pipe_error(self):
        """Safely cleans up broken pipe handle on transmission error."""
        with self._pipe_lock:
            if self._pipe_handle not in (None, 0, INVALID_HANDLE_VALUE, -1):
                try:
                    kernel32.CloseHandle(self._pipe_handle)
                except Exception:
                    pass
                self._pipe_handle = INVALID_HANDLE_VALUE
            self._is_connected = False
        self._static_locked_color = None
        self._static_locked_brightness = None
        self._force_resync = True

    def force_resync(self):
        """Forces the next frame and hardware mode lock to be re-applied to the EC."""
        with self._state_lock:
            self._static_locked_color = None
            self._static_locked_brightness = None
            self._force_resync = True
        self._frame_ready_event.set()

    def _check_pipe_health(self) -> bool:
        """Non-intrusively verifies the named pipe handle is still alive without writing to LEDs."""
        with self._pipe_lock:
            if self._pipe_handle in (None, 0, INVALID_HANDLE_VALUE, -1):
                self._is_connected = False
                return False
            avail = wintypes.DWORD(0)
            ok = kernel32.PeekNamedPipe(
                self._pipe_handle, None, 0, None, ctypes.byref(avail), None
            )
            if not ok:
                self._handle_pipe_error()
                return False
            return True

    def _start_worker(self):
        self._running = True
        self._worker_thread = threading.Thread(target=self._dispatch_loop, daemon=True, name="AcerECPipeTransmitter")
        self._worker_thread.start()

    def _dispatch_loop(self):
        """
        Ultra-responsive background transmitter.
        Samples the latest animation state on demand, handles proactive beat latching,
        applies smooth delta interpolation between 120-160ms EC writes, auto-reconnects to
        AcerLightingService when it boots or restarts, and suppresses jitter.
        """
        while self._running:
            try:
                # Wake on frame arrival or timeout to evaluate settling frames / keepalive / auto-reconnect
                self._frame_ready_event.wait(timeout=0.025)
                if not self._running:
                    break
                self._frame_ready_event.clear()

                now = time.perf_counter()

                # If pipe is disconnected, attempt automatic background reconnection
                if not self._is_connected:
                    if (now - self._last_reconnect_time) >= 1.5:
                        self._last_reconnect_time = now
                        if self._init_pipe():
                            # Reconnected to hardware!
                            pass
                    continue

                # Periodically verify pipe health non-intrusively (even in static mode when no writes occur)
                if (now - self._last_pipe_health_check) >= 2.0:
                    self._last_pipe_health_check = now
                    if not self._check_pipe_health():
                        continue

                # Flush debounced physical EC brightness updates or poll for external Fn+F9/F10 changes
                pending_hw_b: Optional[int] = None
                with self._state_lock:
                    if (
                        getattr(self, "_physical_brightness_enabled", True)
                        and self._pending_hw_brightness is not None
                        and now >= self._pending_hw_brightness_deadline
                    ):
                        pending_hw_b = self._pending_hw_brightness
                        self._pending_hw_brightness = None

                if pending_hw_b is not None:
                    self._apply_hardware_brightness(pending_hw_b)
                elif (now - self._last_hw_brightness_poll) >= 0.40:
                    self._last_hw_brightness_poll = now
                    self._poll_hardware_brightness(now)

                target: Optional[List[Tuple[int, int, int]]] = None
                is_beat: bool = False

                with self._state_lock:
                    if self._target_colors is None:
                        continue

                    if self._has_pending_beat and self._latched_beat_frame is not None:
                        # Beat priority: send latched beat if not expired (>250ms)
                        if (now - self._latched_beat_time) < 0.25:
                            target = list(self._latched_beat_frame)
                            is_beat = True
                        else:
                            target = list(self._target_colors)
                        self._has_pending_beat = False
                        self._latched_beat_frame = None
                    else:
                        target = list(self._target_colors)

                if target is None:
                    continue

                # Smooth delta interpolation
                frame_to_send = self._interpolate_frame(target, is_beat, now)

                # Check if write is necessary
                if is_beat or self._should_send_frame(frame_to_send, now):
                    success = self._write_hardware_sync(frame_to_send)
                    if success:
                        with self._state_lock:
                            self._last_send_time = time.perf_counter()
                            self._smoothed_colors = list(frame_to_send)
                            if is_beat:
                                self._last_beat_dispatch_time = self._last_send_time
            except Exception:
                # Guarantee background worker never terminates on transient OS/pipe errors
                self._handle_pipe_error()
                time.sleep(0.05)

    def _interpolate_frame(
        self,
        target: List[Tuple[int, int, int]],
        is_beat: bool,
        now: float
    ) -> List[Tuple[int, int, int]]:
        """
        Calculates fluid color transitions between successive hardware bus writes.
        Beats snap immediately (0ms perceived latency).
        Decays and sweeps glide continuously to avoid stepped strobe artifacts.
        """
        if is_beat or getattr(self, "_is_static_mode", False):
            return list(target)

        # Hold beat peak briefly (35ms) to give human eye & physical LEDs time to register flash
        if (now - self._last_beat_dispatch_time) < 0.035:
            alpha_hold = (now - self._last_beat_dispatch_time) / 0.035
        else:
            alpha_hold = 1.0

        dt = max(0.001, min(0.30, now - self._last_send_time)) if self._last_send_time > 0 else 0.12

        interpolated = []
        for i in range(self.NUM_ZONES):
            c_last = self._smoothed_colors[i]
            c_tgt = target[i]

            zone_rgb = []
            for ch in range(3):
                last_val = c_last[ch]
                tgt_val = c_tgt[ch]
                diff = tgt_val - last_val

                if abs(diff) <= 2:
                    zone_rgb.append(tgt_val)
                elif diff > 0:
                    # Attack phase: fast snappy rise
                    alpha_rise = min(1.0, max(0.85, dt * 10.0)) * alpha_hold
                    val = last_val + diff * alpha_rise
                    zone_rgb.append(int(max(0, min(255, round(val)))))
                else:
                    # Decay phase: smooth exponential falloff
                    alpha_fall = min(1.0, max(0.45, 1.0 - math.exp(-8.0 * dt))) * alpha_hold
                    val = last_val + diff * alpha_fall
                    zone_rgb.append(int(max(0, min(255, round(val)))))

            interpolated.append((zone_rgb[0], zone_rgb[1], zone_rgb[2]))

        return interpolated

    def _should_send_frame(self, frame: List[Tuple[int, int, int]], now: float) -> bool:
        """
        Adaptive dirty check: suppresses identical / imperceptible bus traffic
        while ensuring settling frames converge with 0 error.
        """
        if getattr(self, "_force_resync", False):
            return True

        scale = self._get_effective_rgb_scale()
        any_diff = False
        max_diff = 0

        for i in range(self.NUM_ZONES):
            r, g, b = frame[i]
            r_sc = int(max(0, min(255, round(r * scale))))
            g_sc = int(max(0, min(255, round(g * scale))))
            b_sc = int(max(0, min(255, round(b * scale))))

            last_r, last_g, last_b = self._last_sent_scaled[i]
            dr = abs(r_sc - last_r)
            dg = abs(g_sc - last_g)
            db = abs(b_sc - last_b)

            if dr > 2 or dg > 2 or db > 2:
                any_diff = True
                break
            max_diff = max(max_diff, dr, dg, db)

        if getattr(self, "_is_static_mode", False):
            # In static mode, dispatch ONLY when colors actually differ from the last sent frame.
            # Suppress ALL redundant periodic keep-alives so physical LEDs remain 100% solid, steady, with zero blinking.
            return any_diff

        if any_diff:
            return True

        # Settling frame: if subtle difference exists and no update was sent in >250ms, update hardware
        if max_diff > 0 and (now - self._last_send_time > 0.25):
            return True

        # Hardware Watchdog Keep-Alive (every 0.45s):
        # In active dynamic animation modes, refresh at >=0.45s if idle.
        if (now - self._last_send_time) >= 0.45:
            return True

        return False

    def _send_command(self, cmd_code: int, params: List[bytes]) -> Optional[bytes]:
        """Atomic command write & read over the Acer Lighting Service named pipe."""
        with self._pipe_lock:
            if self._pipe_handle in (None, 0, INVALID_HANDLE_VALUE, -1):
                now = time.perf_counter()
                # Rate-limit pipe reconnection attempts to avoid hammering the Windows kernel
                if (now - self._last_reconnect_time) < 1.5:
                    return None
                self._last_reconnect_time = now
                if not self._init_pipe_handle():
                    return None

            pkt = struct.pack('<HB', cmd_code, len(params))
            for p in params:
                pkt += struct.pack('<I', len(p)) + p

            bytes_written = wintypes.DWORD()
            res = kernel32.WriteFile(
                self._pipe_handle,
                pkt,
                len(pkt),
                ctypes.byref(bytes_written),
                None
            )
            if not res or bytes_written.value != len(pkt):
                self._handle_pipe_error()
                return None

            # Read response with 64KB buffer and loop if more data is available
            full_resp = bytearray()
            buf_size = 65536
            resp_buf = ctypes.create_string_buffer(buf_size)
            bytes_read = wintypes.DWORD()

            while True:
                res = kernel32.ReadFile(
                    self._pipe_handle,
                    resp_buf,
                    buf_size,
                    ctypes.byref(bytes_read),
                    None
                )
                err = kernel32.GetLastError()
                if res and bytes_read.value > 0:
                    full_resp.extend(resp_buf.raw[:bytes_read.value])
                    break
                elif not res and err == 234:  # ERROR_MORE_DATA
                    full_resp.extend(resp_buf.raw[:bytes_read.value])
                    continue
                else:
                    if len(full_resp) == 0:
                        self._handle_pipe_error()
                        return None
                    break

            return bytes(full_resp)

    def _get_device_count(self) -> int:
        resp = self._send_command(0, [])
        if resp and len(resp) >= 9:
            count = struct.unpack('<I', resp[5:9])[0]
            return count
        return 0

    def get_hardware_leds(self) -> List[Tuple[int, int, int]]:
        p0 = struct.pack('<I', self.device_index)
        resp = self._send_command(6, [p0])
        if resp and len(resp) >= 29:
            colors_data = resp[13:29]
            colors = []
            for i in range(0, 16, 4):
                r = colors_data[i]
                g = colors_data[i+1]
                b = colors_data[i+2]
                colors.append((r, g, b))
            if len(colors) == self.NUM_ZONES:
                with self._state_lock:
                    self._current_colors = list(colors)
                    self._smoothed_colors = list(colors)
                    self._last_sent_scaled = list(colors)
                return colors
        with self._state_lock:
            return list(self._current_colors)

    def _write_device_raw(self, device_index: int, colors: List[Tuple[int, int, int]], scale: float) -> bool:
        """Physical raw packet write to a specific lighting device over the pipe."""
        c_bytes = bytearray()
        for r, g, b in colors:
            r_sc = int(max(0, min(255, round(r * scale))))
            g_sc = int(max(0, min(255, round(g * scale))))
            b_sc = int(max(0, min(255, round(b * scale))))
            c_bytes.extend([r_sc, g_sc, b_sc, 0])

        p0 = struct.pack('<I', device_index)
        p1 = struct.pack('<I', len(colors))
        p2 = bytes(c_bytes)

        resp = self._send_command(3, [p0, p1, p2])
        if resp and len(resp) >= 9:
            status = struct.unpack('<I', resp[5:9])[0]
            return status == 0
        return False

    def _write_hardware_sync(self, colors: List[Tuple[int, int, int]]) -> bool:
        """Physical write to the Acer EC pipe with dynamic zone expansion and auxiliary sync."""
        # In static mode, lock in hardware static mode with primary album color.
        # This sends Command 2 (mode=0 STATIC) with 6 parameters to AcerLightingService,
        # updating the hardware EC and LightingProfile.ini so that service watchdog timeouts
        # retain the album static color instead of reverting to white (#F1F1F1).
        if getattr(self, "_is_static_mode", False) and colors:
            primary_c = colors[1] if len(colors) > 1 else colors[0]
            if (self._static_locked_color != primary_c or
                self._static_locked_brightness != self._brightness):
                mode_ok = self.set_hardware_mode(
                    mode=0,
                    speed=5,
                    brightness=self._brightness,
                    direction=1,
                    r=primary_c[0],
                    g=primary_c[1],
                    b=primary_c[2],
                    _from_hw_sync=True
                )
                self._static_locked_color = primary_c
                self._static_locked_brightness = self._brightness
                if mode_ok:
                    self._hw_brightness_level = self._brightness
                    self._last_hw_brightness_write_time = time.perf_counter()
                    self._pending_hw_brightness = None
        else:
            self._static_locked_color = None
            self._static_locked_brightness = None

        scale = self._get_effective_rgb_scale()

        # 1. Primary Keyboard Write (strictly mapped to hardware zone count)
        # On 4-zone laptops (e.g. Helios Neo 16), kb_leds is strictly 4.
        # On per-key laptops, primary_led_count reflects the key count (e.g. 84).
        if self.model_info and not self.model_info.is_per_key:
            kb_leds = self.model_info.zone_count
        else:
            kb_leds = self.primary_led_count
        kb_colors = map_4zone_to_n(colors, kb_leds)
        success = self._write_device_raw(self.device_index, kb_colors, scale)

        # 2. Auxiliary Devices Sync (Rear Lightbar, Lid Logo) - only if supported by hardware model
        has_aux = bool(self.model_info and (self.model_info.has_rear_lightbar or self.model_info.has_lid_logo))
        if self.sync_auxiliary and has_aux and len(self.devices) > 1:
            for dev in self.devices[1:]:
                dev_idx = dev.get("index", 1)
                dev_leds = max(1, min(64, dev.get("led_count", 1)))
                is_beat = self._has_pending_beat
                aux_colors = map_auxiliary_device_colors(colors, dev_leds, is_beat=is_beat)
                self._write_device_raw(dev_idx, aux_colors, scale)

        # Update cached colors for logical 4-zone state tracking only on successful write
        with self._state_lock:
            if success:
                self._force_resync = False
                self._last_sent_scaled = [
                    (int(round(c[0] * scale)), int(round(c[1] * scale)), int(round(c[2] * scale)))
                    for c in colors[:self.NUM_ZONES]
                ]
                self._current_colors = [
                    (int(max(0, min(255, c[0]))),
                     int(max(0, min(255, c[1]))),
                     int(max(0, min(255, c[2]))))
                    for c in colors[:self.NUM_ZONES]
                ]
            else:
                self._static_locked_color = None
                self._static_locked_brightness = None
                self._force_resync = True

        return success

    def set_zone_color(self, zone: int, r: int, g: int, b: int, sync: bool = False) -> bool:
        if not (0 <= zone < self.NUM_ZONES):
            return False
        with self._state_lock:
            new_colors = list(self._current_colors)
            new_colors[zone] = (r, g, b)
        return self.set_all_zones(new_colors, sync=sync)

    def set_all_zones(
        self,
        colors: List[Tuple[int, int, int]],
        is_beat: bool = False,
        sync: bool = False,
        **kwargs
    ) -> bool:
        """
        Updates 4-zone colors.
        Non-blocking by default (<0.01ms): latches beats and updates latest frame.
        If sync=True, performs an immediate synchronous hardware bus transaction.
        """
        if len(colors) < self.NUM_ZONES:
            return False

        is_static = kwargs.get("is_static", False)

        if sync:
            with self._state_lock:
                self._is_static_mode = is_static
                self._target_colors = list(colors[:self.NUM_ZONES])
            return self._write_hardware_sync(colors[:self.NUM_ZONES])

        with self._state_lock:
            clamped = [
                (
                    int(max(0, min(255, c[0]))),
                    int(max(0, min(255, c[1]))),
                    int(max(0, min(255, c[2])))
                )
                for c in colors[:self.NUM_ZONES]
            ]
            self._is_static_mode = is_static
            self._target_colors = clamped
            self._current_colors = list(clamped)

            if is_static:
                self._has_pending_beat = False
                self._latched_beat_frame = None
            elif is_beat:
                self._has_pending_beat = True
                self._latched_beat_frame = list(clamped)
                self._latched_beat_time = time.perf_counter()

        self._frame_ready_event.set()
        return True

    def set_hardware_mode(
        self,
        mode: int,
        speed: int = 5,
        brightness: Optional[int] = None,
        direction: int = 1,
        r: int = 0,
        g: int = 0,
        b: int = 0,
        device_index: Optional[int] = None,
        _from_hw_sync: bool = False
    ) -> bool:
        """
        Dispatches Command 2 (set_devicemode) with 6 parameters to AcerLightingService.
        mode: Mode value (0 = STATIC, 1 = BREATHING, 2 = NEON, etc.).
        Locks the hardware EC and updates LightingProfile.ini internally.
        """
        # Guard against AcerLightingService C++ bug: Direct modes (1 or 255) corrupt LightingProfile.ini and cause 0xc0000374 heap crash
        if mode in (1, 255):
            return True
        if brightness is not None:
            b_clamped = max(0, min(100, int(brightness)))
            if _from_hw_sync:
                self._brightness = b_clamped
            else:
                self.brightness = b_clamped

        dev_idx = self.device_index if device_index is None else int(device_index)
        p0 = struct.pack('<I', dev_idx)
        p1 = struct.pack('<I', int(mode))
        p2 = bytes([int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF, 0])
        p3 = struct.pack('<I', int(speed))
        p4 = struct.pack('<I', int(self._brightness))
        p5 = struct.pack('<I', int(direction))

        resp = self._send_command(2, [p0, p1, p2, p3, p4, p5])
        if resp and len(resp) >= 9:
            status = struct.unpack('<I', resp[5:9])[0]
            if status == 0:
                self._hw_brightness_level = int(self._brightness)
                self._last_hw_brightness_write_time = time.perf_counter()
                return True
            return False
        return False

    def close(self):
        self._running = False
        self._frame_ready_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            if threading.current_thread() != self._worker_thread:
                self._worker_thread.join(timeout=0.6)
        with self._pipe_lock:
            if self._pipe_handle not in (None, 0, INVALID_HANDLE_VALUE, -1):
                try:
                    kernel32.CloseHandle(self._pipe_handle)
                except Exception:
                    pass
                self._pipe_handle = INVALID_HANDLE_VALUE
            self._is_connected = False

    @staticmethod
    def is_service_running() -> bool:
        """Checks if AcerLightingService Windows service is currently running."""
        try:
            import subprocess
            out = subprocess.check_output(
                ["sc.exe", "query", "AcerLightingService"],
                text=True,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000 if sys.platform == "win32" else 0
            )
            return "RUNNING" in out
        except Exception:
            return False

    @staticmethod
    def start_service_elevated() -> bool:
        """Attempts to start AcerLightingService via Windows UAC elevation."""
        try:
            fix_bat = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Fix-AcerLightingService.bat"))
            if os.path.exists(fix_bat):
                ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", fix_bat, None, None, 1)
                return ret > 32
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", "/c net start AcerLightingService", None, 0)
            return ret > 32
        except Exception:
            return False
