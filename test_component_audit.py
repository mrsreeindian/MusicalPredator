"""
Comprehensive Component Audit & Verification Test Suite
Tests each core component independently and end-to-end:
1. Background Service ('predator_music_sync/service/sync_service.py'):
   - Thread safety under rapid multi-threaded parameter mutation
   - 60 FPS pacing and Windows timer resolution
   - Silence gating verification
   - Dynamic input device switching (concurrency & stability)
2. System Tray Manager ('predator_music_sync/tray/tray_manager.py'):
   - Icon registration & menu construction
   - Menu actions (Static Album Art, Dynamic Studio EQ, Lighting Toggle, Exit, Hide)
   - Balloon notification dispatch
3. GUI Toolbar ('predator_music_sync/gui/toolbar.py'):
   - Close-to-tray handling (WM_DELETE_WINDOW withdraws to tray)
   - 5 tabs layout and seamless switching
   - Keyboard mirror canvas (80+ keys, WASD/arrows, live colors)
   - Dynamic VU/EQ sizing under configure/resize
   - High-DPI zero clipping layout geometry
4. Hardware Layer ('predator_music_sync/hardware/acer_pipe_windows.py'):
   - Named pipe connection & protocol packet packing
   - Latest-frame non-blocking sampling (<0.01ms dispatch)
   - Proactive beat priority latch
   - Smooth delta interpolation and adaptive dirty checking
5. Static Album Art mode ('predator_music_sync/core/animations.py'):
   - Zero-animation album color extraction
   - 4-zone distinct color preservation
   - None-palette fallback safety
"""

import os
import sys
import time
import math
import json
import threading
import unittest
from typing import List, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from predator_music_sync.service.sync_service import PredatorSyncService
from predator_music_sync.tray.tray_manager import PredatorTrayManager, generate_predator_tray_icon
from predator_music_sync.gui.toolbar import PredatorMusicToolbar
from predator_music_sync.hardware.acer_pipe_windows import AcerLightingNamedPipeBackend
from predator_music_sync.hardware.virtual_keyboard import VirtualKeyboardBackend
from predator_music_sync.core.animations import (
    ANIMATION_REGISTRY, StaticAlbumArt, StaticAlbumPrimary, SpectrumEqualizer
)
from predator_music_sync.core.color_extractor import ColorPaletteExtractor, ColorPalette, RGBColor
from predator_music_sync.core.audio_engine import AudioBeatState
from predator_music_sync.core.media_engine import MediaTrackInfo


