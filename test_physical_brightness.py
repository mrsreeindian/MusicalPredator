"""
Comprehensive Unit & Integration Tests for Physical Keyboard Brightness Control:
1. Hardware Base & Virtual Backend physical brightness interface + simulated Fn+F9/F10 keys.
2. AcerLightingNamedPipeBackend Command 1 TLV parsing, Command 2 EC brightness control,
   debounced slider dispatch, zero double-dimming scaling, and external Fn+F9/F10 polling sync.
3. WindowsAcerWmiBackend & LinuxAcerBackend physical brightness read/write & anti-double-dim.
4. PredatorSyncService bidirectional brightness sync, step_brightness, power profile notifications.
5. PredatorTrayManager Brightness submenu (+25%, -25%, 100/75/50/25/0%) & thread-safe readout.
6. PredatorMusicToolbar programmatic slider/label/EC-sync button updates without feedback loops.
7. PredatorMusicSyncApp end-to-end sync from physical hotkey event -> service -> GUI + Tray.
8. Live AcerLightingService_NamedPipe read-only check (when running on Predator hardware).
"""

import os
import sys
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from predator_music_sync.hardware.base import KeyboardControllerBase
from predator_music_sync.hardware.virtual_keyboard import VirtualKeyboardBackend
from predator_music_sync.hardware.acer_pipe_windows import (
    AcerLightingNamedPipeBackend,
    INVALID_HANDLE_VALUE,
)
from predator_music_sync.hardware.acer_wmi_windows import WindowsAcerWmiBackend
from predator_music_sync.hardware.acer_linux import LinuxAcerBackend
from predator_music_sync.hardware.device_detector import parse_model_string
from predator_music_sync.service.sync_service import PredatorSyncService
from predator_music_sync.tray.tray_manager import PredatorTrayManager
from predator_music_sync.gui.toolbar import PredatorMusicToolbar
from predator_music_sync.main import PredatorMusicSyncApp


def _build_cmd1_device_info_packet(name: str = "AcerECKeyboard Device", brightness: int = 75, active_mode: int = 1) -> bytes:
    """Builds a valid AcerLightingService Command 1 (get_deviceinfo) TLV response."""
    fields = [
        struct.pack("<I", len(name)),
        name.encode("ascii") + b"\x00" * max(0, 50 - len(name)),
        struct.pack("<I", 5),
        struct.pack("<I", 9),
        struct.pack("<I", active_mode),
        struct.pack("<I", brightness),
        b"\x00" * 972,
    ]
    out = bytearray([len(fields)])
    for f in fields:
        out += struct.pack("<I", len(f)) + f
    return bytes(out)


