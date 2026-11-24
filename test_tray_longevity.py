"""
Automated Regression & Longevity Test Suite for 5-Minute Tray Malfunction Fixes.

Covers every root cause behind the ~5-minute close-to-tray malfunction:
1. Windows EcoQoS / Timer-Resolution Process Power Throttling opt-out & sleep/resume detection.
2. Acer Named Pipe worker survival on cnt==0, PeekNamedPipe idle health check,
   failed-write state preservation, and static-mode reconnect/resume re-sync.
3. AudioBeatSyncEngine stalled-stream (zombie WASAPI) watchdog & transient open recovery.
4. MediaSessionEngine persistent SMTC worker, fast stop_monitoring, and JSON error parsing.
5. PredatorSyncService sleep/resume recovery, dt clamping, and disabled-lighting override guard.
6. PredatorTrayManager thread-safe menu/title updates & dynamic hardware status.
7. PredatorMusicSyncApp close-to-tray cross-thread GUI dispatch, dedup, and restore sync.
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from predator_music_sync.hardware.acer_pipe_windows import (
    AcerLightingNamedPipeBackend,
    INVALID_HANDLE_VALUE,
)
from predator_music_sync.core.audio_engine import AudioBeatSyncEngine, AudioBeatState
from predator_music_sync.core.media_engine import MediaSessionEngine, MediaTrackInfo
from predator_music_sync.service.sync_service import PredatorSyncService
from predator_music_sync.tray.tray_manager import PredatorTrayManager
from predator_music_sync.utils.power import PowerMonitor, set_process_power_throttling
from predator_music_sync.main import PredatorMusicSyncApp


class TestTrayLongevityFixes(unittest.TestCase):

    def test_01_process_power_throttling_and_resume_detection(self):
        if sys.platform == "win32":
            self.assertTrue(set_process_power_throttling(True))
            self.assertTrue(set_process_power_throttling(False))

        resumed = threading.Event()
        monitor = PowerMonitor(poll_interval=0.5, on_system_resume=lambda: resumed.set())
        # Simulate monotonic time jump (system wake from sleep/standby)
        with patch("predator_music_sync.utils.power.time.monotonic", side_effect=[100.0, 410.0]), \
             patch("predator_music_sync.utils.power.time.time", side_effect=[1000.0, 1310.0]), \
             patch("predator_music_sync.utils.power.time.sleep"):
            def _stop_after_one(*_args, **_kwargs):
                monitor._running = False
                return monitor._query_win32_power()

            monitor.get_status = _stop_after_one
            monitor._running = True
            monitor._monitor_loop()

        self.assertTrue(resumed.is_set(), "PowerMonitor must fire on_system_resume after sleep/idle jump")

    def test_02_pipe_worker_survives_zero_devices_and_resyncs_on_reconnect(self):
        backend = AcerLightingNamedPipeBackend.__new__(AcerLightingNamedPipeBackend)
        backend._pipe_lock = threading.RLock()
        backend._state_lock = threading.Lock()
        backend._frame_ready_event = threading.Event()
        backend._pipe_handle = INVALID_HANDLE_VALUE
        backend._is_connected = False
        backend._running = True
        backend._worker_thread = None
        backend._brightness = 100
        backend._is_static_mode = True
        backend._static_locked_color = (10, 20, 30)
        backend._static_locked_brightness = 100
        backend._force_resync = False
        backend._last_sent_scaled = [(10, 20, 30)] * 4
        backend._current_colors = [(10, 20, 30)] * 4
        backend._last_send_time = 100.0
        backend.NUM_ZONES = 4
        backend.device_index = 0
        backend.sync_auxiliary = False
        backend.devices = []
        from predator_music_sync.hardware.device_detector import parse_model_string
        backend.model_info = parse_model_string("Predator PHN16-71")

        # 1. If _get_device_count() returns 0 transiently, _init_pipe must NOT kill _running!
        with patch.object(backend, "_init_pipe_handle", return_value=True), \
             patch.object(backend, "_get_device_count", return_value=0), \
             patch("predator_music_sync.hardware.acer_pipe_windows.kernel32.CloseHandle"):
            ok = backend._init_pipe()
            self.assertFalse(ok)
            self.assertTrue(backend._running, "_init_pipe must not call close() and kill worker thread")
            self.assertIsNone(backend._static_locked_color)
            self.assertTrue(backend._force_resync)

        # 2. Failed _write_hardware_sync must NOT mark _last_sent_scaled as sent or clear _force_resync
        backend._last_sent_scaled = [(1, 2, 3)] * 4
        backend._force_resync = True
        with patch.object(backend, "set_hardware_mode", return_value=True), \
             patch.object(backend, "_write_device_raw", return_value=False):
            ok = backend._write_hardware_sync([(100, 110, 120)] * 4)
            self.assertFalse(ok)
            self.assertEqual(backend._last_sent_scaled, [(1, 2, 3)] * 4)
            self.assertTrue(backend._force_resync)

        # 3. _should_send_frame in static mode sends on _force_resync, then suppresses identical idle frames
        self.assertTrue(backend._should_send_frame([(1, 2, 3)] * 4, now=101.0))
        with patch.object(backend, "set_hardware_mode", return_value=True) as mock_mode, \
             patch.object(backend, "_write_device_raw", return_value=True):
            ok = backend._write_hardware_sync([(100, 110, 120)] * 4)
            self.assertTrue(ok)
            self.assertFalse(backend._force_resync)
            self.assertEqual(backend._last_sent_scaled, [(100, 110, 120)] * 4)
            mock_mode.assert_called_once()

        self.assertFalse(backend._should_send_frame([(100, 110, 120)] * 4, now=400.0))

        # 4. force_resync() triggers immediate re-sync in static mode
        backend.force_resync()
        self.assertTrue(backend._should_send_frame([(100, 110, 120)] * 4, now=401.0))

        # 5. _check_pipe_health detects broken pipe and triggers _handle_pipe_error
        backend._pipe_handle = 12345
        backend._is_connected = True
        with patch("predator_music_sync.hardware.acer_pipe_windows.kernel32.PeekNamedPipe", return_value=0), \
             patch("predator_music_sync.hardware.acer_pipe_windows.kernel32.CloseHandle"):
            healthy = backend._check_pipe_health()
            self.assertFalse(healthy)
            self.assertFalse(backend._is_connected)
            self.assertTrue(backend._force_resync)

    def test_03_audio_engine_recovers_from_transient_open_failure_and_stalled_stream(self):
        engine = AudioBeatSyncEngine.__new__(AudioBeatSyncEngine)
        engine.device_index = 0
        engine._preferred_device_index = 0
        engine.sample_rate = 48000
        engine.BUFFER_SIZE = 1024
        engine.noise_floor = 0.001
        engine.sensitivity = 1.15
        engine._stream = None
        engine._is_running = False
        engine._is_paused = False
        engine._last_reconnect_time = 0.0
        engine._last_callback_time = 0.0
        engine._state = AudioBeatState()
        engine._lock = threading.Lock()
        engine._stream_lock = threading.RLock()
        engine._beat_callbacks = []
        engine._setup_fft_bins()
        engine._reset_agc()

        # 1. Transient failure in start() must keep _is_running=True for health-check recovery
        with patch.object(engine, "_open_input_stream", return_value=False):
            engine.start()
            self.assertTrue(engine._is_running)

        # 2. Stalled stream (active=True, but callbacks stopped > 2.5s ago) triggers recovery & silence reset
        fake_stream = MagicMock()
        fake_stream.active = True
        engine._stream = fake_stream
        engine._state.overall_energy = 0.9
        engine._state.is_silent = False
        engine._last_callback_time = time.monotonic() - 10.0
        engine._last_reconnect_time = 0.0

        with patch.object(engine, "_recover_stream_locked") as mock_recover:
            engine._check_stream_health()
            mock_recover.assert_called_once()

        # Verify _reset_state_silence zeros stuck energy
        engine._reset_state_silence()
        self.assertTrue(engine._state.is_silent)
        self.assertEqual(engine._state.overall_energy, 0.0)

    def test_04_media_engine_json_parsing_and_fast_stop(self):
        engine = MediaSessionEngine()
        # Title containing the word "Error" must NOT be falsely rejected!
        t = engine._parse_smtc_output('{"Title":"System Error","Artist":"Error Band","AlbumTitle":"Test","HasThumbnail":false}')
        self.assertIsNotNone(t)
        self.assertEqual(t.title, "System Error")
        self.assertEqual(t.artist, "Error Band")

        # Actual JSON Error / NoSession responses must return None
        self.assertIsNone(engine._parse_smtc_output('{"Error":"COM failure"}'))
        self.assertIsNone(engine._parse_smtc_output('{"NoSession":true}'))

        # Verify start_monitoring / stop_monitoring shuts down quickly without hanging
        with patch.object(engine, "_query_windows_smtc_persistent", return_value=None), \
             patch.object(engine, "get_current_media_track", return_value=None):
            engine.start_monitoring()
            time.sleep(0.05)
            t0 = time.perf_counter()
            engine.stop_monitoring()
            self.assertLess(time.perf_counter() - t0, 0.5)

    def test_05_sync_service_resume_and_disabled_lighting_guard(self):
        service = PredatorSyncService(target_fps=60, prefer_virtual=True)
        try:
            service.set_zone_override(0, (255, 0, 0))
            service.toggle_lighting(False)
            service.controller.force_resync = MagicMock()
            service.audio_engine.recover_if_stalled = MagicMock()

            service.start()
            time.sleep(0.08)

            # Disabled lighting must stay black even with zone_overrides set
            self.assertEqual(service._latest_colors, [(0, 0, 0)] * 4)

            # System resume hook triggers audio recovery & hardware force_resync
            service._on_system_resume()
            service.audio_engine.recover_if_stalled.assert_called_once()
            service.controller.force_resync.assert_called_once()
        finally:
            service.stop()

    def test_06_tray_manager_thread_safety_and_hardware_status(self):
        tray = PredatorTrayManager(
            on_show_window=lambda: None,
            on_hide_window=lambda: None,
            on_toggle_lighting=lambda _a: None,
            on_set_mode=lambda _m: None,
            on_exit_app=lambda: None,
        )
        fake_icon = MagicMock()
        tray._icon = fake_icon

        tray.update_hardware_status("Helios Neo 16 [CONNECTED]")
        self.assertEqual(tray._hw_status_text, "Helios Neo 16 [CONNECTED]")
        fake_icon.update_menu.assert_called_once()

        # Duplicate status should not trigger redundant HMENU rebuilds
        tray.update_hardware_status("Helios Neo 16 [CONNECTED]")
        fake_icon.update_menu.assert_called_once()

        # Dynamic menu item renders latest hardware status
        menu = tray.build_menu()
        hw_items = [it for it in menu.items if "Hardware:" in str(it.text)]
        self.assertTrue(hw_items)
        self.assertIn("Helios Neo 16 [CONNECTED]", str(hw_items[0].text))

        # Concurrent updates across threads should not raise
        errors = []

        def worker(i):
            try:
                for n in range(25):
                    tray.update_power_status(n % 2 == 0, False, 100 - (n % 50))
                    tray.update_mode("Static Album Art" if n % 2 else "Dynamic Studio EQ")
                    tray.update_lighting_state(n % 2 == 0)
                    tray.update_hardware_status(f"Dev {i}-{n}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_07_main_app_tray_hide_restore_and_cross_thread_dedup(self):
        app = PredatorMusicSyncApp(target_fps=60, prefer_virtual=True, start_minimized=False)
        app.service.start()
        app.gui.create_window()
        app._start_gui_queue_pump()
        app.gui.root.update()

        try:
            # Hide to tray
            app.gui.hide_to_tray()
            app.gui.root.update()
            self.assertEqual(app.gui.root.state(), "withdrawn")
            self.assertFalse(app.gui._is_gui_active)

            # Track dedup: repeated identical tracks must only call update_track_info once
            track = MediaTrackInfo(title="Song", artist="Artist", album="Album", cover_path=None)
            with patch.object(app.gui, "update_track_info", wraps=app.gui.update_track_info) as mock_track:
                for _ in range(20):
                    app._on_service_state_tick([(10, 20, 30)] * 4, track, AudioBeatState())
                self.assertEqual(mock_track.call_count, 1)

            # Hardware connection dedup: repeated ticks while disconnected must schedule at most once
            with patch.object(app, "_dispatch_to_gui", wraps=app._dispatch_to_gui) as mock_disp:
                app._last_gui_hw_connected = True
                app.service.controller._is_connected = False
                for _ in range(20):
                    app._on_service_state_tick([(10, 20, 30)] * 4, track, AudioBeatState())
                self.assertEqual(mock_disp.call_count, 1)

            # Power status update from background thread while hidden in tray, followed by restore from bg thread
            done = threading.Event()

            def bg_actions():
                app.service.power_monitor.set_mock_status(is_plugged=False, is_battery_saver=False, percent=77)
                time.sleep(0.05)
                app.restore_window()
                time.sleep(0.05)
                done.set()

            threading.Thread(target=bg_actions, daemon=True).start()
            deadline = time.perf_counter() + 2.0
            while not done.is_set() and time.perf_counter() < deadline:
                app.gui.root.update()
                time.sleep(0.01)
            app.gui.root.update()

            self.assertNotEqual(app.gui.root.state(), "withdrawn")
            self.assertTrue(app.gui._is_gui_active)
            self.assertFalse(app.gui._is_plugged_in)
            self.assertEqual(app.gui._battery_percent, 77)
        finally:
            app.exit_completely()


if __name__ == "__main__":
    unittest.main(verbosity=2)