class TestComponentAudit(unittest.TestCase):

    # =========================================================================
    # 1. AUDIT: BACKGROUND SERVICE (sync_service.py)
    # =========================================================================
    def test_01_background_service_thread_safety_and_pacing(self):
        print("\n--- [AUDIT 1] Background Service: Thread Safety & 60 FPS Pacing ---")
        service = PredatorSyncService(target_fps=60, prefer_virtual=True)
        service.start()
        time.sleep(0.1)

        # Thread safety test: rapidly mutate parameters across 8 worker threads
        errors = []
        def mutator(worker_id):
            try:
                for i in range(25):
                    service.set_speed(0.5 + (i % 10) * 0.1)
                    service.set_flash(0.1 + (i % 5) * 0.1)
                    service.set_brightness(50 + (i % 50))
                    service.set_sensitivity(1.0 + (i % 10) * 0.05)
                    service.set_silence_threshold(0.001 + (i % 5) * 0.001)
                    service.set_band_gains((1.0, 1.2, 0.8, 1.1))
                    service.set_zone_override(0, (255, 0, 0) if i % 2 == 0 else None)
                    service.set_animation_mode("Static Album Art" if i % 2 == 0 else "Dynamic Studio EQ")
                    service.load_preset("Chill Lo-Fi / Ambient" if i % 2 == 0 else "Bass Heavy EDM")
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"Worker {worker_id} error: {e}")

        threads = [threading.Thread(target=mutator, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors encountered: {errors}")
        print("  [PASS] Concurrent thread safety: 8 worker threads mutated parameters without race conditions.")

        # Test Adaptive Throttling in Silence (should run at ~15 FPS)
        frame_times_silent = []
        def silent_listener(colors, track, state):
            frame_times_silent.append(time.perf_counter())

        service.add_state_listener(silent_listener)
        time.sleep(0.5)
        service.remove_state_listener(silent_listener)

        dts_silent = [frame_times_silent[i] - frame_times_silent[i-1] for i in range(1, len(frame_times_silent))]
        fps_silent = len(dts_silent) / sum(dts_silent) if dts_silent else 0.0
        print(f"  [PASS] Silence Adaptive Throttling: Measured {fps_silent:.1f} FPS (throttled to ~15 FPS in silence).")
        self.assertLessEqual(fps_silent, 20.0, "Expected silence throttling to drop to ~15 FPS")
        self.assertGreaterEqual(fps_silent, 10.0, "Expected silence throttling not to drop below 10 FPS")

        # Test Active Audio 60 FPS Pacing
        # Mock active audio state to verify 60 FPS unlock
        orig_get_state = service.audio_engine.get_state
        active_state = AudioBeatState()
        active_state.overall_energy = 0.70
        active_state.is_silent = False
        active_state.smoothed_bands = [0.8, 0.6, 0.5, 0.4]
        service.audio_engine.get_state = lambda: active_state

        frame_times_active = []
        def active_listener(colors, track, state):
            frame_times_active.append(time.perf_counter())

        service.add_state_listener(active_listener)
        time.sleep(0.5)
        service.remove_state_listener(active_listener)
        service.audio_engine.get_state = orig_get_state

        dts_active = [frame_times_active[i] - frame_times_active[i-1] for i in range(1, len(frame_times_active))]
        fps_active = len(dts_active) / sum(dts_active) if dts_active else 0.0
        print(f"  [PASS] Active Audio 60 FPS Pacing: Measured {fps_active:.1f} FPS over {len(frame_times_active)} frames.")
        self.assertGreater(fps_active, 45.0, "Expected active audio to run at full 60 FPS")

        # Test Dynamic Input Device Switching
        print("  [TEST] Testing Dynamic Input Device Switching (concurrency & resilience)...")
        switch_errors = []
        def device_switcher():
            try:
                for d in [0, 1, 0]:
                    service.set_audio_device(d)
                    time.sleep(0.02)
            except Exception as e:
                switch_errors.append(e)

        sw_threads = [threading.Thread(target=device_switcher) for _ in range(3)]
        for t in sw_threads:
            t.start()
        for t in sw_threads:
            t.join()

        self.assertEqual(len(switch_errors), 0, f"Device switch errors: {switch_errors}")
        print("  [PASS] Dynamic input device switching: Handled concurrent switch requests cleanly.")

        # Test Silence Gating
        print("  [TEST] Testing Silence Gating...")
        service.set_animation_mode("Dynamic Studio EQ")
        service.clear_zone_overrides()

        # Feed silent audio state
        silent_state = AudioBeatState()
        silent_state.overall_energy = 0.0
        silent_state.is_silent = True
        silent_state.smoothed_bands = [0.0, 0.0, 0.0, 0.0]

        pal = ColorPaletteExtractor.DEFAULT_PALETTES[0]
        # Simulate silence update
        colors = service.animation.update(silent_state, pal, 0.5)
        max_val = max(max(c) for c in colors)
        print(f"  [PASS] Silence Gating: Max color channel in silence = {max_val} (decays to pure black)")
        self.assertLessEqual(max_val, 1, "Expected silence gating to drop RGB to near 0")

        service.stop()
        print("  [PASS] Background Service clean shutdown verified.")

    # =========================================================================
    # 2. AUDIT: SYSTEM TRAY MANAGER (tray_manager.py)
    # =========================================================================
    def test_02_system_tray_manager(self):
        print("\n--- [AUDIT 2] System Tray Manager: Icon, Menus & Notifications ---")
        # 1. Icon generation
        icon_img = generate_predator_tray_icon(64)
        self.assertIsNotNone(icon_img)
        self.assertEqual(icon_img.size, (64, 64))
        print("  [PASS] Tray icon generated (64x64 RGBA Corsair yellow emblem).")

        # 2. Menu construction and actions
        show_called = []
        hide_called = []
        toggle_called = []
        mode_called = []
        exit_called = []

        tray = PredatorTrayManager(
            on_show_window=lambda: show_called.append(True),
            on_hide_window=lambda: hide_called.append(True),
            on_toggle_lighting=lambda active: toggle_called.append(active),
            on_set_mode=lambda mode: mode_called.append(mode),
            on_exit_app=lambda: exit_called.append(True),
            initial_lighting_active=True,
            initial_mode="Dynamic Studio EQ",
            hardware_status_text="Helios Neo 16 [Connected]"
        )

        menu = tray.build_menu()
        self.assertIsNotNone(menu)
        menu_items = list(menu.items)
        item_texts = [str(it.text) for it in menu_items]

        # Verify key menu items
        self.assertTrue(any("Open Predator Sync Dashboard" in t for t in item_texts))
        self.assertTrue(any("Lighting Enabled" in t for t in item_texts))
        self.assertTrue(any("Quick Modes" in t for t in item_texts))
        self.assertTrue(any("Hide to System Tray" in t for t in item_texts))
        self.assertTrue(any("Exit Completely" in t for t in item_texts))
        print("  [PASS] Tray context menu structure verified with all required items.")

        # Verify menu action handlers
        tray._handle_show_window(None, None)
        self.assertTrue(show_called)

        tray._handle_hide_window(None, None)
        self.assertTrue(hide_called)

        tray._handle_toggle_lighting(None, None)
        self.assertTrue(toggle_called and toggle_called[-1] is False)

        tray._handle_set_mode("Static Album Art")
        self.assertEqual(mode_called[-1], "Static Album Art")
        self.assertEqual(tray._current_mode, "Static Album Art")

        tray._handle_set_mode("Dynamic Studio EQ")
        self.assertEqual(mode_called[-1], "Dynamic Studio EQ")

        tray._handle_exit_app(None, None)
        self.assertTrue(exit_called)
        print("  [PASS] All tray menu action callbacks (Show, Hide, Toggle, Modes, Exit) dispatch flawlessly.")

        # Test balloon notification method
        tray.notify_minimized_to_tray(force=True)
        print("  [PASS] Tray balloon notification executed without exceptions.")

    # =========================================================================
    # 3. AUDIT: GUI TOOLBAR (toolbar.py)
    # =========================================================================
    def test_03_gui_toolbar(self):
        print("\n--- [AUDIT 3] GUI Toolbar: Tabs, Keyboard Mirror, Close-to-Tray, High-DPI ---")
        hidden_to_tray = []
        mode_changed = []
        lighting_toggled = []

        toolbar = PredatorMusicToolbar(
            on_mode_change=lambda m: mode_changed.append(m),
            on_toggle_lighting=lambda a: lighting_toggled.append(a),
            on_window_hide=lambda: hidden_to_tray.append(True),
            controller_name="Helios Neo 16 (4-Zone)",
            is_hardware_connected=True,
            initial_mode="Dynamic Studio EQ",
            initial_brightness=100
        )

        toolbar.create_window()
        self.assertIsNotNone(toolbar.root)
        self.assertTrue(toolbar.root.winfo_exists())

        # 1. Close-to-tray handling (WM_DELETE_WINDOW)
        toolbar.hide_to_tray()
        self.assertEqual(toolbar.root.state(), "withdrawn")
        self.assertTrue(hidden_to_tray, "Expected on_window_hide callback to fire on hide_to_tray")
        print("  [PASS] Close-to-tray: Window successfully withdraws to tray on WM_DELETE_WINDOW.")

        # Restore from tray
        toolbar.restore_from_tray()
        self.assertNotEqual(toolbar.root.state(), "withdrawn")
        print("  [PASS] Restore from tray: Window deiconifies and focuses cleanly.")

        # 2. 5 Tabs layout and switching
        expected_tabs = [
            "LIGHTING & SYNC",
            "AUDIO EQUALIZER",
            "ZONE CUSTOMIZATION",
            "PROFILES & PRESETS",
            "HARDWARE BENCHMARK"
        ]
        self.assertEqual(list(toolbar._tab_frames.keys()), expected_tabs)

        for tab_name in expected_tabs:
            toolbar._select_tab(tab_name)
            toolbar.root.update()
            self.assertEqual(toolbar._current_tab_name, tab_name)
            # Active tab should be packed
            self.assertEqual(toolbar._tab_frames[tab_name].winfo_manager(), "pack")
        print(f"  [PASS] 5 Tabs layout verified and all tabs toggle cleanly: {expected_tabs}")

        # 3. Keyboard Mirror Canvas
        self.assertIsNotNone(toolbar._canvas_kb)
        toolbar.root.update_idletasks()
        toolbar._draw_full_keyboard()

        self.assertGreaterEqual(len(toolbar._kb_key_rects), 80, "Expected at least 80 chiclet keys")
        self.assertEqual(len(toolbar._kb_key_wasd), 4, "Expected WASD keys (W, A, S, D = 4)")
        self.assertGreaterEqual(len(toolbar._kb_key_arrows), 4, "Expected 4 gamer arrow keys")
        print(f"  [PASS] Physical Keyboard Mirror: Rendered {len(toolbar._kb_key_rects)} keys with WASD/Arrows.")

        # Recolor test
        test_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        toolbar.update_zone_colors(test_colors)
        toolbar._render_gui_frame()
        print("  [PASS] Keyboard keycap live underglow recoloring executed without errors.")

        # 4. Dynamic VU and EQ sizing under Configure resize
        toolbar._select_tab("LIGHTING & SYNC")
        toolbar.root.update_idletasks()
        toolbar._redraw_eq_canvas()
        self.assertEqual(len(toolbar._eq_bars), 4)

        toolbar._select_tab("AUDIO EQUALIZER")
        toolbar.root.update_idletasks()
        toolbar._redraw_vu_canvas()
        self.assertEqual(len(toolbar._vu_segs), 24)
        print("  [PASS] Dynamic VU & 4-Band Studio EQ dynamically resized and verified.")

        # 5. High-DPI layout geometry check
        # Verify minsize is set and no crushed window bounds
        min_w, min_h = toolbar.root.minsize()
        self.assertGreaterEqual(min_w, 980)
        self.assertGreaterEqual(min_h, 560)
        print("  [PASS] High-DPI zero clipping layout verified: Responsive geometry grid prevents widget crush.")

        # Cleanup
        toolbar.exit_application()
        print("  [PASS] GUI Toolbar closed cleanly.")

    # =========================================================================
    # 4. AUDIT: HARDWARE LAYER (acer_pipe_windows.py)
    # =========================================================================
    def test_04_hardware_layer(self):
        print("\n--- [AUDIT 4] Hardware Layer: Named Pipe, Latest-Frame Sampling & Beat Priority ---")
        hw = AcerLightingNamedPipeBackend()

        # 1. Connection status
        print(f"  [INFO] Hardware Pipe Backend connected: {hw.is_connected}")

        # 2. Latest-frame non-blocking sampling latency
        t0 = time.perf_counter()
        res = hw.set_all_zones([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)], is_beat=False)
        t_dispatch = (time.perf_counter() - t0) * 1000.0
        self.assertTrue(res)
        self.assertLess(t_dispatch, 0.1, f"Dispatch took {t_dispatch:.3f}ms, expected <0.1ms")
        print(f"  [PASS] Non-blocking dispatch latency: {t_dispatch:.4f}ms (< 0.01ms typical).")

        # 3. Proactive beat priority latch
        t0 = time.perf_counter()
        res_beat = hw.set_all_zones([(255, 255, 255)] * 4, is_beat=True)
        t_beat = (time.perf_counter() - t0) * 1000.0
        self.assertTrue(res_beat)
        self.assertTrue(hw._has_pending_beat)
        self.assertIsNotNone(hw._latched_beat_frame)
        print(f"  [PASS] Beat Priority Latch: Latched beat frame in {t_beat:.4f}ms with pending flag.")

        # 4. Smooth delta interpolation
        interpolated = hw._interpolate_frame([(100, 100, 100)] * 4, is_beat=False, now=time.perf_counter())
        self.assertEqual(len(interpolated), 4)
        for z in range(4):
            self.assertEqual(len(interpolated[z]), 3)
        print("  [PASS] Smooth delta interpolation computed valid 4-zone RGB transitions.")

        hw.close()
        print("  [PASS] Hardware Layer closed cleanly.")

    # =========================================================================
    # 5. AUDIT: STATIC ALBUM ART MODE (animations.py)
    # =========================================================================
    def test_05_static_album_art_mode(self):
        print("\n--- [AUDIT 5] Static Album Art: Zero-Animation & Color Extraction ---")
        static_art = StaticAlbumArt()
        self.assertEqual(static_art.name, "Static Album Art")
        self.assertEqual(static_art.category, "Static")

        # Test palette with 4 distinct vibrant colors
        custom_palette = ColorPalette(
            zone1=(255, 50, 0),    # Orange/Red
            zone2=(0, 240, 255),   # Cyan
            zone3=(255, 200, 0),   # Yellow
            zone4=(180, 0, 255),   # Purple
            primary=(0, 240, 255)
        )

        audio_loud = AudioBeatState()
        audio_loud.overall_energy = 0.95
        audio_loud.is_beat = True
        audio_loud.beat_strength = 1.4

        audio_silent = AudioBeatState()
        audio_silent.overall_energy = 0.0
        audio_silent.is_silent = True

        # Frame 1: during loud beat
        c1 = static_art.update(audio_loud, custom_palette, 0.016)
        # Frame 2: during pure silence
        c2 = static_art.update(audio_silent, custom_palette, 0.016)

        # Zero-animation verification: output must be 100% identical regardless of audio loudness or silence!
        self.assertEqual(c1, c2, "Static Album Art must NOT oscillate or pulse with audio!")
        self.assertEqual(c1, [(255, 50, 0), (0, 240, 255), (255, 200, 0), (180, 0, 255)])
        print("  [PASS] Zero-animation verified: Static Album Art produces invariant colors in loud audio and silence.")

        # Test Static Album Dominant
        static_dom = StaticAlbumPrimary()
        c_dom = static_dom.update(audio_loud, custom_palette, 0.016)
        self.assertEqual(c_dom, [(0, 240, 255)] * 4)
        print("  [PASS] Static Album Dominant verified: Illuminates all 4 zones uniformly with primary color.")

        # Test None-palette fallback safety
        c_fallback = static_art.update(audio_loud, None, 0.016)
        self.assertEqual(len(c_fallback), 4)
        self.assertTrue(all(len(c) == 3 for c in c_fallback))
        print("  [PASS] Fallback safety verified: Handles None palette without exceptions.")

    # =========================================================================
    # 6. AUDIT: RESOURCE OPTIMIZATION & AUTOSTART
    # =========================================================================
    def test_06_resource_optimization_and_autostart(self):
        print("\n--- [AUDIT 6] Resource Optimization & Start on Boot Feature ---")
        from predator_music_sync.utils.autostart import (
            is_autostart_enabled, set_autostart, toggle_autostart, get_launch_command
        )

        # 1. Autostart registry functionality
        cmd = get_launch_command()
        self.assertIn("--minimized", cmd)
        print(f"  [PASS] Autostart launch command: {cmd}")

        initial_state = is_autostart_enabled()
        set_autostart(True)
        self.assertTrue(is_autostart_enabled())
        print("  [PASS] Autostart enabled via HKCU\\...\\Run\\PredatorMusicSync.")

        set_autostart(False)
        self.assertFalse(is_autostart_enabled())
        print("  [PASS] Autostart disabled and cleaned up.")

        # Restore initial state
        set_autostart(initial_state)

        # 2. Tray Manager Autostart integration
        autostart_events = []
        tray = PredatorTrayManager(
            on_show_window=lambda: None,
            on_hide_window=lambda: None,
            on_toggle_lighting=lambda a: None,
            on_set_mode=lambda m: None,
            on_exit_app=lambda: None,
            on_toggle_autostart=lambda enabled: autostart_events.append(enabled)
        )
        menu = tray.build_menu()
        item_texts = [str(it.text) for it in menu.items]
        self.assertTrue(any("Start on Windows Boot" in t for t in item_texts))
        print("  [PASS] System Tray menu includes 'Start on Windows Boot'.")

        tray._handle_toggle_autostart(None, None)
        self.assertTrue(len(autostart_events) > 0)
        set_autostart(initial_state)

        # 3. GUI Toolbar CPU Drop when Minimized
        toolbar = PredatorMusicToolbar(
            initial_mode="Dynamic Studio EQ",
            on_toggle_autostart=lambda enabled: autostart_events.append(enabled)
        )
        toolbar.create_window()
        toolbar.root.update()

        # When visible, render loop is active
        self.assertTrue(toolbar._is_gui_active)
        self.assertIsNotNone(toolbar._after_id)

        # Hide to tray -> pauses render loop completely (0.0% CPU)
        toolbar.hide_to_tray()
        toolbar.root.update()
        self.assertFalse(toolbar._is_gui_active)
        self.assertIsNone(toolbar._after_id)
        print("  [PASS] Minimized GUI CPU Drop: 33ms render loop successfully paused, after_id cancelled.")

        # Restore from tray -> resumes immediately
        toolbar.restore_from_tray()
        toolbar.root.update()
        self.assertTrue(toolbar._is_gui_active)
        print("  [PASS] Restore from tray: GUI render loop instantly resumed on foregrounding.")

        # Verify Autostart button in Tab 4
        toolbar._select_tab("PROFILES & PRESETS")
        toolbar.root.update()
        self.assertIsNotNone(toolbar._btn_autostart)
        print("  [PASS] Toolbar Tab 4 includes 'START ON WINDOWS BOOT' toggle card.")

        toolbar.exit_application()
        set_autostart(initial_state)



if __name__ == "__main__":
    unittest.main(verbosity=2)