class TestPhysicalBrightnessControl(unittest.TestCase):

    def _make_unconnected_pipe_backend(self) -> AcerLightingNamedPipeBackend:
        backend = AcerLightingNamedPipeBackend.__new__(AcerLightingNamedPipeBackend)
        backend.NUM_ZONES = 4
        backend.device_index = 0
        backend._pipe_handle = INVALID_HANDLE_VALUE
        backend._is_connected = True
        backend.model_info = parse_model_string("Predator PHN16-71")
        backend.devices = [{"index": 0, "name": "Keyboard", "type": "Keyboard", "led_count": 4, "is_per_key": False}]
        backend.primary_led_count = 4
        backend.sync_auxiliary = False
        backend._pipe_lock = threading.RLock()
        backend._state_lock = threading.Lock()
        backend._frame_ready_event = threading.Event()
        backend._target_colors = None
        backend._has_pending_beat = False
        backend._latched_beat_frame = None
        backend._latched_beat_time = 0.0
        backend._current_colors = [(200, 100, 50)] * 4
        backend._smoothed_colors = [(200, 100, 50)] * 4
        backend._last_sent_scaled = [(200, 100, 50)] * 4
        backend._last_sent_scale = 1.0
        backend._last_send_time = 0.0
        backend._last_beat_dispatch_time = 0.0
        backend._last_reconnect_time = 0.0
        backend._last_pipe_health_check = 0.0
        backend._force_resync = False
        backend._is_static_mode = False
        backend._static_locked_color = None
        backend._static_locked_brightness = None
        backend._brightness = 100
        backend._physical_brightness_enabled = True
        backend._hw_brightness_level = 100
        backend._brightness_listeners = []
        backend._has_initial_hw_sync = True
        backend._pending_hw_brightness = None
        backend._pending_hw_brightness_deadline = 0.0
        backend._last_hw_brightness_poll = 0.0
        backend._last_hw_brightness_write_time = 0.0
        backend._worker_thread = None
        backend._running = False
        return backend

    def test_01_virtual_backend_physical_brightness_and_hotkey_sim(self):
        vk = VirtualKeyboardBackend()
        events = []
        vk.add_brightness_listener(lambda lvl, src: events.append((lvl, src)))

        self.assertTrue(vk.supports_hardware_brightness)
        self.assertEqual(vk.get_hardware_brightness(), 100)

        self.assertTrue(vk.set_hardware_brightness(60))
        self.assertEqual(vk.brightness, 60)
        self.assertEqual(vk.get_hardware_brightness(), 60)

        new_lvl = vk.simulate_physical_brightness_key(-25)
        self.assertEqual(new_lvl, 35)
        self.assertEqual(vk.brightness, 35)
        self.assertEqual(vk.get_hardware_brightness(), 35)
        self.assertEqual(events[-1], (35, "hardware"))

        # Clamp bounds [0, 100]
        self.assertEqual(vk.simulate_physical_brightness_key(-100), 0)
        self.assertEqual(vk.simulate_physical_brightness_key(200), 100)

    def test_02_pipe_cmd1_parsing_and_no_double_dimming(self):
        backend = self._make_unconnected_pipe_backend()

        pkt = _build_cmd1_device_info_packet(brightness=75, active_mode=1)
        parsed = AcerLightingNamedPipeBackend._parse_device_info(pkt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["name"], "AcerECKeyboard Device")
        self.assertEqual(parsed["device_type"], 5)
        self.assertEqual(parsed["brightness"], 75)

        # Malformed packets return None safely
        self.assertIsNone(AcerLightingNamedPipeBackend._parse_device_info(b"\x02\x04\x00"))
        self.assertIsNone(AcerLightingNamedPipeBackend._parse_device_info(None))

        # get_hardware_brightness queries Command 1
        with patch.object(backend, "_send_command", return_value=pkt) as mock_cmd:
            self.assertEqual(backend.get_hardware_brightness(), 75)
            self.assertEqual(mock_cmd.call_args[0][0], 1)

        # Zero double-dimming: when EC hardware brightness == target brightness (50), RGB scale must be 1.0
        backend._brightness = 50
        backend._hw_brightness_level = 50
        self.assertAlmostEqual(backend._get_effective_rgb_scale(), 1.0, places=5)

        # During debounce (target=50 while EC still at 100), software scale smoothly bridges at 0.5
        backend._hw_brightness_level = 100
        self.assertAlmostEqual(backend._get_effective_rgb_scale(), 0.5, places=5)

        # At 0%, RGB scale is strictly 0.0 (blackout)
        backend._brightness = 0
        self.assertEqual(backend._get_effective_rgb_scale(), 0.0)

        # When physical EC sync disabled, pure software scaling applies
        backend._brightness = 40
        backend._physical_brightness_enabled = False
        self.assertAlmostEqual(backend._get_effective_rgb_scale(), 0.4, places=5)

    def test_03_pipe_cmd2_apply_and_external_hotkey_poll_sync(self):
        backend = self._make_unconnected_pipe_backend()
        events = []
        backend.add_brightness_listener(lambda lvl, src: events.append((lvl, src)))

        # Setting brightness queues debounced hardware EC write
        backend.brightness = 50
        self.assertEqual(backend._pending_hw_brightness, 50)

        # Simulate flushing hardware brightness (Command 2 mode=0, brightness=50)
        ok_resp = b"\x01\x04\x00\x00\x00\x00\x00\x00\x00"
        with patch.object(backend, "_send_command", return_value=ok_resp) as mock_send:
            self.assertTrue(backend.set_hardware_brightness(50, sync=False))
            self.assertEqual(mock_send.call_args[0][0], 2)
            params = mock_send.call_args[0][1]
            self.assertEqual(struct.unpack("<I", params[1])[0], 0)   # mode 0 (STATIC)
            self.assertEqual(struct.unpack("<I", params[4])[0], 50)  # brightness 50
            self.assertEqual(backend._hw_brightness_level, 50)
            self.assertIsNone(backend._pending_hw_brightness)
            self.assertTrue(backend._force_resync)

        # Immediately after writing EC, poll must respect grace window and NOT misread stale state
        with patch.object(backend, "get_hardware_brightness", return_value=100) as mock_get:
            backend._poll_hardware_brightness(time.perf_counter())
            mock_get.assert_not_called()

        # After grace window, external Fn+F9/F10 EC change (50 -> 25) must sync back without queuing cmd 2 write
        backend._last_hw_brightness_write_time = time.perf_counter() - 2.0
        with patch.object(backend, "get_hardware_brightness", return_value=25):
            backend._poll_hardware_brightness(time.perf_counter())
        self.assertEqual(backend.brightness, 25)
        self.assertEqual(backend._hw_brightness_level, 25)
        self.assertIsNone(backend._pending_hw_brightness)
        self.assertEqual(events[-1], (25, "hardware"))

    def test_04_wmi_and_linux_backends_brightness(self):
        # WMI backend (mocked PowerShell)
        wmi = WindowsAcerWmiBackend.__new__(WindowsAcerWmiBackend)
        KeyboardControllerBase.__init__(wmi)
        wmi._wmi_available = True
        wmi._unscaled_colors = [(255, 0, 0)] * 4
        wmi._creationflags = 0
        wmi._startupinfo = None

        fake_proc = MagicMock(returncode=0, stdout="75\n")
        with patch("predator_music_sync.hardware.acer_wmi_windows.subprocess.run", return_value=fake_proc):
            self.assertEqual(wmi.get_hardware_brightness(), 75)
            self.assertAlmostEqual(wmi._effective_scale(), 1.0, places=4)

        with patch.object(wmi, "set_hardware_mode", return_value=True) as mock_wmi_mode:
            self.assertTrue(wmi.set_hardware_brightness(50))
            mock_wmi_mode.assert_called_once()
            self.assertEqual(wmi._hw_brightness_level, 50)

        # Linux backend (mocked sysfs LED directory)
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "brightness"), "w") as f:
                f.write("2")
            with open(os.path.join(tmpdir, "max_brightness"), "w") as f:
                f.write("4")

            linux = LinuxAcerBackend.__new__(LinuxAcerBackend)
            KeyboardControllerBase.__init__(linux)
            linux._dev_fd = None
            linux._sysfs_led_dir = tmpdir

            self.assertTrue(linux.supports_hardware_brightness)
            self.assertEqual(linux.get_hardware_brightness(), 50)
            self.assertTrue(linux.set_hardware_brightness(75))
            with open(os.path.join(tmpdir, "brightness"), "r") as f:
                self.assertEqual(f.read().strip(), "3")

    def test_05_service_tray_gui_and_app_bidirectional_sync(self):
        # 1. Tray brightness menu & callbacks
        tray_vals = []
        tray = PredatorTrayManager(
            on_show_window=lambda: None,
            on_hide_window=lambda: None,
            on_toggle_lighting=lambda _a: None,
            on_set_mode=lambda _m: None,
            on_exit_app=lambda: None,
            on_set_brightness=lambda b: tray_vals.append(b),
            initial_brightness=75,
        )
        menu = tray.build_menu()
        self.assertTrue(any("Brightness (75%)" in str(it.text) for it in menu.items))
        tray._handle_step_brightness(-25)
        self.assertEqual(tray_vals[-1], 50)
        tray._handle_set_brightness(100)
        self.assertEqual(tray_vals[-1], 100)

        # 2. Full App bidirectional sync (Fn+F9/F10 -> service -> queue -> GUI + Tray, no feedback loop)
        app = PredatorMusicSyncApp(target_fps=60, prefer_virtual=True, start_minimized=False)
        app.service.start()
        app.gui.create_window()
        app._start_gui_queue_pump()
        app.gui.root.update()
        try:
            # Verify EC sync badge exists in Tab 1
            self.assertIsNotNone(app.gui._btn_phys_bright)
            self.assertIn("EC SYNC", app.gui._btn_phys_bright.cget("text"))

            # Simulate physical Fn+F9 key on virtual controller from background thread
            done = threading.Event()

            def bg_hotkey():
                app.service.controller.simulate_physical_brightness_key(-50)
                done.set()

            threading.Thread(target=bg_hotkey, daemon=True).start()
            deadline = time.perf_counter() + 2.0
            while not done.is_set() and time.perf_counter() < deadline:
                app.gui.root.update()
                time.sleep(0.01)
            for _ in range(5):
                app.gui.root.update()
                time.sleep(0.02)

            self.assertEqual(app.service.get_brightness(), 50)
            self.assertEqual(app.tray._current_brightness, 50)
            self.assertEqual(app.gui._current_brightness, 50)
            self.assertEqual(app.gui._lbl_val_bright.cget("text"), "50%")
            self.assertEqual(int(app.gui._slider_bright.get()), 50)

            # Programmatic set_brightness(notify=False) must NOT trigger on_brightness_change loop
            with patch.object(app.gui, "on_brightness_change") as mock_cb:
                app.gui.set_brightness(25, notify=False, source="hardware")
                app.gui.root.update()
                mock_cb.assert_not_called()
                self.assertEqual(app.gui._lbl_val_bright.cget("text"), "25%")

            # Toggle physical sync off/on via GUI helper
            app.gui._toggle_physical_brightness_gui()
            self.assertFalse(app.service.is_physical_brightness_enabled())
            self.assertEqual(app.gui._btn_phys_bright.cget("text"), "EC SYNC: OFF")
            app.gui._toggle_physical_brightness_gui()
            self.assertTrue(app.service.is_physical_brightness_enabled())
            self.assertEqual(app.gui._btn_phys_bright.cget("text"), "EC SYNC: ON")
        finally:
            app.exit_completely()

    def test_06_live_hardware_pipe_brightness_readonly(self):
        hw = AcerLightingNamedPipeBackend()
        try:
            if hw.is_connected:
                lvl = hw.get_hardware_brightness()
                self.assertIsNotNone(lvl)
                self.assertTrue(0 <= lvl <= 100, f"Unexpected hardware brightness: {lvl}")
                print(f"  [PASS] Live AcerLightingService EC Brightness: {lvl}%")
            else:
                print("  [SKIP] AcerLightingService pipe offline in this environment.")
        finally:
            hw.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
