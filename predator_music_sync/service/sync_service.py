"""
PredatorSyncService - Dedicated Background Lighting & Audio Sync Service
Runs independently of the GUI window.
Controls audio capture, Windows media session extraction, 4-zone beat algorithms,
and direct Acer physical hardware pipe dispatch at 60 FPS.
"""

import os
import sys
import time
import json
import ctypes
import threading
from typing import Optional, List, Tuple, Dict, Callable, Any

from ..core.audio_engine import AudioBeatSyncEngine, AudioBeatState
from ..core.media_engine import MediaSessionEngine, MediaTrackInfo
from ..core.color_extractor import ColorPaletteExtractor, ColorPalette, RGBColor
from ..core.animations import ANIMATION_REGISTRY, BaseAnimation, SpectrumEqualizer
from ..hardware.factory import get_keyboard_controller
from ..hardware.base import KeyboardControllerBase
from ..utils.power import PowerMonitor, PowerStatus, set_process_power_throttling


class PredatorSyncService:
    """
    Dedicated background service engine for Predator 4-Zone RGB Sync.
    Runs persistently in the background whether GUI is open, minimized, or hidden in tray.
    """

    PRESETS: Dict[str, Dict] = {
        "Static Album Cover": {
            "mode": "Static Album Art",
            "speed": 1.0,
            "flash": 0.0,
            "sensitivity": 1.0,
            "silence_threshold": 0.001,
            "band_gains": [1.0, 1.0, 1.0, 1.0],
            "theme": "Auto (Album Cover)"
        },
        "Bass Heavy EDM": {
            "mode": "Dynamic Studio EQ",
            "speed": 1.3,
            "flash": 0.40,
            "sensitivity": 1.35,
            "silence_threshold": 0.001,
            "band_gains": [2.2, 1.3, 0.9, 0.8],
            "theme": "Predator Cyan"
        },
        "Chill Lo-Fi": {
            "mode": "Lush Chroma Aurora",
            "speed": 0.7,
            "flash": 0.05,
            "sensitivity": 1.0,
            "silence_threshold": 0.001,
            "band_gains": [1.1, 1.0, 1.0, 0.7],
            "theme": "Sunset Lo-Fi"
        },
        "Chill Lo-Fi / Ambient": {
            "mode": "Lush Chroma Aurora",
            "speed": 0.7,
            "flash": 0.05,
            "sensitivity": 1.0,
            "silence_threshold": 0.001,
            "band_gains": [1.1, 1.0, 1.0, 0.7],
            "theme": "Sunset Lo-Fi"
        },
        "Competitive Gaming WASD": {
            "mode": "Dynamic Studio EQ",
            "speed": 1.0,
            "flash": 0.20,
            "sensitivity": 1.15,
            "silence_threshold": 0.001,
            "band_gains": [1.0, 1.0, 1.0, 1.0],
            "theme": "Auto (Album Cover)",
            "zone_overrides": {0: (255, 0, 0)}
        },
        "Cyberpunk Synthwave": {
            "mode": "Neon Cyber Wave",
            "speed": 1.1,
            "flash": 0.25,
            "sensitivity": 1.2,
            "silence_threshold": 0.001,
            "band_gains": [1.4, 1.1, 1.1, 1.0],
            "theme": "Cyberpunk Neon"
        },
        "Vocal Acoustic": {
            "mode": "Dynamic Studio EQ",
            "speed": 1.0,
            "flash": 0.15,
            "sensitivity": 1.1,
            "silence_threshold": 0.001,
            "band_gains": [0.8, 1.2, 1.8, 1.2],
            "theme": "Auto (Album Cover)"
        },
        "Vocal & Acoustic": {
            "mode": "Dynamic Studio EQ",
            "speed": 1.0,
            "flash": 0.15,
            "sensitivity": 1.1,
            "silence_threshold": 0.001,
            "band_gains": [0.8, 1.2, 1.8, 1.2],
            "theme": "Auto (Album Cover)"
        }
    }

    def __init__(self, target_fps: int = 60, prefer_virtual: bool = False):
        self.target_fps = target_fps
        self._frame_time = 1.0 / target_fps
        self._is_running = False
        self._render_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._device_switch_lock = threading.Lock()

        # Engine tuning parameters
        self._current_speed: float = 1.0
        self._current_flash: float = 0.20
        self._manual_theme_name: Optional[str] = None
        self._lighting_enabled: bool = True

        # Per-zone overrides {zone: Optional[RGBColor]}
        self.zone_overrides: Dict[int, Optional[RGBColor]] = {0: None, 1: None, 2: None, 3: None}

        # Core subsystems
        self.audio_engine = AudioBeatSyncEngine()
        self.media_engine = MediaSessionEngine(poll_interval=1.5)
        self.color_extractor = ColorPaletteExtractor()
        self.current_palette: ColorPalette = ColorPaletteExtractor.DEFAULT_PALETTES[0]

        # Active animation
        self.active_animation_name = SpectrumEqualizer.name
        self.animation: BaseAnimation = ANIMATION_REGISTRY[self.active_animation_name]()
        self.animation.speed = self._current_speed
        self.animation.flash_intensity = self._current_flash

        # Hardware controller
        self.controller: KeyboardControllerBase = get_keyboard_controller(
            prefer_virtual=prefer_virtual
        )
        self.is_hw = "Virtual" not in self.controller.__class__.__name__
        from ..hardware.device_detector import detect_laptop_model
        self.laptop_info = getattr(self.controller, "model_info", None) or detect_laptop_model()
        self.controller_name = self.laptop_info.display_name if self.is_hw else "Virtual Controller"

        # State cache for UI listeners
        self._latest_colors: List[RGBColor] = [(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)]
        self._latest_track: Optional[MediaTrackInfo] = None
        self._latest_audio_state: Optional[AudioBeatState] = None

        # Callbacks for UI updates
        self._state_listeners: List[Callable[[List[RGBColor], Optional[MediaTrackInfo], Optional[AudioBeatState]], None]] = []

        # =====================================================================
        # POWER & BATTERY SUBSYSTEM (Dual Power Profiles & Battery Saver)
        # =====================================================================
        self.auto_power_switching_enabled: bool = True
        self.battery_saver_disable_enabled: bool = True
        self.battery_brightness_cap: int = 50

        # Dual power profiles
        self.ac_profile: Dict[str, Any] = {
            "mode": "Dynamic Studio EQ",
            "fps": 60,
            "brightness": 100,
            "speed": 1.0,
            "flash": 0.20
        }
        self.battery_profile: Dict[str, Any] = {
            "mode": "Static Album Art",
            "fps": 30,
            "brightness": 50,
            "speed": 0.8,
            "flash": 0.0
        }

        self._is_power_suspended: bool = False
        self._resume_resync_pending: bool = False
        self._power_listeners: List[Callable[[PowerStatus], None]] = []

        self.power_monitor = PowerMonitor(
            poll_interval=1.5,
            on_ac_power_change=self._on_ac_power_changed,
            on_battery_saver_change=self._on_battery_saver_changed,
            on_battery_percent_change=self._on_battery_percent_changed,
            on_system_resume=self._on_system_resume,
        )
        init_status = self.power_monitor.get_status()
        self._is_plugged_in: bool = init_status.is_plugged_in
        self._is_battery_saver: bool = init_status.is_battery_saver
        self._battery_percent: int = init_status.battery_percent

        self.media_engine.add_track_change_callback(self._on_track_changed)

    def _on_track_changed(self, track: MediaTrackInfo):
        with self._lock:
            self._latest_track = track
            if self._manual_theme_name is None or self._manual_theme_name == "Auto (Album Cover)":
                if track and track.cover_path and os.path.exists(track.cover_path) and os.path.getsize(track.cover_path) > 0:
                    new_palette = self.color_extractor.extract_from_image_path(track.cover_path)
                    if new_palette:
                        self.current_palette = new_palette
                elif self.current_palette is None:
                    # Only fallback on cold start before any palette exists
                    self.current_palette = ColorPaletteExtractor.DEFAULT_PALETTES[0]

    def start(self):
        """Starts background audio capture, media monitoring, and the 60 FPS hardware loop."""
        if self._is_running:
            return
        self._is_running = True

        # Optimize Windows timer resolution and opt out of EcoQoS background throttling
        # when minimized/closed to tray so 60 FPS background sync does not starve.
        if sys.platform == "win32":
            set_process_power_throttling(True)
            try:
                ctypes.windll.winmm.timeBeginPeriod(1)
            except Exception:
                pass

        self.audio_engine.start()
        self.media_engine.start_monitoring()
        self.power_monitor.start()

        initial_track = self.media_engine.get_current_media_track()
        if initial_track:
            self._on_track_changed(initial_track)

        self._render_thread = threading.Thread(target=self._service_loop, daemon=True, name="PredatorSyncServiceLoop")
        self._render_thread.start()
        print(f"PredatorSyncService started [Hardware: {self.controller_name}]", flush=True)

    def stop(self):
        """Clean shutdown of service, audio capture, and keyboard controller."""
        self._is_running = False
        if self._render_thread and self._render_thread.is_alive():
            if threading.current_thread() != self._render_thread:
                self._render_thread.join(timeout=0.5)

        self.power_monitor.stop()
        self.audio_engine.stop()
        self.media_engine.stop_monitoring()
        try:
            if hasattr(self.controller, 'set_all_zones') and 'sync' in self.controller.set_all_zones.__code__.co_varnames:
                self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)], sync=True)
            else:
                self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)])
        except Exception:
            pass
        self.controller.close()

        # Restore Windows timer resolution and default power throttling
        if sys.platform == "win32":
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
            set_process_power_throttling(False)

        print("PredatorSyncService stopped cleanly.", flush=True)

    @property
    def is_hardware_connected(self) -> bool:
        """Returns True if the controller is connected to physical hardware."""
        return bool(self.controller and getattr(self.controller, "is_connected", False))

    def add_state_listener(self, listener: Callable[[List[RGBColor], Optional[MediaTrackInfo], Optional[AudioBeatState]], None]):
        """Registers a listener callback that receives live 60 FPS engine state for GUI rendering."""
        with self._lock:
            if listener not in self._state_listeners:
                self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable):
        with self._lock:
            if listener in self._state_listeners:
                self._state_listeners.remove(listener)

    def _service_loop(self):
        last_time = time.perf_counter()
        last_dispatch_time = 0.0
        last_dispatched_colors: Optional[List[RGBColor]] = None

        while self._is_running:
            if self._is_power_suspended:
                # Battery Saver active: LEDs remain off, loop sleeps at 0.5s (~0.0% CPU)
                time.sleep(0.5)
                last_time = time.perf_counter()
                continue

            t0 = time.perf_counter()
            raw_dt = t0 - last_time
            last_time = t0
            if raw_dt > 2.0:
                self._on_system_resume()
            dt = max(0.0, min(0.1, raw_dt))

            # 1. Capture current audio beat state
            audio_state = self.audio_engine.get_state()

            # 2. Compute 4-zone colors
            with self._lock:
                if self._resume_resync_pending:
                    self._resume_resync_pending = False
                    last_dispatched_colors = None

                if self._lighting_enabled:
                    zone_colors = list(self.animation.update(audio_state, self.current_palette, dt))
                    for z, override_color in self.zone_overrides.items():
                        if override_color is not None and 0 <= z < len(zone_colors):
                            zone_colors[z] = override_color
                else:
                    zone_colors = [(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)]

                self._latest_colors = list(zone_colors)
                self._latest_audio_state = audio_state
                track = self._latest_track
                listeners = list(self._state_listeners)
                is_static = (self.active_animation_name in ("Static Album Art", "Static Album Dominant")) or (not self._lighting_enabled)

            is_silent = (audio_state.overall_energy < 0.05 or getattr(audio_state, "is_silent", False))
            colors_unchanged = (last_dispatched_colors is not None and zone_colors == last_dispatched_colors)

            # In static modes, beats must NEVER trigger beat-latching, white flashes, or strobe overrides
            effective_is_beat = False if is_static else audio_state.is_beat

            # 3. Hardware dispatch:
            # In static modes, dispatch ONLY when colors actually change (new track, album art, or preset).
            # Suppress all redundant keep-alive writes so physical LEDs remain 100% solid, steady, with zero flickering or blinking.
            # In dynamic modes, dispatch on color changes, musical beats, or idle keepalive.
            time_since_dispatch = t0 - last_dispatch_time
            if is_static:
                should_dispatch = not colors_unchanged
            else:
                should_dispatch = (not colors_unchanged) or effective_is_beat or (time_since_dispatch >= 0.45)

            if should_dispatch:
                try:
                    self.controller.set_all_zones(zone_colors, is_beat=effective_is_beat, is_static=is_static)
                    last_dispatched_colors = list(zone_colors)
                    last_dispatch_time = t0
                except TypeError:
                    try:
                        self.controller.set_all_zones(zone_colors, is_beat=effective_is_beat)
                        last_dispatched_colors = list(zone_colors)
                        last_dispatch_time = t0
                    except TypeError:
                        try:
                            self.controller.set_all_zones(zone_colors)
                            last_dispatched_colors = list(zone_colors)
                            last_dispatch_time = t0
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    pass

            # 4. Notify GUI listeners
            for listener in listeners:
                try:
                    listener(zone_colors, track, audio_state)
                except Exception:
                    pass

            # 5. Adaptive Pacing:
            # Static modes run at steady 15 FPS (zero CPU).
            # Dynamic modes throttle to 15 FPS during silence, and run at 60 FPS during audio playback.
            if is_static:
                target_frame_time = 1.0 / 15.0  # 15 FPS steady for static mode
            elif is_silent and not audio_state.is_beat:
                target_frame_time = 1.0 / 15.0  # 15 FPS during silence
            else:
                target_frame_time = self._frame_time  # 60 FPS

            elapsed = time.perf_counter() - t0
            sleep_time = max(0.001, target_frame_time - elapsed)
            time.sleep(sleep_time)

    # =========================================================================
    # PARAMETER SETTERS (Thread-Safe)
    # =========================================================================
    def set_animation_mode(self, mode_name: str):
        with self._lock:
            if mode_name in ANIMATION_REGISTRY:
                self.active_animation_name = mode_name
                self.animation = ANIMATION_REGISTRY[mode_name]()
                self.animation.speed = self._current_speed
                self.animation.flash_intensity = self._current_flash
                if mode_name in ("Static Album Art", "Static Album Dominant"):
                    # Immediately ensure palette is loaded from current track if available
                    if self._latest_track and self._latest_track.cover_path and os.path.exists(self._latest_track.cover_path):
                        self.current_palette = self.color_extractor.extract_from_image_path(self._latest_track.cover_path)

    def set_speed(self, val: float):
        with self._lock:
            self._current_speed = max(0.2, min(3.0, val))
            if self.animation:
                self.animation.speed = self._current_speed

    def set_flash(self, val: float):
        with self._lock:
            self._current_flash = max(0.0, min(1.0, val))
            if self.animation:
                self.animation.flash_intensity = self._current_flash

    def set_theme(self, theme_name: str):
        with self._lock:
            self._manual_theme_name = theme_name
            if theme_name in ColorPaletteExtractor.PRESET_THEMES:
                preset = ColorPaletteExtractor.PRESET_THEMES[theme_name]
                if preset is not None:
                    self.current_palette = preset
                else:
                    if self._latest_track and self._latest_track.cover_path and os.path.exists(self._latest_track.cover_path):
                        self.current_palette = self.color_extractor.extract_from_image_path(self._latest_track.cover_path)
                    else:
                        cur_track = self.media_engine.get_current_media_track()
                        if cur_track and cur_track.cover_path and os.path.exists(cur_track.cover_path):
                            self._latest_track = cur_track
                            self.current_palette = self.color_extractor.extract_from_image_path(cur_track.cover_path)
                        elif self.current_palette is None:
                            self.current_palette = ColorPaletteExtractor.DEFAULT_PALETTES[0]

    def set_brightness(self, val: int):
        self.controller.brightness = int(val)

    def set_sensitivity(self, val: float):
        self.audio_engine.sensitivity = float(val)

    def set_silence_threshold(self, val: float):
        self.audio_engine.silence_threshold = float(val)

    def set_band_gains(self, gains: Tuple[float, float, float, float]):
        self.audio_engine.set_band_gains(list(gains))

    def set_band_gain(self, band_idx: int, gain: float):
        self.audio_engine.set_band_gain(band_idx, gain)

    def set_zone_override(self, zone: int, color: Optional[RGBColor]):
        with self._lock:
            if 0 <= zone < 4:
                self.zone_overrides[zone] = color

    def clear_zone_overrides(self):
        with self._lock:
            self.zone_overrides = {0: None, 1: None, 2: None, 3: None}

    def toggle_lighting(self, enabled: bool):
        with self._lock:
            self._lighting_enabled = enabled
        if not enabled:
            try:
                self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)], is_static=True)
            except TypeError:
                try:
                    self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)])
                except Exception:
                    pass
            except Exception:
                pass

    def load_preset(self, preset_name: str) -> bool:
        if preset_name not in self.PRESETS:
            return False
        p = self.PRESETS[preset_name]
        self.set_animation_mode(p["mode"])
        self.set_speed(p["speed"])
        self.set_flash(p["flash"])
        self.set_sensitivity(p["sensitivity"])
        self.set_silence_threshold(p.get("silence_threshold", 0.001))
        self.set_band_gains(tuple(p.get("band_gains", [1.0, 1.0, 1.0, 1.0])))
        self.set_theme(p.get("theme", "Auto (Album Cover)"))
        self.clear_zone_overrides()
        if "zone_overrides" in p:
            for k, v in p["zone_overrides"].items():
                self.set_zone_override(int(k), tuple(v) if v else None)
        return True

    def set_audio_device(self, device_index: int):
        def _switch():
            with self._device_switch_lock:
                try:
                    if hasattr(self.audio_engine, "set_device"):
                        self.audio_engine.set_device(device_index)
                    else:
                        self.audio_engine.stop()
                        self.audio_engine.device_index = device_index
                        self.audio_engine.start()
                except Exception as e:
                    print(f"Error switching device: {e}", flush=True)

        threading.Thread(target=_switch, daemon=True, name="AudioDeviceSwitchWorker").start()

    # =========================================================================
    # POWER & BATTERY MANAGEMENT SUBSYSTEM
    # =========================================================================
    def get_power_status(self) -> PowerStatus:
        """Returns the current Win32 power status snapshot."""
        return self.power_monitor.get_status()

    def add_power_listener(self, listener: Callable[[PowerStatus], None]):
        """Registers a listener for live power state transitions."""
        with self._lock:
            if listener not in self._power_listeners:
                self._power_listeners.append(listener)

    def remove_power_listener(self, listener: Callable):
        with self._lock:
            if listener in self._power_listeners:
                self._power_listeners.remove(listener)

    def _notify_power_listeners(self, status: PowerStatus):
        with self._lock:
            listeners = list(self._power_listeners)
        for listener in listeners:
            try:
                listener(status)
            except Exception:
                pass

    def set_battery_saver_disable(self, enabled: bool):
        """Enables or disables auto-suspension on Windows Battery Saver."""
        with self._lock:
            self.battery_saver_disable_enabled = bool(enabled)
        # Re-evaluate current state
        status = self.power_monitor.get_status()
        self._on_battery_saver_changed(status.is_battery_saver)

    def set_auto_power_switching(self, enabled: bool):
        """Enables or disables automatic AC vs Battery profile switching."""
        with self._lock:
            self.auto_power_switching_enabled = bool(enabled)
        status = self.power_monitor.get_status()
        self._on_ac_power_changed(status.is_plugged_in)

    def set_battery_brightness_cap(self, cap: int):
        """Sets max brightness cap while on battery power."""
        with self._lock:
            self.battery_brightness_cap = max(0, min(100, int(cap)))
            self.battery_profile["brightness"] = self.battery_brightness_cap
        status = self.power_monitor.get_status()
        if status.is_on_battery and self.auto_power_switching_enabled:
            self.set_brightness(min(self.controller.brightness, self.battery_brightness_cap))

    def set_ac_profile(self, mode: Optional[str] = None, fps: Optional[int] = None, brightness: Optional[int] = None):
        """Configures the plugged-in AC power profile."""
        with self._lock:
            if mode:
                self.ac_profile["mode"] = mode
            if fps:
                self.ac_profile["fps"] = max(15, min(120, int(fps)))
            if brightness is not None:
                self.ac_profile["brightness"] = max(0, min(100, int(brightness)))

    def set_battery_profile(self, mode: Optional[str] = None, fps: Optional[int] = None, brightness: Optional[int] = None):
        """Configures the on-battery eco power profile."""
        with self._lock:
            if mode:
                self.battery_profile["mode"] = mode
            if fps:
                self.battery_profile["fps"] = max(15, min(60, int(fps)))
            if brightness is not None:
                self.battery_brightness_cap = max(0, min(100, int(brightness)))
                self.battery_profile["brightness"] = self.battery_brightness_cap

    def _on_ac_power_changed(self, is_plugged: bool):
        """Fired when switching between AC line and Battery."""
        with self._lock:
            self._is_plugged_in = is_plugged
            status = self.power_monitor.get_status()
            auto_switch = self.auto_power_switching_enabled

        if auto_switch:
            if is_plugged:
                # Plugged in: Restore AC profile & full 60 FPS
                mode = self.ac_profile.get("mode", "Dynamic Studio EQ")
                fps = self.ac_profile.get("fps", 60)
                brightness = self.ac_profile.get("brightness", 100)
                self.set_animation_mode(mode)
                self.set_brightness(brightness)
                with self._lock:
                    self.target_fps = fps
                    self._frame_time = 1.0 / fps
            else:
                # On battery: Switch to eco battery profile & 30 FPS
                mode = self.battery_profile.get("mode", "Static Album Art")
                fps = self.battery_profile.get("fps", 30)
                brightness = min(self.controller.brightness, self.battery_brightness_cap)
                self.set_animation_mode(mode)
                self.set_brightness(brightness)
                with self._lock:
                    self.target_fps = fps
                    self._frame_time = 1.0 / fps

        self._notify_power_listeners(status)

    def _on_battery_saver_changed(self, is_saver_active: bool):
        """Fired when Windows Battery Saver mode toggles."""
        with self._lock:
            self._is_battery_saver = is_saver_active
            status = self.power_monitor.get_status()
            disable_on_saver = self.battery_saver_disable_enabled

        if is_saver_active and disable_on_saver:
            # Suspend lighting and audio capture completely to preserve battery
            with self._lock:
                self._is_power_suspended = True

            # Turn off keyboard LEDs immediately
            try:
                if hasattr(self.controller, 'set_all_zones') and 'sync' in self.controller.set_all_zones.__code__.co_varnames:
                    self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)], sync=True)
                else:
                    self.controller.set_all_zones([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)])
            except Exception:
                pass

            # Pause audio stream & media polling
            self.audio_engine.stop()
            if hasattr(self.media_engine, "pause_monitoring"):
                self.media_engine.pause_monitoring()
            else:
                self.media_engine.stop_monitoring()
        else:
            # Exit Battery Saver: restore audio & lighting
            was_suspended = False
            with self._lock:
                if self._is_power_suspended:
                    self._is_power_suspended = False
                    was_suspended = True

            if was_suspended:
                self.audio_engine.start()
                if hasattr(self.media_engine, "resume_monitoring"):
                    self.media_engine.resume_monitoring()
                else:
                    self.media_engine.start_monitoring()

        self._notify_power_listeners(status)

    def _on_battery_percent_changed(self, pct: int):
        """Fired when battery percentage updates."""
        status = self.power_monitor.get_status()
        self._notify_power_listeners(status)

    def _on_system_resume(self):
        """Recovers audio capture and re-syncs hardware LEDs after Windows sleep/idle."""
        if self._is_power_suspended or not self._is_running:
            return
        with self._lock:
            self._resume_resync_pending = True
        if hasattr(self.audio_engine, "recover_if_stalled"):
            try:
                self.audio_engine.recover_if_stalled()
            except Exception:
                pass
        if hasattr(self.controller, "force_resync"):
            try:
                self.controller.force_resync()
            except Exception:
                pass


# Modern Alias
MusicalPredatorService = PredatorSyncService
