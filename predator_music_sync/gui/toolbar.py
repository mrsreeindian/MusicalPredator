"""
Predator Keyboard Music Sync - Full-Fledged Desktop Application Suite
Predator Dark-inspired minimal pure black industrial design language.
Features:
  - Pure black root (#000000), dark charcoal panels (#0A0A0A, #121212), 1px hairline borders (#1E1E1E).
  - Predator signature electric yellow accents (#FFD100) and crisp white typography.
  - Full-resolution realistic top-down rendering of the Acer Predator Helios Neo 16 keyboard
    (80+ chiclet keys, prominent frosted WASD and Arrow gamer keycaps, live 4-zone underglow and hex readouts).
  - 5 Predator Dark-style navigation tabs:
    * TAB 1: [LIGHTING & SYNC] - Effect selector, color themes, precision sliders, now playing, 4-band studio EQ.
    * TAB 2: [AUDIO EQUALIZER & TUNING] - Input device selector, 24-segment Master VU meter, noise gate, 4-band gain sliders.
    * TAB 3: [ZONE CUSTOMIZATION] - Per-zone static color override / lock toggles (e.g. lock WASD to static red for gaming).
    * TAB 4: [PROFILES & PRESETS] - 5 one-click instant profiles and JSON profile save/load.
    * TAB 5: [HARDWARE BENCHMARK] - Embedded real-time multi-pass benchmark runner with latency monitor.
  - Bottom hardware telemetry status bar.
"""

import os
import sys
import json
import time
import math
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
from typing import Optional, Callable, List, Tuple, Dict, Any
from PIL import Image, ImageTk

from ..core.color_extractor import ColorPalette, RGBColor, ColorPaletteExtractor
from ..core.media_engine import MediaTrackInfo
from ..core.audio_engine import AudioBeatState
from ..core.animations import ANIMATION_REGISTRY
from ..utils.autostart import is_autostart_enabled, set_autostart


def _rgb_to_hex(rgb: RGBColor) -> str:
    return f"#{max(0, min(255, int(rgb[0]))):02x}{max(0, min(255, int(rgb[1]))):02x}{max(0, min(255, int(rgb[2]))):02x}"


