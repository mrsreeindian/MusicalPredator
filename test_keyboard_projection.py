"""
Unit & Integration Tests for Keyboard Projection Fidelity, Zone Mapping,
Keycap Symbols, Virtual Hardware Parity, and Animation Engine Behavior.
"""

import os
import sys
import unittest
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from predator_music_sync.gui.toolbar import PredatorMusicToolbar, _blend_over_base, _scale_rgb_brightness
from predator_music_sync.core.animations import (
    ANIMATION_REGISTRY,
    KnightRiderScanner,
    PingPongRebound,
    StaticAlbumArt,
    StaticAlbumPrimary,
)
from predator_music_sync.core.audio_engine import AudioBeatState
from predator_music_sync.core.color_extractor import ColorPalette
from predator_music_sync.hardware.device_detector import (
    KeyboardType,
    LaptopModelInfo,
    map_4zone_to_n,
    map_auxiliary_device_colors,
    parse_model_string,
    set_mock_laptop_model,
    clear_mock_laptop_model,
)
from predator_music_sync.hardware.virtual_keyboard import VirtualKeyboardBackend


class TestKeyboardProjection(unittest.TestCase):

    def setUp(self):
        clear_mock_laptop_model()

    def tearDown(self):
        clear_mock_laptop_model()

    def _make_toolbar(self, laptop_info=None, brightness=100):
        info = laptop_info or parse_model_string("Predator PHN16-71")
        tb = PredatorMusicToolbar(
            laptop_info=info,
            controller_name=info.display_name,
            is_hardware_connected=True,
            initial_mode="Dynamic Studio EQ",
            initial_brightness=brightness,
        )
        tb.create_window()
        tb.root.update()
        tb._draw_full_keyboard()
        tb._redraw_lightbar_canvas()
        return tb

    def test_key_layout_no_overlaps_and_accurate_symbols(self):
        tb = self._make_toolbar()
        try:
            self.assertEqual(len(tb._kb_key_rects), 100)
            self.assertEqual(len(tb._kb_key_wasd), 4)
            self.assertEqual(len(tb._kb_key_arrows), 4)
            self.assertEqual(len(tb._kb_key_predator), 1)

            # Verify directional arrow symbols are uniform and symmetric
            arrow_labels = [
                tb._kb_key_labels[i]
                for i, r in enumerate(tb._kb_key_rects)
                if r in tb._kb_key_arrows
            ]
            self.assertEqual(set(arrow_labels), {"↑", "↓", "←", "→"})

            # Verify no duplicate '+' on numpad and Row 5 numpad ('0', '.') + tall 'ENT' exist
            numpad_labels = [
                tb._kb_key_labels[i]
                for i, z in enumerate(tb._kb_key_zones)
                if z == 3
            ]
            self.assertEqual(numpad_labels.count("+"), 1)
            self.assertEqual(numpad_labels.count("ENT"), 1)
            self.assertIn("0", numpad_labels)
            self.assertIn(".", numpad_labels)
            self.assertIn("[P]", numpad_labels)

            # Verify zero physical bounding-box overlap between any two keycaps
            boxes = []
            for idx, r in enumerate(tb._kb_key_rects):
                coords = tb._canvas_kb.coords(r)
                boxes.append((idx, tb._kb_key_labels[idx], coords))

            for i in range(len(boxes)):
                _, lbl_a, (ax1, ay1, ax2, ay2) = boxes[i]
                for j in range(i + 1, len(boxes)):
                    _, lbl_b, (bx1, by1, bx2, by2) = boxes[j]
                    overlap_x = min(ax2, bx2) - max(ax1, bx1)
                    overlap_y = min(ay2, by2) - max(ay1, by1)
                    self.assertFalse(
                        overlap_x > 0.5 and overlap_y > 0.5,
                        f"Keycap overlap between {lbl_a} and {lbl_b}: ({ax1},{ay1},{ax2},{ay2}) vs ({bx1},{by1},{bx2},{by2})"
                    )
        finally:
            tb.exit_application()

    def test_4zone_key_colors_and_polygon_backdrops_match(self):
        tb = self._make_toolbar()
        try:
            palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
            tb.update_zone_colors(palette)
            tb._render_gui_frame()

            self.assertEqual(len(tb._kb_zone_backs), 4)
            # Every keycap fill must match its assigned zone color blended over base
            for idx, k_rect in enumerate(tb._kb_key_rects):
                z = tb._kb_key_zones[idx]
                is_gamer = (k_rect in tb._kb_key_wasd) or (k_rect in tb._kb_key_arrows)
                base = (20, 20, 20) if is_gamer else (15, 15, 15)
                factor = 0.60 if is_gamer else 0.32
                expected_fill = _blend_over_base(base, palette[z], factor)
                actual_fill = tb._canvas_kb.itemcget(k_rect, "fill")
                self.assertEqual(
                    actual_fill.lower(),
                    expected_fill.lower(),
                    f"Zone mismatch on key {tb._kb_key_labels[idx]} (zone {z})"
                )

            # Verify each keycap center X lies strictly inside its zone backdrop X bounds at key Y
            for idx, k_rect in enumerate(tb._kb_key_rects):
                z = tb._kb_key_zones[idx]
                kx1, ky1, kx2, ky2 = tb._canvas_kb.coords(k_rect)
                cx = (kx1 + kx2) / 2.0
                cy = (ky1 + ky2) / 2.0
                poly = tb._canvas_kb.coords(tb._kb_zone_backs[z])
                # Ray-cast point-in-polygon check
                inside = False
                n = len(poly) // 2
                for p in range(n):
                    x1, y1 = poly[2 * p], poly[2 * p + 1]
                    x2, y2 = poly[2 * ((p + 1) % n)], poly[2 * ((p + 1) % n) + 1]
                    if ((y1 > cy) != (y2 > cy)) and (cx < (x2 - x1) * (cy - y1) / (y2 - y1 + 1e-9) + x1):
                        inside = not inside
                self.assertTrue(
                    inside,
                    f"Key {tb._kb_key_labels[idx]} (zone {z}) lies outside its zone backdrop polygon!"
                )
        finally:
            tb.exit_application()

    def test_3zone_and_1zone_and_per_key_projection_parity(self):
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]

        # 1. 3-Zone RGB (Triton 300): must use [Z1, avg(Z2, Z3), Z4] and include Z4!
        triton_3 = parse_model_string("Predator PT315-52")
        self.assertEqual(triton_3.keyboard_type, KeyboardType.THREE_ZONE_RGB)
        tb3 = self._make_toolbar(laptop_info=triton_3)
        try:
            tb3.update_zone_colors(palette)
            tb3._render_gui_frame()
            mapped_3 = map_4zone_to_n(palette, 3)
            self.assertEqual(len(tb3._kb_zone_backs), 3)
            # Rightmost key ('END' / 'ENT') must show Zone 4 (Yellow), NOT Zone 3 (Blue)
            right_idx = tb3._kb_key_labels.index("END")
            actual_right_fill = tb3._canvas_kb.itemcget(tb3._kb_key_rects[right_idx], "fill")
            expected_right_fill = _blend_over_base((15, 15, 15), mapped_3[2], 0.32)
            self.assertEqual(actual_right_fill.lower(), expected_right_fill.lower())
        finally:
            tb3.exit_application()

        # 2. 1-Zone RGB: must unify all 4 zones to average color across 1 backdrop
        one_zone_info = LaptopModelInfo(
            model_name="Nitro One-Zone",
            series="Nitro",
            keyboard_type=KeyboardType.ONE_ZONE_RGB,
            zone_count=1,
            is_predator=False,
        )
        tb1 = self._make_toolbar(laptop_info=one_zone_info)
        try:
            tb1.update_zone_colors(palette)
            tb1._render_gui_frame()
            unified = map_4zone_to_n(palette, 1)[0]
            self.assertEqual(len(tb1._kb_zone_backs), 1)
            esc_fill = tb1._canvas_kb.itemcget(tb1._kb_key_rects[0], "fill")
            expected_esc = _blend_over_base((15, 15, 15), unified, 0.32)
            self.assertEqual(esc_fill.lower(), expected_esc.lower())
        finally:
            tb1.exit_application()

        # 3. Per-Key RGB (Helios 16): smoothstep gradient reaching Z1 at left and Z4 at right + 12-LED lightbar
        helios_16 = parse_model_string("Predator PH16-72")
        self.assertTrue(helios_16.is_per_key)
        self.assertTrue(helios_16.has_rear_lightbar)
        tbp = self._make_toolbar(laptop_info=helios_16)
        try:
            tbp.update_zone_colors(palette)
            tbp._render_gui_frame()
            self.assertEqual(len(tbp._kb_zone_backs), 24)
            self.assertEqual(len(tbp._lightbar_segs), 12)
            # Rightmost key center norm_x == 1.0 -> must receive pure Zone 4 color
            end_idx = tbp._kb_key_labels.index("END")
            self.assertAlmostEqual(tbp._kb_key_norm_x[end_idx], 1.0, places=5)
            end_fill = tbp._canvas_kb.itemcget(tbp._kb_key_rects[end_idx], "fill")
            self.assertEqual(end_fill.lower(), _blend_over_base((15, 15, 15), palette[3], 0.32).lower())
        finally:
            tbp.exit_application()

    def test_brightness_and_lighting_pause_affect_projection(self):
        tb = self._make_toolbar(brightness=100)
        try:
            palette = [(200, 100, 40), (0, 200, 255), (40, 220, 100), (255, 200, 0)]
            tb.update_zone_colors(palette)
            tb._render_gui_frame()

            # Drop brightness to 50% -> hex labels and keycaps must immediately scale by 0.5
            tb._handle_bright_change(50)
            tb._render_gui_frame()
            scaled_50 = [_scale_rgb_brightness(c, 0.5) for c in palette]
            self.assertEqual(
                tb._kb_hex_labels[0].cget("text"),
                f"#{scaled_50[0][0]:02X}{scaled_50[0][1]:02X}{scaled_50[0][2]:02X}"
            )
            esc_fill_50 = tb._canvas_kb.itemcget(tb._kb_key_rects[0], "fill")
            self.assertEqual(esc_fill_50.lower(), _blend_over_base((15, 15, 15), scaled_50[0], 0.32).lower())

            # Pause lighting -> projection drops cleanly to unlit dark plastic (#0F0F0F) and #000000
            tb.set_lighting_active(False)
            tb._render_gui_frame()
            self.assertEqual(tb._kb_hex_labels[0].cget("text"), "#000000")
            self.assertEqual(tb._canvas_kb.itemcget(tb._kb_key_rects[0], "fill").lower(), "#0f0f0f")
        finally:
            tb.exit_application()

    def test_smooth_monotonic_fade_and_animations_no_fake_cutoffs(self):
        pal = ColorPalette((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
        loud = AudioBeatState()
        loud.overall_energy = 0.85
        loud.is_beat = True
        loud.is_hard_kick = True
        loud.beat_strength = 1.0
        loud.smoothed_bands = np.array([0.9, 0.8, 0.7, 0.6], dtype=np.float32)

        silent = AudioBeatState()
        silent.overall_energy = 0.0
        silent.is_silent = True
        silent.smoothed_bands = np.zeros(4, dtype=np.float32)

        # Dynamic animations must smoothly decay on silence rather than instant hard-snap to 0 on 1 frame,
        # and converge to pure black within 0.5s.
        for name, cls in ANIMATION_REGISTRY.items():
            if name in (StaticAlbumArt.name, StaticAlbumPrimary.name):
                continue
            anim = cls()
            # Run a few active frames so internal state & output are lit
            out_active = anim.update(loud, pal, 0.016)
            self.assertGreater(max(max(c) for c in out_active), 0, f"{name} produced black during loud beat!")

            # One short 16ms silence frame should decay smoothly, not zero out abruptly if lit
            out_16ms = anim.update(silent, pal, 0.016)
            self.assertGreater(
                max(max(c) for c in out_16ms), 0,
                f"{name} snapped abruptly to 0 on a single 16ms silence dip instead of smooth decay!"
            )

            # After 0.5s of silence it must reach pure black (<= 1)
            out_500ms = anim.update(silent, pal, 0.5)
            self.assertLessEqual(
                max(max(c) for c in out_500ms), 1,
                f"{name} failed to gate to black after 500ms of silence!"
            )

        # KnightRiderScanner & PingPongRebound must respect speed multiplier
        k_slow = KnightRiderScanner()
        k_fast = KnightRiderScanner()
        k_slow.speed = 0.5
        k_fast.speed = 2.5
        k_slow.update(loud, pal, 0.016)
        k_fast.update(loud, pal, 0.016)
        self.assertGreater(k_fast._pos, k_slow._pos)

        p_slow = PingPongRebound()
        p_fast = PingPongRebound()
        p_slow.speed = 0.5
        p_fast.speed = 2.5
        p_slow.update(loud, pal, 0.016)
        p_fast.update(loud, pal, 0.016)
        self.assertGreater(p_fast._pos, p_slow._pos)

    def test_virtual_keyboard_device_led_parity(self):
        set_mock_laptop_model("Predator PH16-72")
        try:
            vk = VirtualKeyboardBackend()
            colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
            self.assertTrue(vk.set_all_zones(colors, is_beat=False))
            self.assertEqual(len(vk.get_device_led_colors(0)), 84)
            self.assertEqual(len(vk.get_device_led_colors(1)), 12)
            self.assertEqual(len(vk.get_device_led_colors(2)), 1)

            vk.brightness = 50
            kb_50 = vk.get_device_led_colors(0)
            self.assertEqual(kb_50[0], (128, 0, 0))
            self.assertEqual(kb_50[-1], (128, 128, 0))
        finally:
            clear_mock_laptop_model()


if __name__ == "__main__":
    unittest.main(verbosity=2)
