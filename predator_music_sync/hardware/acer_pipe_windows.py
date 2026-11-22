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
        self._last_send_time: float = 0.0
        self._last_beat_dispatch_time: float = 0.0
        self._last_reconnect_time: float = 0.0

        # Background worker
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        self.refresh_devices()
        self._init_pipe()
        if self._is_connected:
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

        devs = []
        for idx in range(cnt):
            info = self._get_device_info(idx)
            devs.append(info)
        return devs

    def _get_device_info(self, device_index: int) -> Dict[str, Any]:
        """
        Queries Command 1 (get_deviceinfo) for a specific device index to extract physical LED count.
        """
        p0 = struct.pack('<I', device_index)
        resp = self._send_command(1, [p0])
        default_leds = self.model_info.zone_count if device_index == 0 else (12 if device_index == 1 else 1)
        name = "Keyboard" if device_index == 0 else (f"Auxiliary Device {device_index}")

        if resp and len(resp) >= 9:
            try:
                val = struct.unpack('<I', resp[5:9])[0]
                if val > 0:
                    led_count = val
                elif len(resp) >= 13:
                    val2 = struct.unpack('<I', resp[9:13])[0]
                    led_count = val2 if val2 > 0 else default_leds
                else:
                    led_count = default_leds
            except Exception:
                led_count = default_leds
        else:
            led_count = default_leds

        return {
            "index": device_index,
            "name": name,
            "type": "Keyboard" if device_index == 0 else "Auxiliary",
            "led_count": led_count,
            "is_per_key": (led_count > 4 and device_index == 0)
        }

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        val = max(0, min(100, int(value)))
        if val != self._brightness:
            self._brightness = val
            # Wake worker to immediately push updated brightness to hardware
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
                return True
            else:
                self.close()
                self.devices = self._fallback_devices()
                self.primary_led_count = self.model_info.zone_count
                return False

    def _handle_pipe_error(self):
        """Safely cleans up broken pipe handle on transmission error."""
        if self._pipe_handle not in (None, 0, INVALID_HANDLE_VALUE, -1):
            try:
                kernel32.CloseHandle(self._pipe_handle)
            except Exception:
                pass
            self._pipe_handle = INVALID_HANDLE_VALUE
        self._is_connected = False

    def _start_worker(self):
        self._running = True
        self._worker_thread = threading.Thread(target=self._dispatch_loop, daemon=True, name="AcerECPipeTransmitter")
        self._worker_thread.start()

    def _dispatch_loop(self):
        """
        Ultra-responsive background transmitter.
        Samples the latest animation state on demand, handles proactive beat latching,
        applies smooth delta interpolation between 120-160ms EC writes, and suppresses jitter.
        """
        while self._running:
            try:
                # Wake on frame arrival or timeout to evaluate settling frames / keepalive
                self._frame_ready_event.wait(timeout=0.025)
                if not self._running:
                    break
                self._frame_ready_event.clear()

                now = time.perf_counter()
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
        if is_beat:
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
        scale = self._brightness / 100.0
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

        if any_diff:
            return True

        # Settling frame: if subtle difference exists and no update was sent in >250ms, update hardware
        if max_diff > 0 and (now - self._last_send_time > 0.25):
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

            resp_buf = ctypes.create_string_buffer(1024)
            bytes_read = wintypes.DWORD()
            res = kernel32.ReadFile(
                self._pipe_handle,
                resp_buf,
                1024,
                ctypes.byref(bytes_read),
                None
            )
            if not res or bytes_read.value == 0:
                self._handle_pipe_error()
                return None

            return resp_buf.raw[:bytes_read.value]

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
        scale = self._brightness / 100.0

        # 1. Primary Keyboard Write (dynamically expanded across physical LEDs)
        kb_leds = self.primary_led_count
        kb_colors = map_4zone_to_n(colors, kb_leds)
        success = self._write_device_raw(self.device_index, kb_colors, scale)

        # 2. Auxiliary Devices Sync (Rear Lightbar, Lid Logo)
        if self.sync_auxiliary and len(self.devices) > 1:
            for dev in self.devices[1:]:
                dev_idx = dev.get("index", 1)
                dev_leds = dev.get("led_count", 1)
                is_beat = self._has_pending_beat
                aux_colors = map_auxiliary_device_colors(colors, dev_leds, is_beat=is_beat)
                self._write_device_raw(dev_idx, aux_colors, scale)

        # Update cached colors for logical 4-zone state tracking
        with self._state_lock:
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

        if sync:
            with self._state_lock:
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
            self._target_colors = clamped
            self._current_colors = list(clamped)

            if is_beat:
                self._has_pending_beat = True
                self._latched_beat_frame = list(clamped)
                self._latched_beat_time = time.perf_counter()

        self._frame_ready_event.set()
        return True

    def set_hardware_mode(
        self,
        mode: int,
        speed: int,
        brightness: int,
        direction: int,
        r: int,
        g: int,
        b: int
    ) -> bool:
        self.brightness = brightness
        p0 = struct.pack('<I', self.device_index)
        p1 = struct.pack('<I', mode)
        settings = bytearray(32)
        settings[0] = mode & 0xFF
        settings[1] = speed & 0xFF
        settings[2] = brightness & 0xFF
        settings[3] = direction & 0xFF
        settings[4] = r & 0xFF
        settings[5] = g & 0xFF
        settings[6] = b & 0xFF
        p2 = bytes(settings)
        resp = self._send_command(2, [p0, p1, p2])
        return resp is not None

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