def _dim_color(rgb: RGBColor, factor: float) -> str:
    r = int(max(0, min(255, rgb[0] * factor)))
    g = int(max(0, min(255, rgb[1] * factor)))
    b = int(max(0, min(255, rgb[2] * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


class PredatorMusicToolbar:
    """
    Full-fledged Predator Dark-inspired Desktop Application for Predator 4-Zone RGB Sync.
    Engineered with zero clunkiness, responsive layout, and crisp typography.
    """

    # Predator Dark Color System
    BG_ROOT = "#000000"           # Pure pitch black
    SURFACE_PANEL = "#0A0A0A"     # Panel surface
    SURFACE_CARD = "#111111"      # Control card container
    SURFACE_INPUT = "#161616"     # Combobox / input field
    SURFACE_ACTIVE = "#1E1E1E"    # Active tab/item highlight
    BORDER_HAIRLINE = "#1F1F1F"   # Precision 1px border
    BORDER_FOCUS = "#2E2E2E"      # Subtle hover border
    ACCENT_YELLOW = "#FFD100"    # Predator electric yellow
    ACCENT_WARN = "#FF9900"       # Warning amber
    TEXT_WHITE = "#FFFFFF"        # Crisp pure white
    TEXT_SECONDARY = "#999999"    # Subtitles and section labels
    TEXT_MUTED = "#555555"        # Fine print & technical hints
    FONT_FAMILY = "Segoe UI"
    FONT_MONO = "Consolas"

    def __init__(
        self,
        on_mode_change: Optional[Callable[[str], None]] = None,
        on_sensitivity_change: Optional[Callable[[float], None]] = None,
        on_brightness_change: Optional[Callable[[int], None]] = None,
        on_speed_change: Optional[Callable[[float], None]] = None,
        on_flash_change: Optional[Callable[[float], None]] = None,
        on_theme_change: Optional[Callable[[str], None]] = None,
        on_audio_device_change: Optional[Callable[[int], None]] = None,
        on_toggle_lighting: Optional[Callable[[bool], None]] = None,
        on_zone_override_change: Optional[Callable[[int, Optional[RGBColor]], None]] = None,
        on_band_gain_change: Optional[Callable[[Tuple[float, float, float, float]], None]] = None,
        on_silence_threshold_change: Optional[Callable[[float], None]] = None,
        on_save_profile: Optional[Callable[[str, str], None]] = None,
        on_load_profile: Optional[Callable[[str], None]] = None,
        on_load_preset: Optional[Callable[[str], None]] = None,
        on_run_benchmark: Optional[Callable[[], None]] = None,
        on_window_hide: Optional[Callable[[], None]] = None,
        on_toggle_autostart: Optional[Callable[[bool], None]] = None,
        controller_name: str = "Helios Neo 16 (4-Zone)",
        is_hardware_connected: bool = True,
        audio_devices: Optional[List[Tuple[int, str]]] = None,
        selected_device_index: Optional[int] = None,
        initial_mode: str = "Dynamic Studio EQ",
        initial_theme: str = "Auto (Album Cover)",
        initial_brightness: int = 100,
        initial_sensitivity: float = 1.15,
        initial_speed: float = 1.0,
        initial_flash: float = 0.20,
    ):
        self.on_mode_change = on_mode_change
        self.on_sensitivity_change = on_sensitivity_change
        self.on_brightness_change = on_brightness_change
        self.on_speed_change = on_speed_change
        self.on_flash_change = on_flash_change
        self.on_theme_change = on_theme_change
        self.on_audio_device_change = on_audio_device_change
        self.on_toggle_lighting = on_toggle_lighting
        self.on_zone_override_change = on_zone_override_change
        self.on_band_gain_change = on_band_gain_change
        self.on_silence_threshold_change = on_silence_threshold_change
        self.on_save_profile = on_save_profile
        self.on_load_profile = on_load_profile
        self.on_load_preset = on_load_preset
        self.on_run_benchmark = on_run_benchmark
        self.on_window_hide = on_window_hide
        self.on_toggle_autostart = on_toggle_autostart

        self.controller_name = controller_name
        self.is_hardware_connected = is_hardware_connected
        self.audio_devices = audio_devices or []
        self.selected_device_index = selected_device_index

        # Active state parameters
        self._current_mode = initial_mode
        self._current_theme = initial_theme
        self._current_brightness = initial_brightness
        self._current_sensitivity = initial_sensitivity
        self._current_speed = initial_speed
        self._current_flash = initial_flash
        self._is_lighting_active = True
        self._is_autostart_active = is_autostart_enabled()
        self._is_gui_active: bool = True

        # Equalizer band gains: [Sub-Bass, Low-Mid, High-Mid, Treble]
        self._band_gains = [1.0, 1.0, 1.0, 1.0]
        self._silence_threshold = 0.001

        # Per-zone static overrides: {zone: Optional[RGBColor]}
        self._zone_overrides: Dict[int, Optional[RGBColor]] = {0: None, 1: None, 2: None, 3: None}

        self.root: Optional[tk.Tk] = None
        self._lock = threading.Lock()
        self._after_id: Optional[str] = None

        # Live Data Buffers
        self._pending_colors: Optional[List[RGBColor]] = [
            (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)
        ]
        self._last_rendered_colors: List[RGBColor] = [
            (-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)
        ]
        self._pending_track: Optional[MediaTrackInfo] = None
        self._pending_state: Optional[AudioBeatState] = None

        # Header Widgets
        self._lbl_hw_status: Optional[tk.Label] = None
        self._lbl_header_track: Optional[tk.Label] = None
        self._btn_toggle: Optional[tk.Button] = None

        # Full Realistic Keyboard Canvas
        self._canvas_kb: Optional[tk.Canvas] = None
        self._kb_key_rects: List[int] = []
        self._kb_key_zones: List[int] = []
        self._kb_key_wasd: List[int] = []
        self._kb_key_arrows: List[int] = []
        self._kb_zone_backs: List[int] = []
        self._kb_hex_labels: List[tk.Label] = []
        self._kb_dots: List[Tuple[tk.Canvas, int]] = []  # Stores (canvas, rect_id)
        self._kb_lock_badges: List[tk.Label] = []

        # Tabs & Navigation
        self._current_tab_name = "LIGHTING & SYNC"
        self._tab_buttons: Dict[str, tk.Button] = {}
        self._tab_frames: Dict[str, tk.Frame] = {}
        self._tab_container: Optional[tk.Frame] = None

        # Tab 1: Lighting Widgets
        self._combo_mode: Optional[ttk.Combobox] = None
        self._combo_theme: Optional[ttk.Combobox] = None
        self._slider_bright: Optional[tk.Scale] = None
        self._lbl_val_bright: Optional[tk.Label] = None
        self._slider_spd: Optional[tk.Scale] = None
        self._lbl_val_spd: Optional[tk.Label] = None
        self._slider_flash: Optional[tk.Scale] = None
        self._lbl_val_flash: Optional[tk.Label] = None

        # Now Playing & Spectrum (Tab 1)
        self._lbl_cover: Optional[tk.Label] = None
        self._cover_img_tk: Optional[ImageTk.PhotoImage] = None
        self._lbl_title: Optional[tk.Label] = None
        self._lbl_artist: Optional[tk.Label] = None
        self._lbl_bpm: Optional[tk.Label] = None
        self._canvas_eq: Optional[tk.Canvas] = None
        self._eq_bars: List[List[int]] = []
        self._eq_peaks: List[int] = []
        self._eq_peak_levels = [0.0, 0.0, 0.0, 0.0]

        # Tab 2: Audio EQ Widgets
        self._combo_device: Optional[ttk.Combobox] = None
        self._canvas_vu: Optional[tk.Canvas] = None
        self._vu_segs: List[int] = []
        self._vu_peak_line: Optional[int] = None
        self._vu_peak_level: float = 0.0
        self._lbl_vu_status: Optional[tk.Label] = None
        self._slider_sens: Optional[tk.Scale] = None
        self._lbl_val_sens: Optional[tk.Label] = None
        self._slider_noise: Optional[tk.Scale] = None
        self._lbl_val_noise: Optional[tk.Label] = None
        self._gain_sliders: List[tk.Scale] = []
        self._gain_val_labels: List[tk.Label] = []

        # Tab 3: Zone Customization Widgets
        self._zone_toggle_btns: List[tk.Button] = []
        self._zone_color_indicators: List[Tuple[tk.Canvas, int]] = []

        # Tab 4: Profiles Widgets
        self._entry_profile_name: Optional[tk.Entry] = None
        self._lbl_profile_status: Optional[tk.Label] = None
        self._btn_autostart: Optional[tk.Button] = None

        # Tab 5: Benchmark Widgets
        self._txt_bench: Optional[scrolledtext.ScrolledText] = None
        self._lbl_bench_bus: Optional[tk.Label] = None
        self._lbl_bench_fps: Optional[tk.Label] = None

        # Bottom Status Bar
        self._lbl_status_track: Optional[tk.Label] = None

    def create_window(self):
        """Builds and initializes the desktop application window with clean centering."""
        self.root = tk.Tk()
        self.root.title("Predator Keyboard Music Sync")

        # Set taskbar and titlebar application icon
        icon_candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "assets", "predator_icon.ico"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "predator_icon.ico"),
            os.path.join(os.path.dirname(sys.executable), "assets", "predator_icon.ico"),
            os.path.join(os.path.dirname(sys.executable), "predator_icon.ico"),
            "assets/predator_icon.ico"
        ]
        for candidate in icon_candidates:
            if candidate and os.path.exists(candidate):
                try:
                    self.root.iconbitmap(candidate)
                    break
                except Exception:
                    pass

        # Responsive geometry that fits laptops cleanly without clipping
        win_w = 1120
        win_h = 640
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            pos_x = max(0, (screen_w - win_w) // 2)
            pos_y = max(0, (screen_h - win_h) // 2)
            self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        except Exception:
            self.root.geometry(f"{win_w}x{win_h}")

        self.root.minsize(980, 560)
        self.root.configure(bg=self.BG_ROOT)

        # Style standard ttk comboboxes for pure black styling
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=self.SURFACE_INPUT,
            background=self.SURFACE_INPUT,
            foreground=self.TEXT_WHITE,
            darkcolor=self.BORDER_HAIRLINE,
            lightcolor=self.BORDER_HAIRLINE,
            arrowcolor=self.ACCENT_YELLOW,
            bordercolor=self.BORDER_HAIRLINE,
            selectbackground=self.SURFACE_ACTIVE,
            selectforeground=self.TEXT_WHITE,
            padding=4
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", self.SURFACE_INPUT)],
            selectbackground=[("readonly", self.SURFACE_INPUT)],
            selectforeground=[("readonly", self.TEXT_WHITE)]
        )

        self.root.option_add("*TCombobox*Listbox.background", self.SURFACE_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", self.TEXT_WHITE)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.ACCENT_YELLOW)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#000000")
        self.root.option_add("*TCombobox*Listbox.relief", "flat")
        self.root.option_add("*TCombobox*Listbox.borderWidth", "0")

        self._build_header_bar()
        self._build_keyboard_preview_section()
        self._build_tab_navigation_bar()
        self._build_tab_content_area()
        self._build_bottom_status_bar()

        self._schedule_gui_update()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

    # =========================================================================
    # 1. TOP HEADER BAR
    # =========================================================================
    def _build_header_bar(self):
        header = tk.Frame(self.root, bg=self.SURFACE_PANEL, height=38, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Left branding & hardware status
        left = tk.Frame(header, bg=self.SURFACE_PANEL)
        left.pack(side="left", padx=14, fill="y")

        lbl_logo = tk.Label(
            left, text="▲ PREDATOR SYNC",
            font=(self.FONT_FAMILY, 9, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL
        )
        lbl_logo.pack(side="left")

        lbl_model = tk.Label(
            left, text="// HELIOS NEO 16",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        )
        lbl_model.pack(side="left", padx=(6, 14))

        hw_color = self.ACCENT_YELLOW if self.is_hardware_connected else self.ACCENT_WARN
        hw_text = f"● {self.controller_name.upper()} [CONNECTED]" if self.is_hardware_connected else f"● {self.controller_name.upper()} [EMULATION]"
        self._lbl_hw_status = tk.Label(
            left, text=hw_text,
            font=(self.FONT_FAMILY, 7, "bold"), fg=hw_color, bg=self.SURFACE_PANEL
        )
        self._lbl_hw_status.pack(side="left")

        # Center Now Playing snippet
        center = tk.Frame(header, bg=self.SURFACE_PANEL)
        center.pack(side="left", fill="both", expand=True, padx=16)

        self._lbl_header_track = tk.Label(
            center, text="♫ Ready for playback",
            font=(self.FONT_FAMILY, 8), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL, anchor="center"
        )
        self._lbl_header_track.pack(fill="both", expand=True)

        # Right actions
        right = tk.Frame(header, bg=self.SURFACE_PANEL)
        right.pack(side="right", padx=14, fill="y")

        self._btn_toggle = tk.Button(
            right, text="LIGHTING: ACTIVE", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.ACCENT_YELLOW, activebackground=self.ACCENT_YELLOW,
            activeforeground="#000000", bd=0, padx=10, pady=2, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._toggle_lighting_state
        )
        self._btn_toggle.pack(side="left", padx=(0, 6), pady=5)

        btn_bench = tk.Button(
            right, text="DIAGNOSTICS", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, activebackground=self.ACCENT_YELLOW,
            activeforeground="#000000", bd=0, padx=10, pady=2, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: self._select_tab("HARDWARE BENCHMARK")
        )
        btn_bench.pack(side="left", padx=(0, 6), pady=5)

        btn_tray = tk.Button(
            right, text="HIDE TO TRAY", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_SECONDARY, activebackground=self.SURFACE_ACTIVE,
            activeforeground=self.TEXT_WHITE, bd=0, padx=10, pady=2, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self.hide_to_tray
        )
        btn_tray.pack(side="left", pady=5)

    # =========================================================================
    # 2. FULL REALISTIC KEYBOARD PREVIEW (Acer Predator Helios Neo 16)
    # =========================================================================
    def _build_keyboard_preview_section(self):
        panel = tk.Frame(self.root, bg=self.SURFACE_PANEL, height=182, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        panel.pack(fill="x", padx=14, pady=(6, 4))
        panel.pack_propagate(False)

        hdr = tk.Frame(panel, bg=self.SURFACE_PANEL)
        hdr.pack(fill="x", padx=10, pady=(3, 1))

        tk.Label(
            hdr, text="PHYSICAL KEYBOARD HARDWARE MIRROR",
            font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(side="left")

        tk.Label(
            hdr, text="ACER PREDATOR HELIOS NEO 16 (PHN16-71) MATRIX • 80+ KEYS",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        ).pack(side="right")

        self._canvas_kb = tk.Canvas(panel, height=120, bg=self.SURFACE_PANEL, bd=0, highlightthickness=0)
        self._canvas_kb.pack(fill="x", padx=8, pady=(1, 2))
        self._canvas_kb.bind("<Configure>", self._draw_full_keyboard)

        # Under-keyboard 4-zone telemetry bar
        info_bar = tk.Frame(panel, bg=self.SURFACE_PANEL)
        info_bar.pack(fill="x", padx=8, pady=(0, 3))

        zone_titles = [
            ("ZONE 1", "WASD / BASS (20-120Hz)"),
            ("ZONE 2", "MID-LEFT / VOCALS (120-500Hz)"),
            ("ZONE 3", "MID-RIGHT / MELODY (500-3.5kHz)"),
            ("ZONE 4", "NUMPAD / TREBLE (3.5-16kHz)")
        ]
        self._kb_hex_labels = []
        self._kb_dots = []
        self._kb_lock_badges = []

        for z in range(4):
            z_col = tk.Frame(info_bar, bg=self.SURFACE_PANEL)
            z_col.pack(side="left", fill="x", expand=True)

            top = tk.Frame(z_col, bg=self.SURFACE_PANEL)
            top.pack(anchor="w")

            dot_c = tk.Canvas(top, width=7, height=7, bg=self.SURFACE_PANEL, bd=0, highlightthickness=0)
            dot_c.pack(side="left", padx=(2, 4))
            dot = dot_c.create_rectangle(0, 0, 7, 7, fill="#000000", outline="")
            self._kb_dots.append((dot_c, dot))

            tk.Label(top, text=zone_titles[z][0], font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")

            lbl_hex = tk.Label(top, text="#000000", font=(self.FONT_MONO, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL)
            lbl_hex.pack(side="left", padx=4)
            self._kb_hex_labels.append(lbl_hex)

            lbl_lock = tk.Label(top, text="[DYNAMIC]", font=(self.FONT_FAMILY, 6, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
            lbl_lock.pack(side="left", padx=2)
            self._kb_lock_badges.append(lbl_lock)

            tk.Label(z_col, text=zone_titles[z][1], font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w", padx=12)

    def _draw_full_keyboard(self, event=None):
        """Draws realistic Acer Predator Helios Neo 16 keyboard layout with 80+ keys."""
        if not self._canvas_kb:
            return

        w = self._canvas_kb.winfo_width()
        h = self._canvas_kb.winfo_height()
        if w < 200 or h < 50:
            return

        self._canvas_kb.delete("all")
        self._kb_key_rects = []
        self._kb_key_zones = []
        self._kb_key_wasd = []
        self._kb_key_arrows = []
        self._kb_zone_backs = []

        pad_x = 4
        pad_y = 2
        well_w = w - (pad_x * 2)
        well_h = h - (pad_y * 2)

        # Outer keyboard well
        self._canvas_kb.create_rectangle(
            pad_x, pad_y, pad_x + well_w, pad_y + well_h,
            fill="#080808", outline=self.BORDER_HAIRLINE, width=1
        )

        # 4 Zone underglow backdrops
        zone_w = well_w / 4.0
        for z in range(4):
            zx1 = pad_x + (z * zone_w)
            zx2 = zx1 + zone_w
            zb = self._canvas_kb.create_rectangle(
                zx1, pad_y, zx2, pad_y + well_h,
                fill="#0D0D0D", outline="", width=0
            )
            self._kb_zone_backs.append(zb)

        # Detailed Key definitions: (row, x_rel, width_rel, label, zone, is_wasd, is_arrow, is_predator)
        keys_def = [
            # Row 0: Function Row
            (0, 0.0, 1.0, "ESC", 0, False, False, False),
            (0, 1.2, 0.9, "F1", 0, False, False, False),
            (0, 2.15, 0.9, "F2", 0, False, False, False),
            (0, 3.1, 0.9, "F3", 0, False, False, False),
            (0, 4.05, 0.9, "F4", 0, False, False, False),
            (0, 5.15, 0.9, "F5", 1, False, False, False),
            (0, 6.1, 0.9, "F6", 1, False, False, False),
            (0, 7.05, 0.9, "F7", 1, False, False, False),
            (0, 8.0, 0.9, "F8", 1, False, False, False),
            (0, 9.1, 0.9, "F9", 2, False, False, False),
            (0, 10.05, 0.9, "F10", 2, False, False, False),
            (0, 11.0, 0.9, "F11", 2, False, False, False),
            (0, 11.95, 0.9, "F12", 2, False, False, False),
            (0, 13.0, 0.9, "PRT", 2, False, False, False),
            (0, 13.95, 0.95, "DEL", 2, False, False, False),
            # Numpad Row 0
            (0, 15.2, 0.95, "[P]", 3, False, False, True),
            (0, 16.2, 0.95, "NUM", 3, False, False, False),
            (0, 17.2, 0.95, "/", 3, False, False, False),
            (0, 18.2, 0.95, "*", 3, False, False, False),

            # Row 1: Number Row
            (1, 0.0, 0.95, "~", 0, False, False, False),
            (1, 1.0, 0.95, "1", 0, False, False, False),
            (1, 2.0, 0.95, "2", 0, False, False, False),
            (1, 3.0, 0.95, "3", 0, False, False, False),
            (1, 4.0, 0.95, "4", 0, False, False, False),
            (1, 5.0, 0.95, "5", 1, False, False, False),
            (1, 6.0, 0.95, "6", 1, False, False, False),
            (1, 7.0, 0.95, "7", 1, False, False, False),
            (1, 8.0, 0.95, "8", 1, False, False, False),
            (1, 9.0, 0.95, "9", 2, False, False, False),
            (1, 10.0, 0.95, "0", 2, False, False, False),
            (1, 11.0, 0.95, "-", 2, False, False, False),
            (1, 12.0, 0.95, "=", 2, False, False, False),
            (1, 13.0, 1.9, "BACK", 2, False, False, False),
            # Numpad Row 1
            (1, 15.2, 0.95, "7", 3, False, False, False),
            (1, 16.2, 0.95, "8", 3, False, False, False),
            (1, 17.2, 0.95, "9", 3, False, False, False),
            (1, 18.2, 0.95, "-", 3, False, False, False),

            # Row 2: QWERTY Row
            (2, 0.0, 1.45, "TAB", 0, False, False, False),
            (2, 1.5, 0.95, "Q", 0, False, False, False),
            (2, 2.5, 0.95, "W", 0, True, False, False),
            (2, 3.5, 0.95, "E", 0, False, False, False),
            (2, 4.5, 0.95, "R", 0, False, False, False),
            (2, 5.5, 0.95, "T", 1, False, False, False),
            (2, 6.5, 0.95, "Y", 1, False, False, False),
            (2, 7.5, 0.95, "U", 1, False, False, False),
            (2, 8.5, 0.95, "I", 1, False, False, False),
            (2, 9.5, 0.95, "O", 2, False, False, False),
            (2, 10.5, 0.95, "P", 2, False, False, False),
            (2, 11.5, 0.95, "[", 2, False, False, False),
            (2, 12.5, 0.95, "]", 2, False, False, False),
            (2, 13.5, 1.4, "\\", 2, False, False, False),
            # Numpad Row 2
            (2, 15.2, 0.95, "4", 3, False, False, False),
            (2, 16.2, 0.95, "5", 3, False, False, False),
            (2, 17.2, 0.95, "6", 3, False, False, False),
            (2, 18.2, 0.95, "+", 3, False, False, False),

            # Row 3: Home Row
            (3, 0.0, 1.75, "CAPS", 0, False, False, False),
            (3, 1.8, 0.95, "A", 0, True, False, False),
            (3, 2.8, 0.95, "S", 0, True, False, False),
            (3, 3.8, 0.95, "D", 0, True, False, False),
            (3, 4.8, 0.95, "F", 0, False, False, False),
            (3, 5.8, 0.95, "G", 1, False, False, False),
            (3, 6.8, 0.95, "H", 1, False, False, False),
            (3, 7.8, 0.95, "J", 1, False, False, False),
            (3, 8.8, 0.95, "K", 1, False, False, False),
            (3, 9.8, 0.95, "L", 2, False, False, False),
            (3, 10.8, 0.95, ";", 2, False, False, False),
            (3, 11.8, 0.95, "'", 2, False, False, False),
            (3, 12.8, 2.1, "ENTER", 2, False, False, False),
            # Numpad Row 3
            (3, 15.2, 0.95, "1", 3, False, False, False),
            (3, 16.2, 0.95, "2", 3, False, False, False),
            (3, 17.2, 0.95, "3", 3, False, False, False),
            (3, 18.2, 0.95, "+", 3, False, False, False),

            # Row 4: Shift Row
            (4, 0.0, 2.25, "SHIFT", 0, False, False, False),
            (4, 2.3, 0.95, "Z", 0, False, False, False),
            (4, 3.3, 0.95, "X", 0, False, False, False),
            (4, 4.3, 0.95, "C", 0, False, False, False),
            (4, 5.3, 0.95, "V", 0, False, False, False),
            (4, 6.3, 0.95, "B", 1, False, False, False),
            (4, 7.3, 0.95, "N", 1, False, False, False),
            (4, 8.3, 0.95, "M", 1, False, False, False),
            (4, 9.3, 0.95, ",", 2, False, False, False),
            (4, 10.3, 0.95, ".", 2, False, False, False),
            (4, 11.3, 0.95, "/", 2, False, False, False),
            (4, 12.3, 1.55, "SHIFT", 2, False, False, False),
            (4, 13.95, 0.95, "▲", 2, False, True, False),
            # Numpad Row 4
            (4, 15.2, 1.95, "0", 3, False, False, False),
            (4, 17.2, 0.95, ".", 3, False, False, False),
            (4, 18.2, 0.95, "ENT", 3, False, False, False),

            # Row 5: Bottom Row
            (5, 0.0, 1.25, "CTRL", 0, False, False, False),
            (5, 1.3, 0.95, "FN", 0, False, False, False),
            (5, 2.3, 0.95, "WIN", 0, False, False, False),
            (5, 3.3, 1.15, "ALT", 0, False, False, False),
            (5, 4.5, 5.2, "SPACE", 1, False, False, False),
            (5, 9.8, 1.15, "ALT", 2, False, False, False),
            (5, 11.0, 1.15, "CTRL", 2, False, False, False),
            (5, 12.95, 0.95, "◀", 2, False, True, False),
            (5, 13.95, 0.95, "▼", 2, False, True, False),
            (5, 14.95, 0.95, "►", 2, False, True, False),
        ]

        total_rel_w = 19.3
        unit_w = (well_w - 12) / total_rel_w
        row_h = (well_h - 10) / 6.0

        for row, x_rel, w_rel, label, zone, is_wasd, is_arrow, is_pred in keys_def:
            kx1 = pad_x + 6 + (x_rel * unit_w)
            kx2 = kx1 + (w_rel * unit_w) - 2
            ky1 = pad_y + 4 + (row * row_h)
            ky2 = ky1 + row_h - 2

            if is_wasd:
                # Distinctive frosted white gamer keycap
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#1A1A1A", outline="#FFFFFF", width=1.5
                )
                self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 7, "bold"), fill=self.ACCENT_YELLOW
                )
                self._kb_key_wasd.append(k)
            elif is_arrow:
                # Inverted-T Arrow keys with frosted gamer outline
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#1A1A1A", outline="#FFFFFF", width=1.5
                )
                self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 7, "bold"), fill=self.ACCENT_YELLOW
                )
                self._kb_key_arrows.append(k)
            elif is_pred:
                # Iconic Predator Sense Key [P]
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#161616", outline=self.ACCENT_YELLOW, width=1.2
                )
                self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 6, "bold"), fill=self.ACCENT_YELLOW
                )
            else:
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#0F0F0F", outline=self.BORDER_HAIRLINE, width=1
                )
                font_sz = 6 if len(label) > 3 else 7
                self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, font_sz), fill=self.TEXT_SECONDARY
                )

            self._kb_key_rects.append(k)
            self._kb_key_zones.append(zone)

        # Reset rendered cache so next tick immediately paints keys with current colors
        self._last_rendered_colors = [(-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)]

    # =========================================================================
    # 3. TAB NAVIGATION BAR (Predator Dark Industrial Design)
    # =========================================================================
    def _build_tab_navigation_bar(self):
        tab_bar = tk.Frame(self.root, bg=self.SURFACE_PANEL, height=34, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        tab_bar.pack(fill="x", padx=14, pady=(0, 4))
        tab_bar.pack_propagate(False)

        tabs = [
            "LIGHTING & SYNC",
            "AUDIO EQUALIZER",
            "ZONE CUSTOMIZATION",
            "PROFILES & PRESETS",
            "HARDWARE BENCHMARK"
        ]

        self._tab_buttons.clear()

        for tab_name in tabs:
            is_active = (tab_name == self._current_tab_name)
            btn = tk.Button(
                tab_bar, text=f"  {tab_name}  ", font=(self.FONT_FAMILY, 8, "bold"),
                bg=self.SURFACE_ACTIVE if is_active else self.SURFACE_PANEL,
                fg=self.ACCENT_YELLOW if is_active else self.TEXT_SECONDARY,
                activebackground=self.SURFACE_ACTIVE, activeforeground=self.ACCENT_YELLOW,
                bd=0, padx=12, pady=5, cursor="hand2",
                command=lambda t=tab_name: self._select_tab(t)
            )
            btn.pack(side="left", fill="y", padx=(0, 2))
            self._tab_buttons[tab_name] = btn

    def _select_tab(self, tab_name: str):
        if tab_name not in self._tab_frames:
            return

        self._current_tab_name = tab_name

        # Update button states
        for name, btn in self._tab_buttons.items():
            is_active = (name == tab_name)
            btn.configure(
                bg=self.SURFACE_ACTIVE if is_active else self.SURFACE_PANEL,
                fg=self.ACCENT_YELLOW if is_active else self.TEXT_SECONDARY
            )

        # Show selected tab frame
        for name, frame in self._tab_frames.items():
            if name == tab_name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    # =========================================================================
    # 4. TAB CONTENT AREA
    # =========================================================================
    def _build_tab_content_area(self):
        self._tab_container = tk.Frame(self.root, bg=self.BG_ROOT)
        self._tab_container.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        # Build all 5 tabs
        self._build_tab_lighting()
        self._build_tab_equalizer()
        self._build_tab_zones()
        self._build_tab_profiles()
        self._build_tab_benchmark()

        # Show initial tab
        self._select_tab(self._current_tab_name)

    # -------------------------------------------------------------------------
    # TAB 1: LIGHTING & SYNC
    # -------------------------------------------------------------------------
    def _build_tab_lighting(self):
        tab = tk.Frame(self._tab_container, bg=self.BG_ROOT)
        self._tab_frames["LIGHTING & SYNC"] = tab

        # Left Column: Configuration & Sliders
        col_left = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        tk.Label(
            col_left, text="ANIMATION & LIGHTING PARAMETERS",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        form = tk.Frame(col_left, bg=self.SURFACE_PANEL)
        form.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # Effect Combobox
        eff_hdr = tk.Frame(form, bg=self.SURFACE_PANEL)
        eff_hdr.pack(fill="x")
        tk.Label(eff_hdr, text="LIGHTING ANIMATION EFFECT", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(side="left")

        btn_static = tk.Button(
            eff_hdr, text="STATIC ALBUM ART", font=(self.FONT_FAMILY, 6, "bold"),
            bg="#161616", fg=self.ACCENT_YELLOW, bd=0, padx=6, pady=1, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: [self._select_mode("Static Album Art"), self._handle_theme_change_direct("Auto (Album Cover)")]
        )
        btn_static.pack(side="right")

        modes = list(ANIMATION_REGISTRY.keys())
        self._combo_mode = ttk.Combobox(
            form, values=modes, state="readonly", style="Dark.TCombobox", font=(self.FONT_FAMILY, 8)
        )
        self._combo_mode.set(self._current_mode if self._current_mode in modes else modes[0])
        self._combo_mode.pack(fill="x", pady=(1, 5))
        self._combo_mode.bind("<<ComboboxSelected>>", self._handle_mode_select)

        # Theme Combobox
        tk.Label(form, text="COLOR PROFILE THEME", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")
        themes = list(ColorPaletteExtractor.PRESET_THEMES.keys())
        self._combo_theme = ttk.Combobox(
            form, values=themes, state="readonly", style="Dark.TCombobox", font=(self.FONT_FAMILY, 8)
        )
        self._combo_theme.set(self._current_theme if self._current_theme in themes else themes[0])
        self._combo_theme.pack(fill="x", pady=(1, 6))
        self._combo_theme.bind("<<ComboboxSelected>>", self._handle_theme_select)

        # Sliders: Brightness, Speed, Flash
        # 1. Brightness
        s1 = tk.Frame(form, bg=self.SURFACE_PANEL)
        s1.pack(fill="x", pady=2)
        h1 = tk.Frame(s1, bg=self.SURFACE_PANEL)
        h1.pack(fill="x")
        tk.Label(h1, text="HARDWARE BRIGHTNESS", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
        self._lbl_val_bright = tk.Label(h1, text=f"{self._current_brightness}%", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
        self._lbl_val_bright.pack(side="right")
        self._slider_bright = tk.Scale(
            s1, from_=0, to=100, resolution=5, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_bright_change
        )
        self._slider_bright.set(self._current_brightness)
        self._slider_bright.pack(fill="x")
        tk.Label(s1, text="Overall physical LED power output (0% off, 100% full)", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # 2. Animation Speed
        s2 = tk.Frame(form, bg=self.SURFACE_PANEL)
        s2.pack(fill="x", pady=2)
        h2 = tk.Frame(s2, bg=self.SURFACE_PANEL)
        h2.pack(fill="x")
        tk.Label(h2, text="ANIMATION SPEED", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
        self._lbl_val_spd = tk.Label(h2, text=f"{self._current_speed:.2f}x", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
        self._lbl_val_spd.pack(side="right")
        self._slider_spd = tk.Scale(
            s2, from_=0.5, to=2.5, resolution=0.1, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_speed_change
        )
        self._slider_spd.set(self._current_speed)
        self._slider_spd.pack(fill="x")
        tk.Label(s2, text="Motion velocity multiplier for waves, sweeps, and ripples", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # 3. Flash / Peak Overdrive
        s3 = tk.Frame(form, bg=self.SURFACE_PANEL)
        s3.pack(fill="x", pady=2)
        h3 = tk.Frame(s3, bg=self.SURFACE_PANEL)
        h3.pack(fill="x")
        tk.Label(h3, text="FLASH / PEAK OVERDRIVE", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
        self._lbl_val_flash = tk.Label(h3, text=f"{int(self._current_flash * 100)}%", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
        self._lbl_val_flash.pack(side="right")
        self._slider_flash = tk.Scale(
            s3, from_=0, to=100, resolution=5, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_flash_change
        )
        self._slider_flash.set(int(self._current_flash * 100))
        self._slider_flash.pack(fill="x")
        tk.Label(s3, text="0% = Pure color flow, 100% = White kick transients", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # Right Column: Now Playing & 4-Band Studio Spectrum
        col_right = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        tk.Label(
            col_right, text="NOW PLAYING & AUDIO SPECTRUM",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        np_card = tk.Frame(col_right, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        np_card.pack(fill="x", padx=14, pady=(0, 6))

        np_row = tk.Frame(np_card, bg=self.SURFACE_CARD)
        np_row.pack(fill="x", padx=10, pady=6)

        # 56x56 Album Art Frame
        art_box = tk.Frame(np_row, bg="#000000", width=56, height=56, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        art_box.pack(side="left")
        art_box.pack_propagate(False)

        self._lbl_cover = tk.Label(art_box, bg="#080808", text="♫\nNO ART", font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED)
        self._lbl_cover.pack(fill="both", expand=True)

        meta = tk.Frame(np_row, bg=self.SURFACE_CARD)
        meta.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._lbl_title = tk.Label(
            meta, text="No Media Playing", font=(self.FONT_FAMILY, 9, "bold"),
            fg=self.TEXT_WHITE, bg=self.SURFACE_CARD, anchor="w", justify="left"
        )
        self._lbl_title.pack(fill="x")

        self._lbl_artist = tk.Label(
            meta, text="Waiting for Windows SMTC session...", font=(self.FONT_FAMILY, 7),
            fg=self.TEXT_MUTED, bg=self.SURFACE_CARD, anchor="w", justify="left"
        )
        self._lbl_artist.pack(fill="x", pady=(1, 2))

        self._lbl_bpm = tk.Label(
            meta, text="• BPM: -- (Idle)", font=(self.FONT_FAMILY, 7, "bold"),
            fg=self.ACCENT_YELLOW, bg=self.SURFACE_CARD, anchor="w"
        )
        self._lbl_bpm.pack(anchor="w")

        # 4-Band Studio Graphic Equalizer Card
        eq_card = tk.Frame(col_right, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        eq_card.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tk.Label(
            eq_card, text="4-BAND STUDIO FREQUENCY SPECTRUM",
            font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD
        ).pack(anchor="w", padx=10, pady=(6, 2))

        self._canvas_eq = tk.Canvas(eq_card, height=115, bg=self.SURFACE_CARD, bd=0, highlightthickness=0)
        self._canvas_eq.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._canvas_eq.bind("<Configure>", self._redraw_eq_canvas)

        self._eq_bars = []
        self._eq_peaks = []
        self._eq_x_coords = [0, 0, 0, 0]

    def _redraw_eq_canvas(self, event=None):
        """Dynamically centers and draws the 4-band equalizer based on actual canvas width."""
        if not self._canvas_eq:
            return
        w = self._canvas_eq.winfo_width()
        h = self._canvas_eq.winfo_height()
        if w < 100 or h < 50:
            return

        self._canvas_eq.delete("all")
        self._eq_bars = []
        self._eq_peaks = []
        self._eq_x_coords = []

        band_labels = ["SUB-BASS (WASD)", "LOW-MID (M-L)", "HIGH-MID (M-R)", "TREBLE (NUM)"]
        col_w = min(90.0, (w - 30) / 4.0)
        spacing = (w - (col_w * 4.0)) / 5.0

        for i in range(4):
            x_base = spacing + (i * (col_w + spacing))
            self._eq_x_coords.append(x_base)
            seg_ids = []
            for s in range(12):
                y2 = h - 22 - (s * 7)
                y1 = y2 - 5
                rect = self._canvas_eq.create_rectangle(x_base, y1, x_base + col_w, y2, fill="#181818", outline="")
                seg_ids.append(rect)
            self._eq_bars.append(seg_ids)

            peak = self._canvas_eq.create_line(x_base, h - 22, x_base + col_w, h - 22, fill=self.TEXT_WHITE, width=1)
            self._eq_peaks.append(peak)

            self._canvas_eq.create_text(
                x_base + (col_w / 2.0), h - 10, text=band_labels[i],
                font=(self.FONT_FAMILY, 6, "bold"), fill=self.TEXT_MUTED
            )

    # -------------------------------------------------------------------------
    # TAB 2: AUDIO EQUALIZER & TUNING
    # -------------------------------------------------------------------------
    def _build_tab_equalizer(self):
        tab = tk.Frame(self._tab_container, bg=self.BG_ROOT)
        self._tab_frames["AUDIO EQUALIZER"] = tab

        # Left Column: Input Source & Master VU
        col_left = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        tk.Label(
            col_left, text="AUDIO INPUT & MASTER SIGNAL",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        box1 = tk.Frame(col_left, bg=self.SURFACE_PANEL)
        box1.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tk.Label(box1, text="AUDIO INPUT DEVICE (LOOPBACK)", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")
        dev_labels = []
        default_label = "Auto (Default Input)"
        if self.audio_devices:
            for idx, dname in self.audio_devices:
                lbl = f"[{idx}] {dname}"
                dev_labels.append(lbl)
                if self.selected_device_index is not None and idx == self.selected_device_index:
                    default_label = lbl
        else:
            dev_labels = ["Auto (Default Input)"]

        self._combo_device = ttk.Combobox(
            box1, values=dev_labels, state="readonly", style="Dark.TCombobox", font=(self.FONT_FAMILY, 8)
        )
        self._combo_device.set(default_label)
        self._combo_device.pack(fill="x", pady=(1, 8))
        self._combo_device.bind("<<ComboboxSelected>>", self._handle_device_select)

        # Master VU Meter Card
        vu_card = tk.Frame(box1, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        vu_card.pack(fill="x", pady=(0, 8))

        vu_hdr = tk.Frame(vu_card, bg=self.SURFACE_CARD)
        vu_hdr.pack(fill="x", padx=10, pady=(5, 2))

        tk.Label(vu_hdr, text="MASTER SIGNAL LEVEL", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(side="left")
        self._lbl_vu_status = tk.Label(vu_hdr, text="SILENT / GATED", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD)
        self._lbl_vu_status.pack(side="right")

        self._canvas_vu = tk.Canvas(vu_card, height=14, bg=self.SURFACE_CARD, bd=0, highlightthickness=0)
        self._canvas_vu.pack(fill="x", padx=10, pady=(2, 6))
        self._canvas_vu.bind("<Configure>", self._redraw_vu_canvas)

        self._vu_segs = []
        self._vu_peak_line = None

        # Beat Sensitivity Slider
        sens_f = tk.Frame(box1, bg=self.SURFACE_PANEL)
        sens_f.pack(fill="x", pady=2)
        sh = tk.Frame(sens_f, bg=self.SURFACE_PANEL)
        sh.pack(fill="x")
        tk.Label(sh, text="BEAT DETECTION SENSITIVITY", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
        self._lbl_val_sens = tk.Label(sh, text=f"{self._current_sensitivity:.2f}x", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
        self._lbl_val_sens.pack(side="right")
        self._slider_sens = tk.Scale(
            sens_f, from_=0.5, to=2.5, resolution=0.05, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_sens_change
        )
        self._slider_sens.set(self._current_sensitivity)
        self._slider_sens.pack(fill="x")
        tk.Label(sens_f, text="Threshold multiplier for drum beat pulses", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # Noise Gate / Silence Threshold Slider
        noise_f = tk.Frame(box1, bg=self.SURFACE_PANEL)
        noise_f.pack(fill="x", pady=2)
        nh = tk.Frame(noise_f, bg=self.SURFACE_PANEL)
        nh.pack(fill="x")
        tk.Label(nh, text="SILENCE NOISE GATE THRESHOLD", font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
        self._lbl_val_noise = tk.Label(nh, text=f"{self._silence_threshold:.4f}", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
        self._lbl_val_noise.pack(side="right")
        self._slider_noise = tk.Scale(
            noise_f, from_=0.0005, to=0.015, resolution=0.0005, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_noise_change
        )
        self._slider_noise.set(self._silence_threshold)
        self._slider_noise.pack(fill="x")
        tk.Label(noise_f, text="Signals below this RMS drop keyboard to zero/stealth", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # Right Column: 4 Individual Band Gain Sliders
        col_right = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        tk.Label(
            col_right, text="INDIVIDUAL FREQUENCY BAND GAIN BOOST",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        box2 = tk.Frame(col_right, bg=self.SURFACE_PANEL)
        box2.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        band_names = [
            ("SUB-BASS GAIN (20-120Hz)", "WASD Kick Impact & Sub-Bass Power"),
            ("LOW-MID GAIN (120-500Hz)", "Bassline Resonance & Snare Drum Attack"),
            ("HIGH-MID GAIN (500-3.5kHz)", "Vocal Clarity, Melodic Lead & Guitar"),
            ("TREBLE GAIN (3.5-16kHz)", "Hi-Hats, Cymbals & Sparkling Shimmer")
        ]

        self._gain_sliders = []
        self._gain_val_labels = []

        for b_idx in range(4):
            bf = tk.Frame(box2, bg=self.SURFACE_PANEL)
            bf.pack(fill="x", pady=2)
            bh = tk.Frame(bf, bg=self.SURFACE_PANEL)
            bh.pack(fill="x")

            tk.Label(bh, text=band_names[b_idx][0], font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL).pack(side="left")
            val_lbl = tk.Label(bh, text=f"{self._band_gains[b_idx]:.2f}x", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL)
            val_lbl.pack(side="right")
            self._gain_val_labels.append(val_lbl)

            sl = tk.Scale(
                bf, from_=0.0, to=3.0, resolution=0.1, orient="horizontal",
                bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
                activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
                sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
                command=lambda val, idx=b_idx: self._handle_band_gain_change(idx, val)
            )
            sl.set(self._band_gains[b_idx])
            sl.pack(fill="x")
            self._gain_sliders.append(sl)

            tk.Label(bf, text=band_names[b_idx][1], font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

        # Quick EQ Presets Bar
        eq_btns = tk.Frame(box2, bg=self.SURFACE_PANEL)
        eq_btns.pack(fill="x", pady=(8, 0))

        tk.Button(
            eq_btns, text="FLAT (1.0x)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, bd=0, padx=8, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: self._apply_eq_preset([1.0, 1.0, 1.0, 1.0])
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            eq_btns, text="BASS PUNCH (2.2x)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, bd=0, padx=8, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: self._apply_eq_preset([2.2, 1.2, 0.8, 0.8])
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            eq_btns, text="VOCAL FOCUS", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, bd=0, padx=8, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: self._apply_eq_preset([0.8, 1.0, 2.2, 1.1])
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            eq_btns, text="TREBLE SHIMMER", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, bd=0, padx=8, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=lambda: self._apply_eq_preset([0.8, 0.9, 1.2, 2.4])
        ).pack(side="left")

    def _redraw_vu_canvas(self, event=None):
        """Dynamically computes VU segment widths to fill the canvas edge-to-edge."""
        if not self._canvas_vu:
            return
        w = self._canvas_vu.winfo_width()
        if w < 50:
            return

        self._canvas_vu.delete("all")
        self._vu_segs = []
        num_segs = 24
        gap = 2
        seg_w = max(4.0, (w - (num_segs * gap)) / num_segs)

        for s in range(num_segs):
            x1 = s * (seg_w + gap)
            x2 = x1 + seg_w
            rect = self._canvas_vu.create_rectangle(x1, 1, x2, 13, fill="#181818", outline="")
            self._vu_segs.append(rect)

        self._vu_peak_line = self._canvas_vu.create_line(0, 1, 0, 13, fill=self.TEXT_WHITE, width=2)

    def _handle_band_gain_change(self, idx: int, val):
        v = float(val)
        self._band_gains[idx] = v
        if idx < len(self._gain_val_labels):
            self._gain_val_labels[idx].config(text=f"{v:.2f}x")
        if self.on_band_gain_change:
            self.on_band_gain_change(tuple(self._band_gains))

    def _apply_eq_preset(self, gains: List[float]):
        for i in range(4):
            self._band_gains[i] = gains[i]
            if i < len(self._gain_sliders):
                self._gain_sliders[i].set(gains[i])
            if i < len(self._gain_val_labels):
                self._gain_val_labels[i].config(text=f"{gains[i]:.2f}x")
        if self.on_band_gain_change:
            self.on_band_gain_change(tuple(self._band_gains))

    def _handle_noise_change(self, val):
        n = float(val)
        self._silence_threshold = n
        if self._lbl_val_noise:
            self._lbl_val_noise.config(text=f"{n:.4f}")
        if self.on_silence_threshold_change:
            self.on_silence_threshold_change(n)

    # -------------------------------------------------------------------------
    # TAB 3: ZONE CUSTOMIZATION (Static Overrides & Lock Toggles)
    # -------------------------------------------------------------------------
    def _build_tab_zones(self):
        tab = tk.Frame(self._tab_container, bg=self.BG_ROOT)
        self._tab_frames["ZONE CUSTOMIZATION"] = tab

        panel = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        panel.pack(fill="both", expand=True)

        hdr = tk.Frame(panel, bg=self.SURFACE_PANEL)
        hdr.pack(fill="x", padx=16, pady=(8, 4))

        tk.Label(
            hdr, text="PER-ZONE STATIC COLOR OVERRIDE & LOCK CONTROLS",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(side="left")

        tk.Label(
            hdr, text="Lock any zone (e.g. WASD) to a static color while others react to music",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        ).pack(side="right")

        # 4 Zone control cards grid
        zones_grid = tk.Frame(panel, bg=self.SURFACE_PANEL)
        zones_grid.pack(fill="both", expand=True, padx=16, pady=(0, 6))

        zone_names = [
            ("ZONE 1 (WASD / BASS)", "Controls Left / WASD keycap cluster"),
            ("ZONE 2 (MID-LEFT / VOCALS)", "Controls Center-Left key cluster"),
            ("ZONE 3 (MID-RIGHT / MELODY)", "Controls Center-Right & Arrow cluster"),
            ("ZONE 4 (NUMPAD / TREBLE)", "Controls 10-key Numpad cluster")
        ]

        preset_colors = [
            ("RED", (255, 0, 0)),
            ("CYAN", (0, 240, 255)),
            ("YELLOW", (255, 209, 0)),
            ("WHITE", (255, 255, 255)),
            ("PURPLE", (170, 0, 255)),
            ("GREEN", (0, 255, 80)),
            ("ORANGE", (255, 120, 0)),
            ("BLUE", (0, 100, 255)),
        ]

        self._zone_toggle_btns = []
        self._zone_color_indicators = []

        for z in range(4):
            card = tk.Frame(zones_grid, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
            card.pack(fill="x", pady=2)

            chdr = tk.Frame(card, bg=self.SURFACE_CARD)
            chdr.pack(fill="x", padx=10, pady=(5, 3))

            # Swatch box
            ind_c = tk.Canvas(chdr, width=12, height=12, bg=self.SURFACE_CARD, bd=0, highlightthickness=0)
            ind_c.pack(side="left", padx=(0, 6))
            rect_id = ind_c.create_rectangle(0, 0, 12, 12, fill="#333333", outline="")
            self._zone_color_indicators.append((ind_c, rect_id))

            tk.Label(chdr, text=zone_names[z][0], font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(side="left")
            tk.Label(chdr, text=f"• {zone_names[z][1]}", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(side="left", padx=8)

            t_btn = tk.Button(
                chdr, text="DYNAMIC (MUSIC SYNC)", font=(self.FONT_FAMILY, 7, "bold"),
                bg="#1A1A1A", fg=self.ACCENT_YELLOW, bd=0, padx=8, pady=2, cursor="hand2",
                highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
                command=lambda z_idx=z: self._toggle_zone_lock(z_idx)
            )
            t_btn.pack(side="right")
            self._zone_toggle_btns.append(t_btn)

            # Palette buttons row
            swatch_row = tk.Frame(card, bg=self.SURFACE_CARD)
            swatch_row.pack(fill="x", padx=10, pady=(0, 5))

            tk.Label(swatch_row, text="Lock to Color:", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(side="left", padx=(0, 6))

            for cname, rgb in preset_colors:
                hex_c = _rgb_to_hex(rgb)
                btn_swatch = tk.Button(
                    swatch_row, text=f" {cname} ", font=(self.FONT_FAMILY, 6, "bold"),
                    bg="#161616", fg=hex_c, bd=0, padx=4, pady=1, cursor="hand2",
                    highlightthickness=1, highlightbackground=hex_c,
                    command=lambda z_idx=z, c=rgb: self._set_zone_lock_color(z_idx, c)
                )
                btn_swatch.pack(side="left", padx=2)

        # Quick Gaming Profiles at bottom of Tab 3
        qf = tk.Frame(panel, bg=self.SURFACE_PANEL)
        qf.pack(fill="x", padx=16, pady=(4, 8))

        tk.Button(
            qf, text="GAMING: LOCK WASD TO RED", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg="#FF3333", bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground="#FF3333",
            command=lambda: self._set_zone_lock_color(0, (255, 0, 0))
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            qf, text="GAMING: LOCK WASD TO CYAN", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg="#00F2C3", bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground="#00F2C3",
            command=lambda: self._set_zone_lock_color(0, (0, 240, 255))
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            qf, text="UNLOCK ALL (100% MUSIC SYNC)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.ACCENT_YELLOW, bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._unlock_all_zones
        ).pack(side="left")

    def _toggle_zone_lock(self, zone_idx: int):
        if self._zone_overrides[zone_idx] is not None:
            self._set_zone_lock_color(zone_idx, None)
        else:
            self._set_zone_lock_color(zone_idx, (255, 0, 0))

    def _set_zone_lock_color(self, zone_idx: int, color: Optional[RGBColor]):
        self._zone_overrides[zone_idx] = color
        btn = self._zone_toggle_btns[zone_idx]
        ind_c, rect_id = self._zone_color_indicators[zone_idx]
        badge = self._kb_lock_badges[zone_idx]

        if color is not None:
            hex_c = _rgb_to_hex(color)
            btn.config(text=f"LOCKED: {hex_c.upper()}", fg="#FFFFFF", bg="#331A00")
            ind_c.itemconfig(rect_id, fill=hex_c)
            badge.config(text=f"[{hex_c.upper()}]", fg="#FFFFFF")
        else:
            btn.config(text="DYNAMIC (MUSIC SYNC)", fg=self.ACCENT_YELLOW, bg="#1A1A1A")
            ind_c.itemconfig(rect_id, fill="#333333")
            badge.config(text="[DYNAMIC]", fg=self.ACCENT_YELLOW)

        if self.on_zone_override_change:
            self.on_zone_override_change(zone_idx, color)

    def _unlock_all_zones(self):
        for z in range(4):
            self._set_zone_lock_color(z, None)

    # -------------------------------------------------------------------------
    # TAB 4: PROFILES & PRESETS
    # -------------------------------------------------------------------------
    def _build_tab_profiles(self):
        tab = tk.Frame(self._tab_container, bg=self.BG_ROOT)
        self._tab_frames["PROFILES & PRESETS"] = tab

        # Left Column: 5 Instant Hardware Presets
        col_left = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        tk.Label(
            col_left, text="QUICK ONE-CLICK PRESET PROFILES",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        presets_box = tk.Frame(col_left, bg=self.SURFACE_PANEL)
        presets_box.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        presets = [
            ("Static Album Cover", "Static 4-Zone illumination from album cover artwork • Zero animation"),
            ("Bass Heavy EDM", "Dynamic Studio EQ • Sub-Bass 2.0x • Predator Cyan • 35% Flash"),
            ("Chill Lo-Fi / Ambient", "Lush Chroma Aurora • Speed 0.8x • Flash 0% • Synthwave Sunset"),
            ("Competitive Gaming WASD", "Bass WASD & Melodic • WASD Static Red • Sens 1.3x"),
            ("Cyberpunk Synthwave", "Neon Cyber Wave • Speed 1.2x • Cyberpunk Neon Profile"),
            ("Vocal & Acoustic", "Euphoria Breath • High-Mid Boost 1.6x • Electric Amber"),
        ]

        for pname, pdesc in presets:
            pf = tk.Frame(presets_box, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
            pf.pack(fill="x", pady=2)

            p_in = tk.Frame(pf, bg=self.SURFACE_CARD)
            p_in.pack(fill="x", padx=10, pady=5)

            left = tk.Frame(p_in, bg=self.SURFACE_CARD)
            left.pack(side="left")
            tk.Label(left, text=pname, font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(anchor="w")
            tk.Label(left, text=pdesc, font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")

            btn_load = tk.Button(
                p_in, text="LOAD PRESET", font=(self.FONT_FAMILY, 7, "bold"),
                bg="#1A1A1A", fg=self.ACCENT_YELLOW, bd=0, padx=8, pady=3, cursor="hand2",
                highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
                command=lambda name=pname: self._load_builtin_preset(name)
            )
            btn_load.pack(side="right")

        # Right Column: Custom Profile JSON Management
        col_right = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        col_right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        tk.Label(
            col_right, text="CUSTOM PROFILE BACKUP & RESTORE",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(8, 4))

        mgt_box = tk.Frame(col_right, bg=self.SURFACE_PANEL)
        mgt_box.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tk.Label(mgt_box, text="PROFILE NAME:", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")
        self._entry_profile_name = tk.Entry(
            mgt_box, bg=self.SURFACE_INPUT, fg=self.TEXT_WHITE, insertbackground=self.ACCENT_YELLOW,
            bd=0, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE, font=(self.FONT_FAMILY, 9)
        )
        self._entry_profile_name.insert(0, "My Predator Profile")
        self._entry_profile_name.pack(fill="x", pady=(2, 8))

        btn_row = tk.Frame(mgt_box, bg=self.SURFACE_PANEL)
        btn_row.pack(fill="x", pady=(0, 8))

        tk.Button(
            btn_row, text="SAVE PROFILE (JSON)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.ACCENT_YELLOW, bd=0, padx=10, pady=4, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._handle_save_profile
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row, text="LOAD PROFILE (JSON)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.TEXT_WHITE, bd=0, padx=10, pady=4, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._handle_load_profile
        ).pack(side="left")

        self._lbl_profile_status = tk.Label(
            mgt_box, text="Ready.", font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL, anchor="w"
        )
        self._lbl_profile_status.pack(fill="x", pady=(4, 6))

        # Windows System & Startup Integration Card
        tk.Label(
            col_right, text="WINDOWS STARTUP INTEGRATION",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(6, 4))

        boot_card = tk.Frame(col_right, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        boot_card.pack(fill="x", padx=14, pady=(0, 6))

        b_row = tk.Frame(boot_card, bg=self.SURFACE_CARD)
        b_row.pack(fill="x", padx=10, pady=8)

        b_left = tk.Frame(b_row, bg=self.SURFACE_CARD)
        b_left.pack(side="left")
        tk.Label(b_left, text="START ON WINDOWS BOOT", font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(anchor="w")
        tk.Label(b_left, text="Auto-launches silently to tray on Windows login", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")

        btn_bg = self.ACCENT_YELLOW if self._is_autostart_active else "#161616"
        btn_fg = "#000000" if self._is_autostart_active else self.TEXT_MUTED
        self._btn_autostart = tk.Button(
            b_row, text="ENABLED" if self._is_autostart_active else "DISABLED",
            font=(self.FONT_FAMILY, 7, "bold"),
            bg=btn_bg, fg=btn_fg,
            bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.ACCENT_YELLOW if self._is_autostart_active else self.BORDER_HAIRLINE,
            command=self._toggle_autostart_gui
        )
        self._btn_autostart.pack(side="right")

    def _load_builtin_preset(self, name: str):
        if name == "Static Album Cover":
            self._select_mode("Static Album Art")
            self._handle_theme_change_direct("Auto (Album Cover)")
            if self._slider_flash:
                self._slider_flash.set(0)
                self._handle_flash_change(0)
            self._apply_eq_preset([1.0, 1.0, 1.0, 1.0])
            self._unlock_all_zones()
        elif name == "Bass Heavy EDM":
            self._select_mode("Dynamic Studio EQ")
            self._handle_theme_change_direct("Predator Cyan")
            if self._slider_flash:
                self._slider_flash.set(35)
                self._handle_flash_change(35)
            self._apply_eq_preset([2.0, 1.2, 0.8, 0.8])
            self._unlock_all_zones()
        elif name == "Chill Lo-Fi / Ambient":
            self._select_mode("Lush Chroma Aurora")
            self._handle_theme_change_direct("Synthwave Sunset")
            if self._slider_spd:
                self._slider_spd.set(0.8)
                self._handle_speed_change(0.8)
            if self._slider_flash:
                self._slider_flash.set(0)
                self._handle_flash_change(0)
            self._apply_eq_preset([1.0, 1.0, 1.0, 1.0])
            self._unlock_all_zones()
        elif name == "Competitive Gaming WASD":
            self._select_mode("Bass WASD & Melodic")
            if self._slider_sens:
                self._slider_sens.set(1.3)
                self._handle_sens_change(1.3)
            self._set_zone_lock_color(0, (255, 0, 0))
        elif name == "Cyberpunk Synthwave":
            self._select_mode("Neon Cyber Wave")
            self._handle_theme_change_direct("Cyberpunk Neon")
            if self._slider_spd:
                self._slider_spd.set(1.2)
                self._handle_speed_change(1.2)
            self._unlock_all_zones()
        elif name == "Vocal & Acoustic":
            self._select_mode("Euphoria Breath")
            self._handle_theme_change_direct("Electric Amber")
            self._apply_eq_preset([0.8, 1.0, 1.8, 1.1])
            self._unlock_all_zones()

        if self.on_load_preset:
            self.on_load_preset(name)

        if self._lbl_profile_status:
            self._lbl_profile_status.config(text=f"Loaded preset: '{name}'", fg=self.ACCENT_YELLOW)

    def _handle_save_profile(self):
        fpath = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON Files", "*.json")],
            title="Save Predator Lighting Profile"
        )
        if fpath:
            name = self._entry_profile_name.get() if self._entry_profile_name else "Profile"
            data = {
                "name": name,
                "mode": self._current_mode,
                "theme": self._current_theme,
                "brightness": self._current_brightness,
                "sensitivity": self._current_sensitivity,
                "speed": self._current_speed,
                "flash": self._current_flash,
                "band_gains": self._band_gains,
                "silence_threshold": self._silence_threshold,
                "zone_overrides": {str(k): v for k, v in self._zone_overrides.items()}
            }
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                if self._lbl_profile_status:
                    self._lbl_profile_status.config(text=f"Profile saved: {os.path.basename(fpath)}", fg=self.ACCENT_YELLOW)
                if self.on_save_profile:
                    self.on_save_profile(name, fpath)
            except Exception as e:
                if self._lbl_profile_status:
                    self._lbl_profile_status.config(text=f"Error saving: {e}", fg="#FF4444")

    def _handle_load_profile(self):
        fpath = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json")], title="Load Predator Lighting Profile"
        )
        if fpath and os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "mode" in data:
                    self._select_mode(data["mode"])
                elif "animation_mode" in data:
                    self._select_mode(data["animation_mode"])
                if "theme" in data:
                    self._handle_theme_change_direct(data["theme"])
                elif "theme_name" in data:
                    self._handle_theme_change_direct(data["theme_name"])
                if "brightness" in data and self._slider_bright:
                    self._slider_bright.set(data["brightness"])
                    self._handle_bright_change(data["brightness"])
                if "sensitivity" in data and self._slider_sens:
                    self._slider_sens.set(data["sensitivity"])
                    self._handle_sens_change(data["sensitivity"])
                if "speed" in data and self._slider_spd:
                    self._slider_spd.set(data["speed"])
                    self._handle_speed_change(data["speed"])
                if "flash" in data and self._slider_flash:
                    self._slider_flash.set(int(data["flash"] * 100))
                    self._handle_flash_change(int(data["flash"] * 100))
                if "band_gains" in data:
                    self._apply_eq_preset(data["band_gains"])
                if "silence_threshold" in data and self._slider_noise:
                    self._slider_noise.set(data["silence_threshold"])
                    self._handle_noise_change(data["silence_threshold"])
                if "zone_overrides" in data:
                    for k, v in data["zone_overrides"].items():
                        c = tuple(v) if v else None
                        self._set_zone_lock_color(int(k), c)
                if self._lbl_profile_status:
                    self._lbl_profile_status.config(text=f"Loaded: {os.path.basename(fpath)}", fg=self.ACCENT_YELLOW)
                if self.on_load_profile:
                    self.on_load_profile(fpath)
            except Exception as e:
                if self._lbl_profile_status:
                    self._lbl_profile_status.config(text=f"Error loading: {e}", fg="#FF4444")

    def _handle_theme_change_direct(self, theme_name: str):
        self._current_theme = theme_name
        if self._combo_theme:
            self._combo_theme.set(theme_name)
        if self.on_theme_change:
            self.on_theme_change(theme_name)

    def _toggle_autostart_gui(self):
        new_val = not self._is_autostart_active
        set_autostart(new_val)
        self.set_autostart_state(new_val)
        if self.on_toggle_autostart:
            self.on_toggle_autostart(new_val)

    def set_autostart_state(self, enabled: bool):
        self._is_autostart_active = enabled
        if self._btn_autostart and self.root and self.root.winfo_exists():
            try:
                btn_bg = self.ACCENT_YELLOW if enabled else "#161616"
                btn_fg = "#000000" if enabled else self.TEXT_MUTED
                self._btn_autostart.config(
                    text="ENABLED" if enabled else "DISABLED",
                    bg=btn_bg, fg=btn_fg,
                    highlightbackground=self.ACCENT_YELLOW if enabled else self.BORDER_HAIRLINE
                )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # TAB 5: HARDWARE BENCHMARK (Embedded Live Console)
    # -------------------------------------------------------------------------
    def _build_tab_benchmark(self):
        tab = tk.Frame(self._tab_container, bg=self.BG_ROOT)
        self._tab_frames["HARDWARE BENCHMARK"] = tab

        panel = tk.Frame(tab, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        panel.pack(fill="both", expand=True)

        top_bar = tk.Frame(panel, bg=self.SURFACE_PANEL)
        top_bar.pack(fill="x", padx=14, pady=(8, 4))

        tk.Label(
            top_bar, text="PHYSICAL ACPI EC HARDWARE & AUDIO BENCHMARK SUITE",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL
        ).pack(side="left")

        btn_run = tk.Button(
            top_bar, text="RUN BENCHMARK (3 PASSES)", font=(self.FONT_FAMILY, 7, "bold"),
            bg="#161616", fg=self.ACCENT_YELLOW, bd=0, padx=12, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._start_embedded_benchmark
        )
        btn_run.pack(side="right")

        # Telemetry metrics cards row
        m_row = tk.Frame(panel, bg=self.SURFACE_PANEL)
        m_row.pack(fill="x", padx=14, pady=(0, 6))

        self._lbl_bench_bus = tk.Label(
            m_row, text="EC ACPI BUS ROUNDTRIP: ~250 ms", font=(self.FONT_MONO, 7, "bold"),
            fg=self.ACCENT_YELLOW, bg=self.SURFACE_CARD, padx=8, pady=2
        )
        self._lbl_bench_bus.pack(side="left", padx=(0, 6))

        self._lbl_bench_fps = tk.Label(
            m_row, text="NON-BLOCKING PIPELINE: >100,000 FPS (Pass 6)", font=(self.FONT_MONO, 7, "bold"),
            fg=self.TEXT_WHITE, bg=self.SURFACE_CARD, padx=8, pady=2
        )
        self._lbl_bench_fps.pack(side="left")

        # Output console
        self._txt_bench = scrolledtext.ScrolledText(
            panel, bg="#060606", fg="#D0D0D0", font=(self.FONT_MONO, 8),
            bd=0, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE
        )
        self._txt_bench.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self._txt_bench.insert(tk.END, "Ready to benchmark physical ACPI EC and audio pipeline. Click 'RUN BENCHMARK' above.\n")

    def _start_embedded_benchmark(self):
        if not self._txt_bench:
            return
        self._txt_bench.delete("1.0", tk.END)

        def log_cb(line: str):
            if self.root and self.root.winfo_exists() and self._txt_bench:
                self.root.after(0, lambda l=line: [self._txt_bench.insert(tk.END, l + "\n"), self._txt_bench.see(tk.END)])

        def _bench_worker():
            try:
                from ..benchmark.benchmark_suite import run_comprehensive_benchmark
                run_comprehensive_benchmark(passes=3, log_callback=log_cb)
            except Exception as e:
                import traceback
                log_cb("Benchmark error:\n" + traceback.format_exc())

        threading.Thread(target=_bench_worker, daemon=True).start()

    # =========================================================================
    # 5. BOTTOM STATUS BAR
    # =========================================================================
    def _build_bottom_status_bar(self):
        bar = tk.Frame(self.root, bg=self.SURFACE_PANEL, height=24, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=self.SURFACE_PANEL)
        left.pack(side="left", padx=14, fill="y")

        tk.Label(
            left, text="HARDWARE: ACER PREDATOR HELIOS NEO 16 (PHN16-71)",
            font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        ).pack(side="left")

        tk.Label(
            left, text="• WASAPI LOOPBACK (48 kHz) • 60 FPS NON-BLOCKING",
            font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        ).pack(side="left", padx=6)

        right = tk.Frame(bar, bg=self.SURFACE_PANEL)
        right.pack(side="right", padx=14, fill="y")

        self._lbl_status_track = tk.Label(
            right, text="SESSION: READY",
            font=(self.FONT_FAMILY, 6, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_PANEL
        )
        self._lbl_status_track.pack(side="left")

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================
    def _select_mode(self, mode_name: str):
        if mode_name not in ANIMATION_REGISTRY:
            return
        self._current_mode = mode_name
        if self._combo_mode and self._combo_mode.get() != mode_name:
            self._combo_mode.set(mode_name)
        if self.on_mode_change:
            self.on_mode_change(mode_name)

    def _handle_mode_select(self, event=None):
        if self._combo_mode:
            self._select_mode(self._combo_mode.get())

    def _handle_device_select(self, event=None):
        if not self._combo_device:
            return
        val = self._combo_device.get()
        if val.startswith("[") and "]" in val:
            try:
                idx = int(val[1:val.index("]")])
                self.selected_device_index = idx
                if self.on_audio_device_change:
                    self.on_audio_device_change(idx)
            except Exception:
                pass

    def _handle_theme_select(self, event=None):
        if self._combo_theme:
            self._handle_theme_change_direct(self._combo_theme.get())

    def _handle_bright_change(self, val):
        b = int(float(val))
        self._current_brightness = b
        if self._lbl_val_bright:
            self._lbl_val_bright.config(text=f"{b}%")
        if self.on_brightness_change:
            self.on_brightness_change(b)

    def _handle_sens_change(self, val):
        s = float(val)
        self._current_sensitivity = s
        if self._lbl_val_sens:
            self._lbl_val_sens.config(text=f"{s:.2f}x")
        if self.on_sensitivity_change:
            self.on_sensitivity_change(s)

    def _handle_speed_change(self, val):
        spd = float(val)
        self._current_speed = spd
        if self._lbl_val_spd:
            self._lbl_val_spd.config(text=f"{spd:.2f}x")
        if self.on_speed_change:
            self.on_speed_change(spd)

    def _handle_flash_change(self, val):
        pct = int(float(val))
        self._current_flash = pct / 100.0
        if self._lbl_val_flash:
            self._lbl_val_flash.config(text=f"{pct}%")
        if self.on_flash_change:
            self.on_flash_change(self._current_flash)

    def _toggle_lighting_state(self):
        self._is_lighting_active = not self._is_lighting_active
        if self._btn_toggle:
            if self._is_lighting_active:
                self._btn_toggle.config(text="LIGHTING: ACTIVE", fg=self.ACCENT_YELLOW, bg="#161616")
            else:
                self._btn_toggle.config(text="LIGHTING: PAUSED", fg=self.ACCENT_WARN, bg="#2A1B00")
        if self.on_toggle_lighting:
            self.on_toggle_lighting(self._is_lighting_active)

    def set_mode(self, mode_name: str, notify: bool = False):
        """Thread-safe synchronization of active mode from tray or service."""
        if mode_name not in ANIMATION_REGISTRY:
            return
        self._current_mode = mode_name
        if self._combo_mode and self.root and self.root.winfo_exists():
            try:
                self._combo_mode.set(mode_name)
            except Exception:
                pass
        if notify and self.on_mode_change:
            self.on_mode_change(mode_name)

    def set_lighting_active(self, active: bool, notify: bool = False):
        """Thread-safe synchronization of lighting state from tray or service."""
        self._is_lighting_active = active
        if self._btn_toggle and self.root and self.root.winfo_exists():
            try:
                if active:
                    self._btn_toggle.config(text="LIGHTING: ACTIVE", fg=self.ACCENT_YELLOW, bg="#161616")
                else:
                    self._btn_toggle.config(text="LIGHTING: PAUSED", fg=self.ACCENT_WARN, bg="#2A1B00")
            except Exception:
                pass
        if notify and self.on_toggle_lighting:
            self.on_toggle_lighting(active)

    # =========================================================================
    # REAL-TIME 60 FPS RENDER LOOP & GUI TICK
    # =========================================================================
    def update_zone_colors(self, colors: List[RGBColor]):
        with self._lock:
            self._pending_colors = list(colors)

    def update_track_info(self, track: MediaTrackInfo):
        with self._lock:
            self._pending_track = track

    def update_audio_state(self, state: AudioBeatState):
        with self._lock:
            self._pending_state = state

    def _schedule_gui_update(self):
        if self._is_gui_active and self.root and self.root.winfo_exists() and self.root.state() != "withdrawn":
            try:
                self._render_gui_frame()
                self._after_id = self.root.after(33, self._schedule_gui_update)
            except Exception:
                pass
        else:
            self._after_id = None

    def _render_gui_frame(self):
        with self._lock:
            colors = self._pending_colors
            track = self._pending_track
            state = self._pending_state
            self._pending_track = None

        # 1. Update Media Track Info
        if track:
            t_title = track.title or "Unknown Title"
            t_artist = track.artist or "Unknown Artist"
            if len(t_title) > 38:
                t_title = t_title[:35] + "..."
            if len(t_artist) > 38:
                t_artist = t_artist[:35] + "..."

            if self._lbl_title:
                self._lbl_title.config(text=t_title)
            if self._lbl_artist:
                self._lbl_artist.config(text=t_artist)
            if self._lbl_header_track:
                self._lbl_header_track.config(text=f"♫ {t_title} — {t_artist}")
            if self._lbl_status_track:
                self._lbl_status_track.config(text=f"PLAYING: {t_title.upper()}")

            if self._lbl_cover:
                if track.cover_path and os.path.exists(track.cover_path):
                    try:
                        img = Image.open(track.cover_path).resize((56, 56), Image.Resampling.LANCZOS)
                        self._cover_img_tk = ImageTk.PhotoImage(img)
                        self._lbl_cover.config(image=self._cover_img_tk, text="")
                    except Exception:
                        self._lbl_cover.config(image="", text="♫")
                else:
                    self._lbl_cover.config(image="", text="♫")

        # 2. Update Full Realistic Keyboard Graphic & Live Keycap Illumination
        if colors and len(colors) == 4 and self._canvas_kb:
            # Check if colors actually changed before costly Tkinter itemconfig calls
            colors_changed = any(c != l for c, l in zip(colors, self._last_rendered_colors))
            if colors_changed:
                self._last_rendered_colors = list(colors)

                for z in range(4):
                    r, g, b = colors[z]
                    hex_c = f"#{r:02x}{g:02x}{b:02x}"

                    if z < len(self._kb_hex_labels):
                        self._kb_hex_labels[z].config(text=hex_c.upper())

                    # Update zone status LED dot canvas safely
                    if z < len(self._kb_dots):
                        dot_c, dot_id = self._kb_dots[z]
                        dot_c.itemconfig(dot_id, fill=hex_c)

                    # Soft underglow backdrop per zone
                    if z < len(self._kb_zone_backs):
                        dim_hex = _dim_color(colors[z], 0.16)
                        self._canvas_kb.itemconfig(self._kb_zone_backs[z], fill=dim_hex)

                # Recolor individual keycaps
                is_silent = all(sum(c) < 15 for c in colors)
                for idx in range(len(self._kb_key_rects)):
                    k_rect = self._kb_key_rects[idx]
                    z = self._kb_key_zones[idx]
                    is_wasd = k_rect in self._kb_key_wasd
                    is_arr = k_rect in self._kb_key_arrows

                    if is_silent:
                        k_fill = "#141414" if (is_wasd or is_arr) else "#0F0F0F"
                        k_out = "#FFFFFF" if (is_wasd or is_arr) else self.BORDER_HAIRLINE
                    else:
                        factor = 0.65 if (is_wasd or is_arr) else 0.30
                        k_fill = _dim_color(colors[z], factor)
                        k_out = "#FFFFFF" if (is_wasd or is_arr) else (
                            f"#{colors[z][0]:02x}{colors[z][1]:02x}{colors[z][2]:02x}" if sum(colors[z]) > 25 else self.BORDER_HAIRLINE
                        )
                    self._canvas_kb.itemconfig(k_rect, fill=k_fill, outline=k_out)

        # 3. Update Audio Beat State, Spectrum Equalizer & Master VU Meter
        if state:
            if self._lbl_bpm:
                self._lbl_bpm.config(text=f"• BPM: {state.bpm_estimate:.0f}")

            # Master VU Meter (Tab 2)
            if self._canvas_vu and self._lbl_vu_status and self._vu_segs:
                energy = float(state.overall_energy)
                if energy < 0.05:
                    self._lbl_vu_status.config(text="SILENT / GATED", fg=self.TEXT_MUTED)
                else:
                    self._lbl_vu_status.config(text=f"ACTIVE ({int(energy * 100)}%)", fg=self.ACCENT_YELLOW)

                active_count = int(min(1.0, energy) * len(self._vu_segs))
                for s in range(len(self._vu_segs)):
                    seg_id = self._vu_segs[s]
                    if s < active_count:
                        c = self.ACCENT_YELLOW if s < 18 else "#FF3333"
                        self._canvas_vu.itemconfig(seg_id, fill=c)
                    else:
                        self._canvas_vu.itemconfig(seg_id, fill="#181818")

                if energy > self._vu_peak_level:
                    self._vu_peak_level = energy
                else:
                    self._vu_peak_level = max(0.0, self._vu_peak_level - 0.03)

                if self._vu_peak_line:
                    w = self._canvas_vu.winfo_width()
                    if w > 50:
                        peak_x = int(min(1.0, self._vu_peak_level) * (w - 4)) + 2
                        self._canvas_vu.coords(self._vu_peak_line, peak_x, 1, peak_x, 13)

            # 4-Band Vertical Equalizer (Tab 1)
            if self._canvas_eq and len(state.smoothed_bands) >= 4 and len(self._eq_bars) == 4:
                h = self._canvas_eq.winfo_height()
                base_y = h - 22 if h > 50 else 95
                col_w = min(90.0, (self._canvas_eq.winfo_width() - 30) / 4.0)

                for i in range(4):
                    band_val = float(state.smoothed_bands[i])
                    active_segs = int(min(1.0, band_val * 1.3) * 12)
                    for s in range(12):
                        seg_id = self._eq_bars[i][s]
                        if s < active_segs:
                            c = self.ACCENT_YELLOW if s < 9 else "#FF5533"
                            self._canvas_eq.itemconfig(seg_id, fill=c)
                        else:
                            self._canvas_eq.itemconfig(seg_id, fill="#181818")

                    if band_val > self._eq_peak_levels[i]:
                        self._eq_peak_levels[i] = band_val
                    else:
                        self._eq_peak_levels[i] = max(0.0, self._eq_peak_levels[i] - 0.04)

                    peak_y = int(base_y - (min(1.0, self._eq_peak_levels[i]) * 75))
                    if i < len(self._eq_x_coords):
                        x_base = self._eq_x_coords[i]
                        self._canvas_eq.coords(self._eq_peaks[i], x_base, peak_y, x_base + col_w, peak_y)

    def open_benchmark_window(self):
        """Switches to Tab 5 (Embedded Hardware Benchmark)."""
        self._select_tab("HARDWARE BENCHMARK")

    def hide_to_tray(self):
        """Hides the GUI window to the Windows System Tray without interrupting the background sync service."""
        if self.root and self.root.winfo_exists():
            self._is_gui_active = False
            if self._after_id:
                try:
                    self.root.after_cancel(self._after_id)
                except Exception:
                    pass
                self._after_id = None
            self.root.withdraw()
            if self.on_window_hide:
                try:
                    self.on_window_hide()
                except Exception:
                    pass

    def restore_from_tray(self):
        """Restores and focuses the GUI window from the Windows System Tray."""
        if self.root and self.root.winfo_exists():
            self.root.deiconify()
            self.root.lift()
            try:
                self.root.attributes("-topmost", True)
                self.root.attributes("-topmost", False)
            except Exception:
                pass
            self.root.focus_force()
            if not self._is_gui_active:
                self._is_gui_active = True
                self._schedule_gui_update()

    def exit_application(self):
        """Completely terminates the application and closes the GUI window."""
        self._on_window_close()

    def _on_window_close(self):
        """Clean application shutdown on window close."""
        if self._after_id and self.root and self.root.winfo_exists():
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def run(self):
        """Starts the main Tkinter UI event loop."""
        self.create_window()
        if self.root:
            self.root.mainloop()
