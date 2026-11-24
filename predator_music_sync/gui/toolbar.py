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
import ctypes
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
from ..hardware.device_detector import (
    detect_laptop_model,
    LaptopModelInfo,
    KeyboardType,
    map_4zone_to_n,
    map_auxiliary_device_colors,
)


def _rgb_to_hex(rgb: RGBColor) -> str:
    return f"#{max(0, min(255, int(rgb[0]))):02x}{max(0, min(255, int(rgb[1]))):02x}{max(0, min(255, int(rgb[2]))):02x}"


def _dim_color(rgb: RGBColor, factor: float) -> str:
    r = int(max(0, min(255, rgb[0] * factor)))
    g = int(max(0, min(255, rgb[1] * factor)))
    b = int(max(0, min(255, rgb[2] * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend_over_base(base: RGBColor, led_rgb: RGBColor, factor: float) -> str:
    """Blends backlit LED emission smoothly over dark keycap plastic with zero low-level pop."""
    r = int(max(0, min(255, round(base[0] + led_rgb[0] * factor))))
    g = int(max(0, min(255, round(base[1] + led_rgb[1] * factor))))
    b = int(max(0, min(255, round(base[2] + led_rgb[2] * factor))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _scale_rgb_brightness(rgb: RGBColor, scale: float) -> RGBColor:
    return (
        int(max(0, min(255, round(rgb[0] * scale)))),
        int(max(0, min(255, round(rgb[1] * scale)))),
        int(max(0, min(255, round(rgb[2] * scale)))),
    )


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
    ACCENT_GREEN = "#00E676"      # AC wall power green
    ACCENT_AMBER = "#FFB300"      # Battery amber
    ACCENT_SAVER = "#FF5533"      # Battery saver warning red
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
        on_toggle_battery_saver: Optional[Callable[[bool], None]] = None,
        on_plugged_effect_change: Optional[Callable[[str], None]] = None,
        on_battery_effect_change: Optional[Callable[[str], None]] = None,
        on_battery_brightness_cap_change: Optional[Callable[[int], None]] = None,
        laptop_info: Optional[LaptopModelInfo] = None,
        on_toggle_aux_sync: Optional[Callable[[bool], None]] = None,
        on_aux_mode_change: Optional[Callable[[str], None]] = None,
        on_start_hardware_service: Optional[Callable[[], None]] = None,
        on_toggle_physical_brightness: Optional[Callable[[bool], None]] = None,
        physical_brightness_supported: bool = True,
        initial_physical_brightness_enabled: bool = True,
        initial_aux_sync_enabled: bool = True,
        initial_aux_mode: str = "Beat Pulse (Zone 2)",
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
        initial_battery_saver_disable: bool = True,
        initial_plugged_mode: str = "Dynamic Studio EQ",
        initial_battery_mode: str = "Static Album Art",
        initial_battery_brightness_cap: int = 50,
    ):
        self.laptop_info = laptop_info or detect_laptop_model()
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
        self.on_toggle_battery_saver = on_toggle_battery_saver
        self.on_plugged_effect_change = on_plugged_effect_change
        self.on_battery_effect_change = on_battery_effect_change
        self.on_battery_brightness_cap_change = on_battery_brightness_cap_change
        self.on_toggle_aux_sync = on_toggle_aux_sync
        self.on_aux_mode_change = on_aux_mode_change
        self.on_start_hardware_service = on_start_hardware_service
        self.on_toggle_physical_brightness = on_toggle_physical_brightness
        self._physical_brightness_supported = bool(physical_brightness_supported)
        self._physical_brightness_enabled = bool(initial_physical_brightness_enabled)
        self._suppress_bright_target: Optional[int] = None

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

        # Power & Battery Subsystem State
        self._is_battery_saver_disable = initial_battery_saver_disable
        self._plugged_mode = initial_plugged_mode
        self._battery_mode = initial_battery_mode
        self._battery_brightness_cap = initial_battery_brightness_cap
        self._is_plugged_in: bool = True
        self._is_battery_saver_active: bool = False
        self._battery_percent: int = 100
        self._power_poll_tick: int = 0

        # Auxiliary Hardware Sync State (Rear Lightbar & Lid Logo)
        self._aux_sync_enabled = initial_aux_sync_enabled
        self._aux_mode = initial_aux_mode
        self._kb_key_x_rels: List[float] = []
        self._kb_key_norm_x: List[float] = []
        self._kb_key_texts: List[int] = []
        self._kb_key_labels: List[str] = []
        self._kb_key_predator: List[int] = []
        self._lightbar_segs: List[int] = []
        self._pending_is_beat: bool = False

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

        # Header & Hardware Model Widgets
        self._lbl_model: Optional[tk.Label] = None
        self._lbl_hw_status: Optional[tk.Label] = None
        self._lbl_power_status: Optional[tk.Label] = None
        self._lbl_header_track: Optional[tk.Label] = None
        self._btn_toggle: Optional[tk.Button] = None

        # Full Realistic Keyboard Canvas & Auxiliary Mirror
        self._lbl_kb_matrix: Optional[tk.Label] = None
        self._canvas_kb: Optional[tk.Canvas] = None
        self._banner_saver: Optional[tk.Frame] = None
        self._frame_aux: Optional[tk.Frame] = None
        self._lbl_aux_badge: Optional[tk.Label] = None
        self._canvas_lightbar: Optional[tk.Canvas] = None
        self._lightbar_rect: Optional[int] = None
        self._btn_aux_toggle: Optional[tk.Button] = None
        self._btn_aux_tab3_toggle: Optional[tk.Button] = None
        self._combo_aux_mode: Optional[ttk.Combobox] = None
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
        self._btn_phys_bright: Optional[tk.Button] = None
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

        # Tab 4: Profiles & Power Efficiency Widgets
        self._entry_profile_name: Optional[tk.Entry] = None
        self._lbl_profile_status: Optional[tk.Label] = None
        self._btn_autostart: Optional[tk.Button] = None
        self._btn_battery_saver: Optional[tk.Button] = None
        self._combo_plugged_effect: Optional[ttk.Combobox] = None
        self._combo_battery_effect: Optional[ttk.Combobox] = None
        self._slider_battery_cap: Optional[tk.Scale] = None
        self._lbl_val_battery_cap: Optional[tk.Label] = None

        # Tab 5: Benchmark Widgets
        self._txt_bench: Optional[scrolledtext.ScrolledText] = None
        self._lbl_bench_bus: Optional[tk.Label] = None
        self._lbl_bench_fps: Optional[tk.Label] = None

        # Bottom Status Bar
        self._lbl_status_track: Optional[tk.Label] = None

    def create_window(self):
        """Builds and initializes the desktop application window with clean centering."""
        self.root = tk.Tk()
        self.root.title("MusicalPredator")

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
            left, text="▲ MUSICALPREDATOR",
            font=(self.FONT_FAMILY, 9, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL
        )
        lbl_logo.pack(side="left")

        self._lbl_model = tk.Label(
            left, text=f"// {self.laptop_info.display_name.upper()}",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        )
        self._lbl_model.pack(side="left", padx=(6, 14))

        if "Virtual" in self.controller_name:
            hw_color = self.TEXT_MUTED
            hw_text = "● VIRTUAL CONTROLLER [EMULATION]"
            cursor = ""
        elif self.is_hardware_connected:
            hw_color = self.ACCENT_YELLOW
            hw_text = f"● {self.controller_name.upper()} [CONNECTED]"
            cursor = ""
        else:
            hw_color = self.ACCENT_WARN
            hw_text = f"⚠ {self.controller_name.upper()} [SERVICE STOPPED - CLICK TO START]"
            cursor = "hand2"

        self._lbl_hw_status = tk.Label(
            left, text=hw_text,
            font=(self.FONT_FAMILY, 7, "bold"), fg=hw_color, bg=self.SURFACE_PANEL,
            cursor=cursor
        )
        self._lbl_hw_status.pack(side="left")
        self._lbl_hw_status.bind("<Button-1>", self._trigger_start_hardware_service)

        # Live Power & Battery Status Badge
        self._lbl_power_status = tk.Label(
            left, text="⚡ PLUGGED IN",
            font=(self.FONT_FAMILY, 7, "bold"), fg=self.ACCENT_GREEN, bg=self.SURFACE_PANEL
        )
        self._lbl_power_status.pack(side="left", padx=(10, 0))

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
        panel = tk.Frame(self.root, bg=self.SURFACE_PANEL, height=202, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        panel.pack(fill="x", padx=14, pady=(6, 4))
        panel.pack_propagate(False)

        # Unobtrusive Battery Saver Notification Banner (hidden by default)
        self._banner_saver = tk.Frame(
            panel, bg="#1E1400", highlightthickness=1,
            highlightbackground="#664400", height=22
        )
        self._banner_saver.pack_propagate(False)

        lbl_saver = tk.Label(
            self._banner_saver,
            text="🌙 Battery Saver Active • Keyboard lighting and audio sampling suspended to conserve power",
            font=(self.FONT_FAMILY, 7, "bold"),
            fg="#FFB300",
            bg="#1E1400"
        )
        lbl_saver.pack(fill="both", expand=True)

        hdr = tk.Frame(panel, bg=self.SURFACE_PANEL)
        hdr.pack(fill="x", padx=10, pady=(3, 1))

        tk.Label(
            hdr, text="PHYSICAL KEYBOARD HARDWARE MIRROR",
            font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(side="left")

        self._lbl_kb_matrix = tk.Label(
            hdr, text=f"{self.laptop_info.model_name.upper()} MATRIX • {self.laptop_info.keyboard_type.value.upper()} • 100 KEYS",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        )
        self._lbl_kb_matrix.pack(side="right")

        # Auxiliary Device Sync Strip (Rear Lightbar & Lid Logo)
        self._frame_aux = tk.Frame(panel, bg=self.SURFACE_PANEL, height=14)
        self._frame_aux.pack(fill="x", padx=8, pady=(1, 2))
        self._frame_aux.pack_propagate(False)

        has_aux = bool(self.laptop_info.has_rear_lightbar or self.laptop_info.has_lid_logo)
        if self.laptop_info.has_rear_lightbar:
            aux_lbl_text = "REAR LIGHTBAR & LOGO //"
        elif self.laptop_info.has_lid_logo:
            aux_lbl_text = "PREDATOR LID LOGO //"
        else:
            aux_lbl_text = "AUX PERIPHERALS // NONE ON MODEL"

        self._lbl_aux_badge = tk.Label(
            self._frame_aux, text=aux_lbl_text,
            font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        )
        self._lbl_aux_badge.pack(side="left", padx=(2, 6))

        self._canvas_lightbar = tk.Canvas(self._frame_aux, height=8, bg="#0A0A0A", bd=0, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        self._canvas_lightbar.pack(side="left", fill="x", expand=True)
        self._canvas_lightbar.bind("<Configure>", self._redraw_lightbar_canvas)
        self._lightbar_rect = self._canvas_lightbar.create_rectangle(0, 0, 1200, 8, fill="#101010", outline="")
        self._lightbar_segs = [self._lightbar_rect]

        self._btn_aux_toggle = tk.Button(
            self._frame_aux,
            text="AUX SYNC: ON" if (self._aux_sync_enabled and has_aux) else ("AUX SYNC: OFF" if has_aux else "AUX: N/A"),
            font=(self.FONT_FAMILY, 6, "bold"),
            bg=self.ACCENT_YELLOW if (self._aux_sync_enabled and has_aux) else "#161616",
            fg="#000000" if (self._aux_sync_enabled and has_aux) else self.TEXT_MUTED,
            bd=0, padx=8, pady=0, cursor="hand2",
            highlightthickness=1, highlightbackground=self.ACCENT_YELLOW if (self._aux_sync_enabled and has_aux) else self.BORDER_HAIRLINE,
            command=self._toggle_aux_sync_gui
        )
        self._btn_aux_toggle.pack(side="right", padx=(6, 2))

        self._canvas_kb = tk.Canvas(panel, height=120, bg=self.SURFACE_PANEL, bd=0, highlightthickness=0)
        self._canvas_kb.pack(fill="x", padx=8, pady=(1, 2))
        self._canvas_kb.bind("<Configure>", self._draw_full_keyboard)

        # Under-keyboard 4-zone telemetry bar
        info_bar = tk.Frame(panel, bg=self.SURFACE_PANEL)
        info_bar.pack(fill="x", padx=8, pady=(0, 3))

        zone_titles = [
            ("ZONE 1", "WASD / BASS (20-120Hz)"),
            ("ZONE 2", "MID-LEFT / LOW-MID (120-500Hz)"),
            ("ZONE 3", "MID-RIGHT / VOCALS (500-3.5kHz)"),
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

    def _redraw_lightbar_canvas(self, event=None):
        """Draws the auxiliary lightbar / lid logo LED segments matching hardware layout."""
        if not self._canvas_lightbar:
            return
        w = self._canvas_lightbar.winfo_width()
        h = self._canvas_lightbar.winfo_height()
        if w < 20 or h < 4:
            return

        self._canvas_lightbar.delete("all")
        self._lightbar_segs = []

        if self.laptop_info.has_rear_lightbar:
            num_segs = 12
            gap = 2
            seg_w = max(4.0, (w - (num_segs - 1) * gap) / float(num_segs))
            for i in range(num_segs):
                x1 = i * (seg_w + gap)
                x2 = x1 + seg_w
                seg = self._canvas_lightbar.create_rectangle(x1, 0, x2, h, fill="#101010", outline="")
                self._lightbar_segs.append(seg)
            self._lightbar_rect = self._lightbar_segs[0]
        elif self.laptop_info.has_lid_logo:
            cx = w / 2.0
            logo_w = min(80.0, w * 0.25)
            seg = self._canvas_lightbar.create_rectangle(cx - logo_w / 2.0, 0, cx + logo_w / 2.0, h, fill="#101010", outline="")
            self._lightbar_segs = [seg]
            self._lightbar_rect = seg
        else:
            seg = self._canvas_lightbar.create_rectangle(0, 0, w, h, fill="#101010", outline="")
            self._lightbar_segs = [seg]
            self._lightbar_rect = seg

        self._last_rendered_colors = [(-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)]

    @staticmethod
    def _smoothstep_per_key_color(colors: List[RGBColor], norm_x: float) -> RGBColor:
        """Evaluates continuous 4-zone Hermite smoothstep gradient matching device_detector.map_4zone_to_n."""
        t = max(0.0, min(1.0, float(norm_x)))
        if t <= (1.0 / 3.0):
            u = t * 3.0
            c1, c2 = colors[0], colors[1]
        elif t <= (2.0 / 3.0):
            u = (t - (1.0 / 3.0)) * 3.0
            c1, c2 = colors[1], colors[2]
        else:
            u = (t - (2.0 / 3.0)) * 3.0
            c1, c2 = colors[2], colors[3]
        u_c = max(0.0, min(1.0, u))
        w = u_c * u_c * (3.0 - 2.0 * u_c)
        return (
            int(max(0, min(255, round(c1[0] + (c2[0] - c1[0]) * w)))),
            int(max(0, min(255, round(c1[1] + (c2[1] - c1[1]) * w)))),
            int(max(0, min(255, round(c1[2] + (c2[2] - c1[2]) * w)))),
        )

    def _draw_full_keyboard(self, event=None):
        """Draws realistic Acer Predator Helios Neo 16 keyboard layout with aligned zones and symbols."""
        if not self._canvas_kb:
            return

        w = self._canvas_kb.winfo_width()
        h = self._canvas_kb.winfo_height()
        if w < 200 or h < 50:
            return

        self._canvas_kb.delete("all")
        self._kb_key_rects = []
        self._kb_key_texts = []
        self._kb_key_labels = []
        self._kb_key_zones = []
        self._kb_key_wasd = []
        self._kb_key_arrows = []
        self._kb_key_predator = []
        self._kb_zone_backs = []
        self._kb_key_x_rels = []
        self._kb_key_norm_x = []

        pad_x = 4
        pad_y = 2
        well_w = w - (pad_x * 2)
        well_h = h - (pad_y * 2)

        # Outer keyboard well
        self._canvas_kb.create_rectangle(
            pad_x, pad_y, pad_x + well_w, pad_y + well_h,
            fill="#080808", outline=self.BORDER_HAIRLINE, width=1
        )

        # Detailed Key definitions:
        # (row, x_rel, width_rel, row_span, label, zone, is_wasd, is_arrow, is_predator)
        keys_def = [
            # Row 0: Function Row & Numpad Header Row
            (0, 0.0, 1.0, 1, "ESC", 0, False, False, False),
            (0, 1.2, 0.9, 1, "F1", 0, False, False, False),
            (0, 2.15, 0.9, 1, "F2", 0, False, False, False),
            (0, 3.1, 0.9, 1, "F3", 0, False, False, False),
            (0, 4.05, 0.9, 1, "F4", 0, False, False, False),
            (0, 5.15, 0.9, 1, "F5", 1, False, False, False),
            (0, 6.1, 0.9, 1, "F6", 1, False, False, False),
            (0, 7.05, 0.9, 1, "F7", 1, False, False, False),
            (0, 8.0, 0.9, 1, "F8", 1, False, False, False),
            (0, 9.1, 0.9, 1, "F9", 2, False, False, False),
            (0, 10.05, 0.9, 1, "F10", 2, False, False, False),
            (0, 11.0, 0.9, 1, "F11", 2, False, False, False),
            (0, 11.95, 0.9, 1, "F12", 2, False, False, False),
            (0, 13.0, 0.9, 1, "PRT", 2, False, False, False),
            (0, 13.95, 0.95, 1, "DEL", 2, False, False, False),
            # Numpad Row 0
            (0, 16.15, 0.95, 1, "[P]", 3, False, False, True),
            (0, 17.15, 0.95, 1, "HOME", 3, False, False, False),
            (0, 18.15, 0.95, 1, "PGUP", 3, False, False, False),
            (0, 19.15, 0.95, 1, "END", 3, False, False, False),

            # Row 1: Number Row & Numpad Row 1
            (1, 0.0, 0.95, 1, "~", 0, False, False, False),
            (1, 1.0, 0.95, 1, "1", 0, False, False, False),
            (1, 2.0, 0.95, 1, "2", 0, False, False, False),
            (1, 3.0, 0.95, 1, "3", 0, False, False, False),
            (1, 4.0, 0.95, 1, "4", 0, False, False, False),
            (1, 5.0, 0.95, 1, "5", 1, False, False, False),
            (1, 6.0, 0.95, 1, "6", 1, False, False, False),
            (1, 7.0, 0.95, 1, "7", 1, False, False, False),
            (1, 8.0, 0.95, 1, "8", 1, False, False, False),
            (1, 9.0, 0.95, 1, "9", 2, False, False, False),
            (1, 10.0, 0.95, 1, "0", 2, False, False, False),
            (1, 11.0, 0.95, 1, "-", 2, False, False, False),
            (1, 12.0, 0.95, 1, "=", 2, False, False, False),
            (1, 13.0, 1.9, 1, "BACK", 2, False, False, False),
            # Numpad Row 1
            (1, 16.15, 0.95, 1, "NUM", 3, False, False, False),
            (1, 17.15, 0.95, 1, "/", 3, False, False, False),
            (1, 18.15, 0.95, 1, "*", 3, False, False, False),
            (1, 19.15, 0.95, 1, "-", 3, False, False, False),

            # Row 2: QWERTY Row & Numpad Row 2 (tall '+' spans rows 2-3)
            (2, 0.0, 1.45, 1, "TAB", 0, False, False, False),
            (2, 1.5, 0.95, 1, "Q", 0, False, False, False),
            (2, 2.5, 0.95, 1, "W", 0, True, False, False),
            (2, 3.5, 0.95, 1, "E", 0, False, False, False),
            (2, 4.5, 0.95, 1, "R", 0, False, False, False),
            (2, 5.5, 0.95, 1, "T", 1, False, False, False),
            (2, 6.5, 0.95, 1, "Y", 1, False, False, False),
            (2, 7.5, 0.95, 1, "U", 1, False, False, False),
            (2, 8.5, 0.95, 1, "I", 1, False, False, False),
            (2, 9.5, 0.95, 1, "O", 2, False, False, False),
            (2, 10.5, 0.95, 1, "P", 2, False, False, False),
            (2, 11.5, 0.95, 1, "[", 2, False, False, False),
            (2, 12.5, 0.95, 1, "]", 2, False, False, False),
            (2, 13.5, 1.4, 1, "\\", 2, False, False, False),
            # Numpad Row 2
            (2, 16.15, 0.95, 1, "7", 3, False, False, False),
            (2, 17.15, 0.95, 1, "8", 3, False, False, False),
            (2, 18.15, 0.95, 1, "9", 3, False, False, False),
            (2, 19.15, 0.95, 2, "+", 3, False, False, False),

            # Row 3: Home Row & Numpad Row 3
            (3, 0.0, 1.75, 1, "CAPS", 0, False, False, False),
            (3, 1.8, 0.95, 1, "A", 0, True, False, False),
            (3, 2.8, 0.95, 1, "S", 0, True, False, False),
            (3, 3.8, 0.95, 1, "D", 0, True, False, False),
            (3, 4.8, 0.95, 1, "F", 0, False, False, False),
            (3, 5.8, 0.95, 1, "G", 1, False, False, False),
            (3, 6.8, 0.95, 1, "H", 1, False, False, False),
            (3, 7.8, 0.95, 1, "J", 1, False, False, False),
            (3, 8.8, 0.95, 1, "K", 1, False, False, False),
            (3, 9.8, 0.95, 1, "L", 2, False, False, False),
            (3, 10.8, 0.95, 1, ";", 2, False, False, False),
            (3, 11.8, 0.95, 1, "'", 2, False, False, False),
            (3, 12.8, 2.1, 1, "ENTER", 2, False, False, False),
            # Numpad Row 3
            (3, 16.15, 0.95, 1, "4", 3, False, False, False),
            (3, 17.15, 0.95, 1, "5", 3, False, False, False),
            (3, 18.15, 0.95, 1, "6", 3, False, False, False),

            # Row 4: Shift Row & Numpad Row 4 (tall 'ENT' spans rows 4-5)
            (4, 0.0, 2.25, 1, "SHIFT", 0, False, False, False),
            (4, 2.3, 0.95, 1, "Z", 0, False, False, False),
            (4, 3.3, 0.95, 1, "X", 0, False, False, False),
            (4, 4.3, 0.95, 1, "C", 0, False, False, False),
            (4, 5.3, 0.95, 1, "V", 0, False, False, False),
            (4, 6.3, 0.95, 1, "B", 1, False, False, False),
            (4, 7.3, 0.95, 1, "N", 1, False, False, False),
            (4, 8.3, 0.95, 1, "M", 1, False, False, False),
            (4, 9.3, 0.95, 1, ",", 2, False, False, False),
            (4, 10.3, 0.95, 1, ".", 2, False, False, False),
            (4, 11.3, 0.95, 1, "/", 2, False, False, False),
            (4, 12.3, 1.55, 1, "SHIFT", 2, False, False, False),
            (4, 13.95, 0.95, 1, "↑", 2, False, True, False),
            # Numpad Row 4
            (4, 16.15, 0.95, 1, "1", 3, False, False, False),
            (4, 17.15, 0.95, 1, "2", 3, False, False, False),
            (4, 18.15, 0.95, 1, "3", 3, False, False, False),
            (4, 19.15, 0.95, 2, "ENT", 3, False, False, False),

            # Row 5: Bottom Row & Numpad Row 5
            (5, 0.0, 1.25, 1, "CTRL", 0, False, False, False),
            (5, 1.3, 0.95, 1, "FN", 0, False, False, False),
            (5, 2.3, 0.95, 1, "WIN", 0, False, False, False),
            (5, 3.3, 1.15, 1, "ALT", 0, False, False, False),
            (5, 4.5, 5.2, 1, "SPACE", 1, False, False, False),
            (5, 9.8, 1.15, 1, "ALT", 2, False, False, False),
            (5, 11.0, 1.15, 1, "CTRL", 2, False, False, False),
            (5, 12.95, 0.95, 1, "←", 2, False, True, False),
            (5, 13.95, 0.95, 1, "↓", 2, False, True, False),
            (5, 14.95, 0.95, 1, "→", 2, False, True, False),
            # Numpad Row 5
            (5, 16.15, 1.95, 1, "0", 3, False, False, False),
            (5, 18.15, 0.95, 1, ".", 3, False, False, False),
        ]

        total_rel_w = 20.25
        unit_w = (well_w - 12) / total_rel_w
        row_h = (well_h - 10) / 6.0

        def _x_px(xr: float) -> float:
            return pad_x + 6 + (xr * unit_w)

        def _y_px(r: float) -> float:
            return pad_y + 4 + (r * row_h)

        # Underglow backdrops matched exactly to hardware zone topology
        kb_type = self.laptop_info.keyboard_type
        if kb_type == KeyboardType.ONE_ZONE_RGB:
            zb = self._canvas_kb.create_rectangle(
                pad_x + 1, pad_y + 1, pad_x + well_w - 1, pad_y + well_h - 1,
                fill="#0D0D0D", outline="", width=0
            )
            self._kb_zone_backs.append(zb)
        elif kb_type == KeyboardType.THREE_ZONE_RGB:
            zone_w = (well_w - 2) / 3.0
            for z in range(3):
                zx1 = pad_x + 1 + (z * zone_w)
                zx2 = zx1 + zone_w
                zb = self._canvas_kb.create_rectangle(
                    zx1, pad_y + 1, zx2, pad_y + well_h - 1,
                    fill="#0D0D0D", outline="", width=0
                )
                self._kb_zone_backs.append(zb)
        elif kb_type == KeyboardType.PER_KEY_RGB:
            slices = 24
            sw = (well_w - 2) / float(slices)
            for s in range(slices):
                sx1 = pad_x + 1 + (s * sw)
                sx2 = sx1 + sw + 0.5
                zb = self._canvas_kb.create_rectangle(
                    sx1, pad_y + 1, sx2, pad_y + well_h - 1,
                    fill="#0D0D0D", outline="", width=0
                )
                self._kb_zone_backs.append(zb)
        else:
            # 4-Zone RGB: build exact per-row seam polygons aligned to keys in each zone
            row_seams: Dict[int, List[float]] = {}
            for r in range(6):
                z_bounds: Dict[int, Tuple[float, float]] = {}
                for row_i, xr, wr, _, _, z_i, _, _, _ in keys_def:
                    if row_i == r:
                        k_left = _x_px(xr)
                        k_right = _x_px(xr + wr) - 2
                        if z_i not in z_bounds:
                            z_bounds[z_i] = (k_left, k_right)
                        else:
                            z_bounds[z_i] = (min(z_bounds[z_i][0], k_left), max(z_bounds[z_i][1], k_right))
                s01 = (z_bounds[0][1] + z_bounds[1][0]) / 2.0
                s12 = (z_bounds[1][1] + z_bounds[2][0]) / 2.0
                s23 = (z_bounds[2][1] + z_bounds[3][0]) / 2.0
                row_seams[r] = [pad_x + 1, s01, s12, s23, pad_x + well_w - 1]

            for z in range(4):
                pts: List[float] = []
                # Left edge top-to-bottom
                for r in range(6):
                    y_top = (pad_y + 1) if r == 0 else _y_px(r) - 1
                    y_bot = (pad_y + well_h - 1) if r == 5 else _y_px(r + 1) - 1
                    pts.extend([row_seams[r][z], y_top, row_seams[r][z], y_bot])
                # Right edge bottom-to-top
                for r in range(5, -1, -1):
                    y_top = (pad_y + 1) if r == 0 else _y_px(r) - 1
                    y_bot = (pad_y + well_h - 1) if r == 5 else _y_px(r + 1) - 1
                    pts.extend([row_seams[r][z + 1], y_bot, row_seams[r][z + 1], y_top])
                zb = self._canvas_kb.create_polygon(pts, fill="#0D0D0D", outline="", width=0)
                self._kb_zone_backs.append(zb)

        min_center = min(xr + wr * 0.5 for _, xr, wr, *_ in keys_def)
        max_center = max(xr + wr * 0.5 for _, xr, wr, *_ in keys_def)
        center_span = max(0.001, max_center - min_center)

        for row, x_rel, w_rel, row_span, label, zone, is_wasd, is_arrow, is_pred in keys_def:
            kx1 = _x_px(x_rel)
            kx2 = _x_px(x_rel + w_rel) - 2
            ky1 = _y_px(row)
            ky2 = _y_px(row + row_span) - 2

            if is_wasd:
                # Distinctive frosted white gamer keycap
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#141414", outline="#FFFFFF", width=1.5
                )
                txt_id = self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 7, "bold"), fill=self.ACCENT_YELLOW
                )
                self._kb_key_wasd.append(k)
            elif is_arrow:
                # Inverted-T Arrow keys with frosted gamer outline
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#141414", outline="#FFFFFF", width=1.5
                )
                txt_id = self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 8, "bold"), fill=self.ACCENT_YELLOW
                )
                self._kb_key_arrows.append(k)
            elif is_pred:
                # Iconic Predator Sense Key [P]
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#161616", outline=self.ACCENT_YELLOW, width=1.2
                )
                txt_id = self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, 6, "bold"), fill=self.ACCENT_YELLOW
                )
                self._kb_key_predator.append(k)
            else:
                k = self._canvas_kb.create_rectangle(
                    kx1, ky1, kx2, ky2,
                    fill="#0F0F0F", outline=self.BORDER_HAIRLINE, width=1
                )
                font_sz = 6 if len(label) > 3 else 7
                txt_id = self._canvas_kb.create_text(
                    (kx1 + kx2) / 2, (ky1 + ky2) / 2,
                    text=label, font=(self.FONT_FAMILY, font_sz), fill=self.TEXT_SECONDARY
                )

            self._kb_key_rects.append(k)
            self._kb_key_texts.append(txt_id)
            self._kb_key_labels.append(label)
            self._kb_key_zones.append(zone)
            self._kb_key_x_rels.append(x_rel)
            self._kb_key_norm_x.append(((x_rel + w_rel * 0.5) - min_center) / center_span)

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
        phys_active = self._physical_brightness_supported and self._physical_brightness_enabled
        phys_text = "EC SYNC: ON" if phys_active else ("EC SYNC: OFF" if self._physical_brightness_supported else "SW SCALE")
        self._btn_phys_bright = tk.Button(
            h1, text=phys_text, font=(self.FONT_FAMILY, 6, "bold"),
            bg="#1E1800" if phys_active else "#161616",
            fg=self.ACCENT_YELLOW if phys_active else self.TEXT_MUTED,
            bd=0, padx=6, pady=0, cursor="hand2" if self._physical_brightness_supported else "",
            highlightthickness=1,
            highlightbackground=self.ACCENT_YELLOW if phys_active else self.BORDER_HAIRLINE,
            command=self._toggle_physical_brightness_gui
        )
        self._btn_phys_bright.pack(side="right", padx=(0, 8))
        self._slider_bright = tk.Scale(
            s1, from_=0, to=100, resolution=5, orient="horizontal",
            bg=self.SURFACE_PANEL, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_bright_change
        )
        self._slider_bright.set(self._current_brightness)
        self._slider_bright.pack(fill="x")
        tk.Label(s1, text="Physical EC backlight + Fn+F9/F10 hotkey sync (0% off, 100% full)", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL).pack(anchor="w")

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

        # Auxiliary Hardware Sync Card
        aux_card = tk.Frame(panel, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        aux_card.pack(fill="x", padx=16, pady=(6, 2))

        a_row = tk.Frame(aux_card, bg=self.SURFACE_CARD)
        a_row.pack(fill="x", padx=10, pady=6)

        a_left = tk.Frame(a_row, bg=self.SURFACE_CARD)
        a_left.pack(side="left")
        tk.Label(a_left, text="AUXILIARY HARDWARE SYNC (REAR LIGHTBAR & PREDATOR LID LOGO)", font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(anchor="w")
        tk.Label(a_left, text="Synchronizes rear exhaust lightbar and chassis Predator lid emblem with musical beats", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")

        self._btn_aux_tab3_toggle = tk.Button(
            a_row,
            text="ENABLED" if self._aux_sync_enabled else "DISABLED",
            font=(self.FONT_FAMILY, 7, "bold"),
            bg=self.ACCENT_YELLOW if self._aux_sync_enabled else "#161616",
            fg="#000000" if self._aux_sync_enabled else self.TEXT_MUTED,
            bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.ACCENT_YELLOW if self._aux_sync_enabled else self.BORDER_HAIRLINE,
            command=self._toggle_aux_sync_gui
        )
        self._btn_aux_tab3_toggle.pack(side="right")

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

        # Power & Battery Efficiency Card
        tk.Label(
            col_right, text="POWER & BATTERY EFFICIENCY",
            font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w", padx=14, pady=(6, 4))

        pwr_card = tk.Frame(col_right, bg=self.SURFACE_CARD, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        pwr_card.pack(fill="x", padx=14, pady=(0, 6))

        # 1. Toggle: DISABLE APP ON BATTERY SAVER
        t_row = tk.Frame(pwr_card, bg=self.SURFACE_CARD)
        t_row.pack(fill="x", padx=10, pady=(6, 4))

        t_left = tk.Frame(t_row, bg=self.SURFACE_CARD)
        t_left.pack(side="left")
        tk.Label(t_left, text="DISABLE APP ON BATTERY SAVER", font=(self.FONT_FAMILY, 8, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD).pack(anchor="w")
        tk.Label(t_left, text="Turns off keyboard LEDs & suspends audio sampling in Battery Saver", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")

        pwr_btn_bg = self.ACCENT_YELLOW if self._is_battery_saver_disable else "#161616"
        pwr_btn_fg = "#000000" if self._is_battery_saver_disable else self.TEXT_MUTED
        self._btn_battery_saver = tk.Button(
            t_row,
            text="ENABLED (RECOMMENDED)" if self._is_battery_saver_disable else "DISABLED",
            font=(self.FONT_FAMILY, 7, "bold"),
            bg=pwr_btn_bg, fg=pwr_btn_fg,
            bd=0, padx=10, pady=3, cursor="hand2",
            highlightthickness=1, highlightbackground=self.ACCENT_YELLOW if self._is_battery_saver_disable else self.BORDER_HAIRLINE,
            command=self._toggle_battery_saver_disable_gui
        )
        self._btn_battery_saver.pack(side="right")

        # 2. Dual Power Profile Effects Dropdowns (Plugged In Effect & On Battery Effect)
        effects_row = tk.Frame(pwr_card, bg=self.SURFACE_CARD)
        effects_row.pack(fill="x", padx=10, pady=(2, 4))

        # Left: Plugged In Effect
        col_plugged = tk.Frame(effects_row, bg=self.SURFACE_CARD)
        col_plugged.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Label(col_plugged, text="PLUGGED IN EFFECT:", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")
        self._combo_plugged_effect = ttk.Combobox(
            col_plugged,
            values=list(ANIMATION_REGISTRY.keys()),
            state="readonly",
            style="Dark.TCombobox",
            font=(self.FONT_FAMILY, 7)
        )
        self._combo_plugged_effect.set(self._plugged_mode if self._plugged_mode in ANIMATION_REGISTRY else "Dynamic Studio EQ")
        self._combo_plugged_effect.pack(fill="x", pady=(2, 0))
        self._combo_plugged_effect.bind("<<ComboboxSelected>>", self._handle_plugged_effect_select)

        # Right: On Battery Effect
        col_batt = tk.Frame(effects_row, bg=self.SURFACE_CARD)
        col_batt.pack(side="right", fill="x", expand=True, padx=(4, 0))
        tk.Label(col_batt, text="ON BATTERY EFFECT:", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")
        self._combo_battery_effect = ttk.Combobox(
            col_batt,
            values=list(ANIMATION_REGISTRY.keys()),
            state="readonly",
            style="Dark.TCombobox",
            font=(self.FONT_FAMILY, 7)
        )
        self._combo_battery_effect.set(self._battery_mode if self._battery_mode in ANIMATION_REGISTRY else "Static Album Art")
        self._combo_battery_effect.pack(fill="x", pady=(2, 0))
        self._combo_battery_effect.bind("<<ComboboxSelected>>", self._handle_battery_effect_select)

        # 3. Battery Brightness Cap Slider
        cap_row = tk.Frame(pwr_card, bg=self.SURFACE_CARD)
        cap_row.pack(fill="x", padx=10, pady=(2, 6))

        cap_header = tk.Frame(cap_row, bg=self.SURFACE_CARD)
        cap_header.pack(fill="x")
        tk.Label(cap_header, text="BATTERY BRIGHTNESS CAP:", font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(side="left")
        self._lbl_val_battery_cap = tk.Label(cap_header, text=f"{self._battery_brightness_cap}%", font=(self.FONT_MONO, 7, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_CARD)
        self._lbl_val_battery_cap.pack(side="right")

        self._slider_battery_cap = tk.Scale(
            cap_row, from_=0, to=100, orient="horizontal",
            bg=self.SURFACE_CARD, fg=self.TEXT_WHITE, highlightthickness=0, bd=0,
            activebackground=self.ACCENT_YELLOW, troughcolor="#181818",
            sliderlength=14, width=8, sliderrelief="flat", showvalue=False,
            command=self._handle_battery_cap_change
        )
        self._slider_battery_cap.set(self._battery_brightness_cap)
        self._slider_battery_cap.pack(fill="x", pady=(2, 1))

        tk.Label(cap_row, text="Caps keyboard LED brightness on DC battery to extend laptop battery life", font=(self.FONT_FAMILY, 6), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD).pack(anchor="w")

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

    def _toggle_battery_saver_disable_gui(self):
        new_val = not self._is_battery_saver_disable
        self._is_battery_saver_disable = new_val
        if self._btn_battery_saver and self.root and self.root.winfo_exists():
            btn_bg = self.ACCENT_YELLOW if new_val else "#161616"
            btn_fg = "#000000" if new_val else self.TEXT_MUTED
            self._btn_battery_saver.config(
                text="ENABLED (RECOMMENDED)" if new_val else "DISABLED",
                bg=btn_bg, fg=btn_fg,
                highlightbackground=self.ACCENT_YELLOW if new_val else self.BORDER_HAIRLINE
            )
        self.update_power_status(self._is_plugged_in, self._is_battery_saver_active, self._battery_percent)
        if self.on_toggle_battery_saver:
            self.on_toggle_battery_saver(new_val)

    def _handle_plugged_effect_select(self, event=None):
        if self._combo_plugged_effect:
            mode = self._combo_plugged_effect.get()
            self._plugged_mode = mode
            if self.on_plugged_effect_change:
                self.on_plugged_effect_change(mode)

    def _handle_battery_effect_select(self, event=None):
        if self._combo_battery_effect:
            mode = self._combo_battery_effect.get()
            self._battery_mode = mode
            if self.on_battery_effect_change:
                self.on_battery_effect_change(mode)

    def _handle_battery_cap_change(self, val):
        cap = int(float(val))
        self._battery_brightness_cap = cap
        if self._lbl_val_battery_cap:
            self._lbl_val_battery_cap.config(text=f"{cap}%")
        if self.on_battery_brightness_cap_change:
            self.on_battery_brightness_cap_change(cap)

    def set_battery_saver_disable_state(self, enabled: bool):
        self._is_battery_saver_disable = enabled
        if self._btn_battery_saver and self.root and self.root.winfo_exists():
            btn_bg = self.ACCENT_YELLOW if enabled else "#161616"
            btn_fg = "#000000" if enabled else self.TEXT_MUTED
            self._btn_battery_saver.config(
                text="ENABLED (RECOMMENDED)" if enabled else "DISABLED",
                bg=btn_bg, fg=btn_fg,
                highlightbackground=self.ACCENT_YELLOW if enabled else self.BORDER_HAIRLINE
            )
        self.update_power_status(self._is_plugged_in, self._is_battery_saver_active, self._battery_percent)

    def set_battery_brightness_cap(self, cap: int):
        self._battery_brightness_cap = int(cap)
        if self._slider_battery_cap and self.root and self.root.winfo_exists():
            self._slider_battery_cap.set(cap)
        if self._lbl_val_battery_cap:
            self._lbl_val_battery_cap.config(text=f"{cap}%")

    def set_power_profiles(self, plugged_mode: Optional[str] = None, battery_mode: Optional[str] = None):
        if plugged_mode:
            self._plugged_mode = plugged_mode
            if self._combo_plugged_effect and self.root and self.root.winfo_exists():
                self._combo_plugged_effect.set(plugged_mode)
        if battery_mode:
            self._battery_mode = battery_mode
            if self._combo_battery_effect and self.root and self.root.winfo_exists():
                self._combo_battery_effect.set(battery_mode)

    def _toggle_aux_sync_gui(self):
        new_val = not self._aux_sync_enabled
        self._aux_sync_enabled = new_val
        self.set_aux_sync_state(new_val)
        if self.on_toggle_aux_sync:
            self.on_toggle_aux_sync(new_val)

    def set_aux_sync_state(self, enabled: bool):
        self._aux_sync_enabled = enabled
        has_aux = bool(self.laptop_info.has_rear_lightbar or self.laptop_info.has_lid_logo)
        if self._btn_aux_toggle and self.root and self.root.winfo_exists():
            self._btn_aux_toggle.config(
                text=("AUX SYNC: ON" if enabled else "AUX SYNC: OFF") if has_aux else "AUX: N/A",
                bg=self.ACCENT_YELLOW if (enabled and has_aux) else "#161616",
                fg="#000000" if (enabled and has_aux) else self.TEXT_MUTED,
                highlightbackground=self.ACCENT_YELLOW if (enabled and has_aux) else self.BORDER_HAIRLINE
            )
        if self._btn_aux_tab3_toggle and self.root and self.root.winfo_exists():
            self._btn_aux_tab3_toggle.config(
                text="ENABLED" if enabled else "DISABLED",
                bg=self.ACCENT_YELLOW if enabled else "#161616",
                fg="#000000" if enabled else self.TEXT_MUTED,
                highlightbackground=self.ACCENT_YELLOW if enabled else self.BORDER_HAIRLINE
            )
        self._last_rendered_colors = [(-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)]
        if not enabled and self._canvas_lightbar:
            try:
                for seg in (self._lightbar_segs or ([self._lightbar_rect] if self._lightbar_rect else [])):
                    self._canvas_lightbar.itemconfig(seg, fill="#101010")
            except Exception:
                pass

    def update_laptop_model(self, laptop_info: LaptopModelInfo):
        """Dynamically updates the UI to reflect a newly detected laptop model."""
        self.laptop_info = laptop_info
        if self.root and self.root.winfo_exists():
            try:
                if self._lbl_model:
                    self._lbl_model.config(text=f"// {laptop_info.display_name.upper()}")
                if self._lbl_kb_matrix:
                    self._lbl_kb_matrix.config(text=f"{laptop_info.model_name.upper()} MATRIX • {laptop_info.keyboard_type.value.upper()} • 100 KEYS")
                if self._lbl_aux_badge:
                    if laptop_info.has_rear_lightbar:
                        aux_text = "REAR LIGHTBAR & LOGO //"
                    elif laptop_info.has_lid_logo:
                        aux_text = "PREDATOR LID LOGO //"
                    else:
                        aux_text = "AUX PERIPHERALS // NONE ON MODEL"
                    self._lbl_aux_badge.config(text=aux_text)
                if getattr(self, "_lbl_status_hw", None):
                    self._lbl_status_hw.config(text=f"HARDWARE: {laptop_info.model_name.upper()} ({laptop_info.keyboard_type.value.upper()})")
                self.set_aux_sync_state(self._aux_sync_enabled)
                self._redraw_lightbar_canvas()
                self._draw_full_keyboard()
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

        self._lbl_status_hw = tk.Label(
            left, text=f"HARDWARE: {self.laptop_info.model_name.upper()} ({self.laptop_info.keyboard_type.value.upper()})",
            font=(self.FONT_FAMILY, 6, "bold"), fg=self.TEXT_MUTED, bg=self.SURFACE_PANEL
        )
        self._lbl_status_hw.pack(side="left")

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
        if mode_name in ("Static Album Art", "Static Album Dominant"):
            self._handle_theme_change_direct("Auto (Album Cover)")
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
        b = max(0, min(100, int(float(val))))
        self._current_brightness = b
        if self._lbl_val_bright:
            self._lbl_val_bright.config(text=f"{b}%")
        self._last_rendered_colors = [(-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)]
        if self._suppress_bright_target is not None and b == self._suppress_bright_target:
            self._suppress_bright_target = None
            return
        self._suppress_bright_target = None
        if self.on_brightness_change:
            self.on_brightness_change(b)

    def _clear_bright_suppress(self, expected: int):
        if self._suppress_bright_target == expected:
            self._suppress_bright_target = None

    def set_brightness(self, value: int, notify: bool = False, source: str = "software"):
        """Synchronizes brightness slider, label, and keyboard projection without feedback loops."""
        b = max(0, min(100, int(value)))
        self._current_brightness = b
        if self._lbl_val_bright and self.root and self.root.winfo_exists():
            try:
                self._lbl_val_bright.config(text=f"{b}%")
            except Exception:
                pass
        if self._slider_bright and self.root and self.root.winfo_exists():
            try:
                cur_slider = int(float(self._slider_bright.get()))
                if cur_slider != b:
                    self._suppress_bright_target = b
                    self._slider_bright.set(b)
                    self.root.after_idle(lambda t=b: self._clear_bright_suppress(t))
            except Exception:
                pass
        self._last_rendered_colors = [(-1, -1, -1), (-1, -1, -1), (-1, -1, -1), (-1, -1, -1)]
        if notify and self.on_brightness_change:
            self.on_brightness_change(b)

    def _toggle_physical_brightness_gui(self):
        if not self._physical_brightness_supported:
            return
        new_val = not self._physical_brightness_enabled
        self.set_physical_brightness_enabled(new_val)
        if self.on_toggle_physical_brightness:
            self.on_toggle_physical_brightness(new_val)

    def set_physical_brightness_enabled(self, enabled: bool):
        self._physical_brightness_enabled = bool(enabled)
        if self._btn_phys_bright and self.root and self.root.winfo_exists():
            phys_active = self._physical_brightness_supported and self._physical_brightness_enabled
            phys_text = "EC SYNC: ON" if phys_active else ("EC SYNC: OFF" if self._physical_brightness_supported else "SW SCALE")
            try:
                self._btn_phys_bright.config(
                    text=phys_text,
                    bg="#1E1800" if phys_active else "#161616",
                    fg=self.ACCENT_YELLOW if phys_active else self.TEXT_MUTED,
                    highlightbackground=self.ACCENT_YELLOW if phys_active else self.BORDER_HAIRLINE,
                )
            except Exception:
                pass

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

    def update_hardware_connection(self, is_connected: bool):
        """Dynamically updates the header hardware status badge when connection state changes."""
        self.is_hardware_connected = is_connected
        if not hasattr(self, '_lbl_hw_status') or not self._lbl_hw_status:
            return
        if "Virtual" in self.controller_name:
            hw_color = self.TEXT_MUTED
            hw_text = "● VIRTUAL CONTROLLER [EMULATION]"
            self._lbl_hw_status.config(cursor="")
        elif is_connected:
            hw_color = self.ACCENT_YELLOW
            hw_text = f"● {self.controller_name.upper()} [CONNECTED]"
            self._lbl_hw_status.config(cursor="")
        else:
            hw_color = self.ACCENT_WARN
            hw_text = f"⚠ {self.controller_name.upper()} [SERVICE STOPPED - CLICK TO START]"
            self._lbl_hw_status.config(cursor="hand2")
        self._lbl_hw_status.config(text=hw_text, fg=hw_color)

    def _trigger_start_hardware_service(self, event=None):
        """Triggers service start helper when user clicks the service stopped warning badge."""
        if self.is_hardware_connected:
            return
        if self.on_start_hardware_service:
            self.on_start_hardware_service()
        else:
            try:
                from ..hardware.acer_pipe_windows import AcerLightingNamedPipeBackend
                AcerLightingNamedPipeBackend.start_service_elevated()
            except Exception:
                pass

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
                self._power_poll_tick += 1
                if self._power_poll_tick >= 90:
                    self._power_poll_tick = 0
                    self._poll_system_power()
                self._after_id = self.root.after(16, self._schedule_gui_update)
            except Exception:
                pass
        else:
            self._after_id = None

    def update_power_status(self, is_plugged, is_saver_active: bool = False, battery_pct: int = 100):
        """Updates live power badge in header, battery saver banner, and power state."""
        if hasattr(is_plugged, "is_plugged_in"):
            status = is_plugged
            is_plugged = status.is_plugged_in
            is_saver_active = status.is_battery_saver
            battery_pct = status.battery_percent

        self._is_plugged_in = bool(is_plugged)
        self._is_battery_saver_active = bool(is_saver_active)
        self._battery_percent = int(battery_pct)

        if not (self.root and self.root.winfo_exists()):
            return

        try:
            # 1. Update Header Power Badge
            if self._lbl_power_status:
                if is_saver_active:
                    self._lbl_power_status.config(
                        text="🌙 BATTERY SAVER (SUSPENDED)",
                        fg=self.ACCENT_SAVER
                    )
                elif not is_plugged:
                    pct_str = f" ({battery_pct}%)" if battery_pct >= 0 else ""
                    self._lbl_power_status.config(
                        text=f"🔋 ON BATTERY{pct_str}",
                        fg=self.ACCENT_AMBER
                    )
                else:
                    self._lbl_power_status.config(
                        text="⚡ PLUGGED IN",
                        fg=self.ACCENT_GREEN
                    )

            # 2. Update Battery Saver Notification Banner
            if self._banner_saver and self._canvas_kb:
                if is_saver_active and self._is_battery_saver_disable:
                    if not self._banner_saver.winfo_ismapped():
                        self._banner_saver.pack(fill="x", padx=8, pady=(2, 2), before=self._canvas_kb)
                else:
                    if self._banner_saver.winfo_ismapped():
                        self._banner_saver.pack_forget()
        except Exception:
            pass

    def _poll_system_power(self):
        """Zero-overhead Win32 power poll to keep badge and banner fresh even if callbacks are detached."""
        try:
            from ..utils.power import SYSTEM_POWER_STATUS
            if sys.platform == "win32":
                sps = SYSTEM_POWER_STATUS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                    plugged = sps.ACLineStatus != 0
                    saver = sps.SystemStatusFlag == 1
                    pct = int(sps.BatteryLifePercent) if sps.BatteryLifePercent <= 100 else 100
                    self.update_power_status(plugged, saver, pct)
        except Exception:
            pass

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
                        with Image.open(track.cover_path) as raw_img:
                            img = raw_img.resize((56, 56), Image.Resampling.LANCZOS)
                            self._cover_img_tk = ImageTk.PhotoImage(img)
                            self._lbl_cover.config(image=self._cover_img_tk, text="")
                    except Exception:
                        self._lbl_cover.config(image="", text="♫")
                else:
                    self._lbl_cover.config(image="", text="♫")

        # 2. Update Full Realistic Keyboard Graphic & Live Keycap Illumination
        if colors and len(colors) == 4 and self._canvas_kb:
            # Apply real hardware brightness & lighting-active scaling so projection matches physical output
            bright_scale = (self._current_brightness / 100.0) if self._is_lighting_active else 0.0
            effective_colors = [_scale_rgb_brightness(c, bright_scale) for c in colors]

            # Check if effective colors actually changed before costly Tkinter itemconfig calls
            colors_changed = any(c != l for c, l in zip(effective_colors, self._last_rendered_colors))
            if colors_changed:
                self._last_rendered_colors = list(effective_colors)
                kb_type = self.laptop_info.keyboard_type
                is_static = self._current_mode in ("Static Album Art", "Static Album Dominant")
                is_beat_now = bool(state and getattr(state, "is_beat", False) and not is_static and bright_scale > 0.0)

                for z in range(4):
                    r, g, b = effective_colors[z]
                    hex_c = f"#{r:02x}{g:02x}{b:02x}"

                    if z < len(self._kb_hex_labels):
                        self._kb_hex_labels[z].config(text=hex_c.upper())

                    # Update zone status LED dot canvas safely
                    if z < len(self._kb_dots):
                        dot_c, dot_id = self._kb_dots[z]
                        dot_c.itemconfig(dot_id, fill=hex_c)

                # Soft underglow backdrop matched to hardware zone topology
                if kb_type == KeyboardType.ONE_ZONE_RGB:
                    unified = map_4zone_to_n(effective_colors, 1)[0]
                    if self._kb_zone_backs:
                        self._canvas_kb.itemconfig(self._kb_zone_backs[0], fill=_blend_over_base((8, 8, 8), unified, 0.18))
                elif kb_type == KeyboardType.THREE_ZONE_RGB:
                    mapped_3 = map_4zone_to_n(effective_colors, 3)
                    for z in range(min(3, len(self._kb_zone_backs))):
                        self._canvas_kb.itemconfig(self._kb_zone_backs[z], fill=_blend_over_base((8, 8, 8), mapped_3[z], 0.18))
                elif kb_type == KeyboardType.PER_KEY_RGB:
                    n_backs = len(self._kb_zone_backs)
                    if n_backs > 0:
                        denom = float(max(1, n_backs - 1))
                        for s_idx, zb in enumerate(self._kb_zone_backs):
                            c_slice = self._smoothstep_per_key_color(effective_colors, s_idx / denom)
                            self._canvas_kb.itemconfig(zb, fill=_blend_over_base((8, 8, 8), c_slice, 0.18))
                else:
                    for z in range(min(4, len(self._kb_zone_backs))):
                        self._canvas_kb.itemconfig(self._kb_zone_backs[z], fill=_blend_over_base((8, 8, 8), effective_colors[z], 0.18))

                # Recolor individual keycaps (adaptive Per-Key, 4-Zone, 3-Zone, or 1-Zone)
                mapped_3_keys = map_4zone_to_n(effective_colors, 3) if kb_type == KeyboardType.THREE_ZONE_RGB else None
                unified_1_key = map_4zone_to_n(effective_colors, 1)[0] if kb_type == KeyboardType.ONE_ZONE_RGB else None
                wasd_set = set(self._kb_key_wasd)
                arr_set = set(self._kb_key_arrows)
                pred_set = set(self._kb_key_predator)

                for idx in range(len(self._kb_key_rects)):
                    k_rect = self._kb_key_rects[idx]
                    z = self._kb_key_zones[idx]
                    is_wasd = k_rect in wasd_set
                    is_arr = k_rect in arr_set
                    is_pred = k_rect in pred_set
                    norm_x = self._kb_key_norm_x[idx] if idx < len(self._kb_key_norm_x) else 0.5

                    # Determine target keycap color matching real hardware driver mapping
                    if kb_type == KeyboardType.PER_KEY_RGB:
                        key_c = self._smoothstep_per_key_color(effective_colors, norm_x)
                    elif mapped_3_keys is not None:
                        z3 = 0 if norm_x < (1.0 / 3.0) else (1 if norm_x < (2.0 / 3.0) else 2)
                        key_c = mapped_3_keys[z3]
                    elif unified_1_key is not None:
                        key_c = unified_1_key
                    else:
                        key_c = effective_colors[z]

                    base_rgb = (20, 20, 20) if (is_wasd or is_arr) else (15, 15, 15)
                    factor = 0.60 if (is_wasd or is_arr) else 0.32
                    k_fill = _blend_over_base(base_rgb, key_c, factor)

                    if is_wasd or is_arr:
                        k_out = "#FFFFFF"
                    elif sum(key_c) > 20:
                        k_out = f"#{key_c[0]:02x}{key_c[1]:02x}{key_c[2]:02x}"
                    elif is_pred:
                        k_out = self.ACCENT_YELLOW
                    else:
                        k_out = self.BORDER_HAIRLINE

                    self._canvas_kb.itemconfig(k_rect, fill=k_fill, outline=k_out)

                    if idx < len(self._kb_key_texts):
                        t_id = self._kb_key_texts[idx]
                        if is_wasd or is_arr:
                            t_fill = self.ACCENT_YELLOW
                        elif sum(key_c) > 45:
                            # Subtle translucent backlit keycap legend tint
                            t_fill = _blend_over_base((165, 165, 165), key_c, 0.35)
                        elif is_pred:
                            t_fill = self.ACCENT_YELLOW
                        else:
                            t_fill = self.TEXT_SECONDARY
                        self._canvas_kb.itemconfig(t_id, fill=t_fill)

                # Recolor Auxiliary Device lightbar strip matching map_auxiliary_device_colors
                if self._canvas_lightbar and self._lightbar_segs:
                    has_aux = bool(self.laptop_info.has_rear_lightbar or self.laptop_info.has_lid_logo)
                    if has_aux and self._aux_sync_enabled and any(sum(c) > 0 for c in effective_colors):
                        aux_leds = map_auxiliary_device_colors(
                            effective_colors,
                            len(self._lightbar_segs),
                            is_beat=is_beat_now
                        )
                        for s_idx, seg_id in enumerate(self._lightbar_segs):
                            c_aux = aux_leds[s_idx] if s_idx < len(aux_leds) else effective_colors[1]
                            self._canvas_lightbar.itemconfig(seg_id, fill=_dim_color(c_aux, 0.90))
                    else:
                        for seg_id in self._lightbar_segs:
                            self._canvas_lightbar.itemconfig(seg_id, fill="#101010")

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
