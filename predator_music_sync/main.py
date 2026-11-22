"""
Predator Keyboard Music Sync - Full Desktop Application & Background Service
Corsair iCUE-inspired industrial interface with Windows System Tray integration
and persistent 24/7 background lighting service.
"""

import os
import sys
import time
import json
import ctypes
import threading
from typing import Optional, List, Tuple, Dict

# Ensure package directory is on sys.path for direct execution
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from predator_music_sync.service.sync_service import PredatorSyncService
from predator_music_sync.tray.tray_manager import PredatorTrayManager
from predator_music_sync.gui.toolbar import PredatorMusicToolbar
from predator_music_sync.core.media_engine import MediaTrackInfo
from predator_music_sync.core.audio_engine import AudioBeatState
from predator_music_sync.core.color_extractor import RGBColor
from predator_music_sync.utils.autostart import is_autostart_enabled, set_autostart


class PredatorMusicSyncApp:
    """
    Master Application Coordinator:
    - Dedicated 60 FPS Background Service (audio loopback, SMTC media, hardware pipe)
    - Persistent Windows System Tray Icon & Quick Context Menu
    - Full-fledged Corsair iCUE-inspired Dashboard that hides to tray on close
    """

    def __init__(self, target_fps: int = 60, prefer_virtual: bool = False, start_minimized: bool = False):
        self.start_minimized = start_minimized

        # 1. Initialize dedicated background sync service
        self.service = PredatorSyncService(
            target_fps=target_fps,
            prefer_virtual=prefer_virtual
        )

        # Enumerate available audio input devices for GUI combobox
        audio_devs: List[Tuple[int, str]] = []
        if hasattr(self.service.audio_engine, "get_available_input_devices"):
            for dev in self.service.audio_engine.get_available_input_devices():
                idx = dev[0]
                name = f"{dev[1]} ({dev[2]})" if len(dev) > 2 else dev[1]
                audio_devs.append((idx, name))

        # 2. Initialize GUI Desktop Toolbar
        self.gui = PredatorMusicToolbar(
            on_mode_change=self.set_animation_mode,
            on_sensitivity_change=self.service.set_sensitivity,
            on_brightness_change=self.service.set_brightness,
            on_speed_change=self.service.set_speed,
            on_flash_change=self.service.set_flash,
            on_theme_change=self.service.set_theme,
            on_audio_device_change=self.service.set_audio_device,
            on_toggle_lighting=self.toggle_lighting,
            on_zone_override_change=self.service.set_zone_override,
            on_band_gain_change=self.service.set_band_gains,
            on_silence_threshold_change=self.service.set_silence_threshold,
            on_save_profile=self.save_profile,
            on_load_profile=self.load_profile,
            on_load_preset=self.service.load_preset,
            on_window_hide=self._on_window_hidden_to_tray,
            on_toggle_autostart=self.toggle_autostart,
            controller_name=self.service.controller_name,
            is_hardware_connected=self.service.is_hw,
            audio_devices=audio_devs,
            selected_device_index=self.service.audio_engine.device_index,
            initial_mode=self.service.active_animation_name,
            initial_theme="Auto (Album Cover)",
            initial_brightness=self.service.controller.brightness,
            initial_sensitivity=self.service.audio_engine.sensitivity,
            initial_speed=self.service._current_speed,
            initial_flash=self.service._current_flash
        )

        # 3. Initialize Windows System Tray Icon
        hw_status_str = f"{self.service.controller_name} [CONNECTED]" if self.service.is_hw else f"{self.service.controller_name} [EMULATION]"
        self.tray = PredatorTrayManager(
            on_show_window=self.restore_window,
            on_hide_window=self.hide_window,
            on_toggle_lighting=self.toggle_lighting,
            on_set_mode=self.set_animation_mode,
            on_exit_app=self.exit_completely,
            on_toggle_autostart=self.toggle_autostart,
            initial_lighting_active=self.service._lighting_enabled,
            initial_mode=self.service.active_animation_name,
            hardware_status_text=hw_status_str
        )

        # 4. Connect Service State Stream to GUI Visualizer
        self.service.add_state_listener(self._on_service_state_tick)

    def _on_service_state_tick(self, colors: List[RGBColor], track: Optional[MediaTrackInfo], state: Optional[AudioBeatState]):
        """Transfers live 60 FPS service data to GUI buffers."""
        if self.gui:
            self.gui.update_zone_colors(colors)
            if track:
                self.gui.update_track_info(track)
            if state:
                self.gui.update_audio_state(state)

    def _on_window_hidden_to_tray(self):
        """Called when user closes the window with the 'X' button or 'Hide to Tray' button."""
        self.tray.notify_minimized_to_tray()

    def restore_window(self):
        """Restores and brings the GUI window to the foreground."""
        if self.gui and self.gui.root:
            self.gui.root.after(0, self.gui.restore_from_tray)

    def hide_window(self):
        """Hides the GUI window to the system tray."""
        if self.gui and self.gui.root:
            self.gui.root.after(0, self.gui.hide_to_tray)

    def set_animation_mode(self, mode_name: str):
        self.service.set_animation_mode(mode_name)
        self.tray.update_mode(mode_name)
        if self.gui and self.gui.root:
            self.gui.root.after(0, lambda: self.gui.set_mode(mode_name, notify=False))

    def toggle_lighting(self, enabled: bool):
        self.service.toggle_lighting(enabled)
        self.tray.update_lighting_state(enabled)
        if self.gui and self.gui.root:
            self.gui.root.after(0, lambda: self.gui.set_lighting_active(enabled, notify=False))

    def toggle_autostart(self, enabled: bool):
        set_autostart(enabled)
        if self.tray:
            self.tray.update_autostart_state()
        if self.gui and self.gui.root:
            self.gui.root.after(0, lambda: self.gui.set_autostart_state(enabled))

    def save_profile(self, name: str, filepath: Optional[str] = None) -> str:
        if filepath is None:
            profiles_dir = os.path.join(parent_dir, "profiles")
            os.makedirs(profiles_dir, exist_ok=True)
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip() or "profile"
            filepath = os.path.join(profiles_dir, f"{safe_name}.json")

        profile_data = {
            "name": name,
            "animation_mode": self.service.active_animation_name,
            "speed": self.service._current_speed,
            "flash": self.service._current_flash,
            "brightness": self.service.controller.brightness,
            "sensitivity": self.service.audio_engine.sensitivity,
            "silence_threshold": self.service.audio_engine.silence_threshold,
            "band_gains": [float(g) for g in self.service.audio_engine.band_gains],
            "theme_name": self.service._manual_theme_name or "Auto (Album Cover)",
            "zone_overrides": {str(k): list(v) if v else None for k, v in self.service.zone_overrides.items()},
            "lighting_enabled": self.service._lighting_enabled
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, indent=2)
        print(f"Saved profile '{name}' to {filepath}", flush=True)
        return filepath

    def load_profile(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "animation_mode" in data:
                self.set_animation_mode(data["animation_mode"])
            elif "mode" in data:
                self.set_animation_mode(data["mode"])
            if "speed" in data:
                self.service.set_speed(float(data["speed"]))
            if "flash" in data:
                self.service.set_flash(float(data["flash"]))
            if "brightness" in data:
                self.service.set_brightness(int(data["brightness"]))
            if "sensitivity" in data:
                self.service.set_sensitivity(float(data["sensitivity"]))
            if "silence_threshold" in data:
                self.service.set_silence_threshold(float(data["silence_threshold"]))
            if "band_gains" in data:
                self.service.set_band_gains(tuple(data["band_gains"]))
            if "theme_name" in data:
                self.service.set_theme(data["theme_name"])
            elif "theme" in data:
                self.service.set_theme(data["theme"])
            if "zone_overrides" in data:
                for k, v in data["zone_overrides"].items():
                    self.service.set_zone_override(int(k), tuple(v) if v else None)
            if "lighting_enabled" in data:
                self.toggle_lighting(bool(data["lighting_enabled"]))
            print(f"Loaded profile from {filepath}", flush=True)
            return True
        except Exception as e:
            print(f"Error loading profile {filepath}: {e}", flush=True)
            return False

    def exit_completely(self):
        """Cleanly terminates the background service, system tray, and GUI."""
        if getattr(self, "_is_exiting", False):
            return
        self._is_exiting = True
        print("Shutting down Predator Sync Application completely...", flush=True)
        self.service.stop()
        self.tray.stop()
        if self.gui and self.gui.root:
            try:
                self.gui.root.after(0, self.gui.exit_application)
            except Exception:
                pass

    def start(self):
        """Starts background service, tray icon, and launches GUI."""
        # 1. Start background service
        self.service.start()

        # 2. Start Windows System Tray Icon
        self.tray.start()

        # 3. Create GUI Window
        self.gui.create_window()

        if self.start_minimized:
            self.gui.root.withdraw()
            self.gui._is_gui_active = False
            self.tray.notify_minimized_to_tray()

        # 4. Run GUI Mainloop on Main Thread
        try:
            if self.gui.root:
                self.gui.root.mainloop()
        finally:
            self.exit_completely()


def _init_windows_dpi():
    """Initializes Windows Per-Monitor V2 DPI awareness for ultra-crisp UI rendering."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass


# Modern Alias
MusicalPredatorApp = PredatorMusicSyncApp


def main():
    _init_windows_dpi()
    prefer_virtual = "--virtual" in sys.argv or "-v" in sys.argv
    start_minimized = "--minimized" in sys.argv or "--tray" in sys.argv
    app = PredatorMusicSyncApp(prefer_virtual=prefer_virtual, start_minimized=start_minimized)
    app.start()


if __name__ == "__main__":
    main()
