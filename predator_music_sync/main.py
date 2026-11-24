"""
Predator Keyboard Music Sync - Full Desktop Application & Background Service
Corsair iCUE-inspired industrial interface with Windows System Tray integration
and persistent 24/7 background lighting service.
"""

import os
import sys
import time
import json
import queue
import ctypes
import threading
from typing import Optional, List, Tuple, Dict, Callable

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
from predator_music_sync.utils.power import PowerStatus, PowerMonitor
from predator_music_sync.hardware.device_detector import detect_laptop_model, LaptopModelInfo


class PredatorMusicSyncApp:
    """
    Master Application Coordinator:
    - Dedicated 60 FPS Background Service (audio loopback, SMTC media, hardware pipe)
    - Persistent Windows System Tray Icon & Quick Context Menu
    - Full-fledged Corsair iCUE-inspired Dashboard that hides to tray on close
    """

    def __init__(self, target_fps: int = 60, prefer_virtual: bool = False, start_minimized: bool = False):
        self.start_minimized = start_minimized
        self._main_thread_id = threading.get_ident()
        self._gui_dispatch_lock = threading.Lock()
        self._gui_queue: queue.Queue = queue.Queue(maxsize=256)
        self._gui_pump_id: Optional[str] = None
        self._is_exiting = False
        self._last_gui_track_id: Optional[str] = None
        self._last_gui_hw_connected: Optional[bool] = None
        self._last_tray_power_key: Optional[Tuple[bool, bool, int]] = None
        self._latest_power_status: Optional[PowerStatus] = None

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

        # Query detected laptop hardware model
        laptop_info = getattr(self.service, "laptop_info", None) or detect_laptop_model()

        # 2. Initialize GUI Desktop Toolbar
        self.gui = PredatorMusicToolbar(
            on_mode_change=self.set_animation_mode,
            on_sensitivity_change=self.service.set_sensitivity,
            on_brightness_change=self.set_brightness,
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
            on_toggle_battery_saver=self.service.set_battery_saver_disable,
            on_plugged_effect_change=lambda mode: self.service.set_ac_profile(mode=mode),
            on_battery_effect_change=lambda mode: self.service.set_battery_profile(mode=mode),
            on_battery_brightness_cap_change=self.service.set_battery_brightness_cap,
            on_toggle_physical_brightness=self.service.set_physical_brightness_enabled,
            physical_brightness_supported=self.service.is_physical_brightness_supported(),
            initial_physical_brightness_enabled=self.service.is_physical_brightness_enabled(),
            laptop_info=laptop_info,
            controller_name=self.service.controller_name,
            is_hardware_connected=self.service.is_hardware_connected,
            on_start_hardware_service=self.start_hardware_service,
            audio_devices=audio_devs,
            selected_device_index=self.service.audio_engine.device_index,
            initial_mode=self.service.active_animation_name,
            initial_theme="Auto (Album Cover)",
            initial_brightness=self.service.get_brightness(),
            initial_sensitivity=self.service.audio_engine.sensitivity,
            initial_speed=self.service._current_speed,
            initial_flash=self.service._current_flash,
            initial_battery_saver_disable=getattr(self.service, "battery_saver_disable_enabled", True),
            initial_plugged_mode=getattr(self.service, "ac_profile", {}).get("mode", "Dynamic Studio EQ"),
            initial_battery_mode=getattr(self.service, "battery_profile", {}).get("mode", "Static Album Art"),
            initial_battery_brightness_cap=getattr(self.service, "battery_brightness_cap", 50)
        )

        # 3. Initialize Windows System Tray Icon
        model_title = laptop_info.display_name if laptop_info else self.service.controller_name
        hw_status_str = f"{model_title} [CONNECTED]" if self.service.is_hw else f"{model_title} [EMULATION]"
        self.tray = PredatorTrayManager(
            on_show_window=self.restore_window,
            on_hide_window=self.hide_window,
            on_toggle_lighting=self.toggle_lighting,
            on_set_mode=self.set_animation_mode,
            on_exit_app=self.exit_completely,
            on_toggle_autostart=self.toggle_autostart,
            on_set_brightness=self.set_brightness,
            initial_lighting_active=self.service._lighting_enabled,
            initial_mode=self.service.active_animation_name,
            initial_brightness=self.service.get_brightness(),
            hardware_status_text=hw_status_str
        )

        # 4. Connect Service State Stream to GUI Visualizer
        self.service.add_state_listener(self._on_service_state_tick)
        self.service.add_power_listener(self._on_power_state_changed)
        self.service.add_brightness_listener(self._on_brightness_changed)

        # Wire Power Management callbacks to GUI
        self.gui.on_toggle_battery_saver = self.service.set_battery_saver_disable
        self.gui.on_battery_saver_toggle = self.service.set_battery_saver_disable
        self.gui.on_plugged_effect_change = lambda mode: self.service.set_ac_profile(mode=mode)
        self.gui.on_battery_effect_change = lambda mode: self.service.set_battery_profile(mode=mode)
        self.gui.on_battery_brightness_cap_change = self.service.set_battery_brightness_cap
        self.gui.get_power_status = self.service.get_power_status

        # Push initial power state
        init_power = self.service.get_power_status()
        self._on_power_state_changed(init_power)

    def _dispatch_to_gui(self, fn: Callable[[], None]):
        """Thread-safely schedules a GUI callback onto the Tkinter main thread without cross-thread Tcl calls."""
        if self._is_exiting or not self.gui or not self.gui.root:
            return
        if threading.get_ident() == self._main_thread_id:
            try:
                if self.gui.root.winfo_exists():
                    fn()
            except Exception:
                pass
            return
        try:
            self._gui_queue.put_nowait(fn)
        except queue.Full:
            # Drop oldest pending callback to avoid unbounded buildup
            try:
                self._gui_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._gui_queue.put_nowait(fn)
            except queue.Full:
                pass

    def _start_gui_queue_pump(self):
        """Starts the main-thread Tkinter queue poller (safe even when window is withdrawn in tray)."""
        if self._is_exiting or not self.gui or not self.gui.root:
            return
        self._drain_gui_queue()

    def _drain_gui_queue(self):
        """Drains pending cross-thread UI callbacks on the Tkinter main thread."""
        if self._is_exiting or not self.gui or not self.gui.root:
            self._gui_pump_id = None
            return
        root = self.gui.root
        try:
            if not root.winfo_exists():
                self._gui_pump_id = None
                return
        except Exception:
            self._gui_pump_id = None
            return

        for _ in range(32):
            try:
                fn = self._gui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
            if self._is_exiting or not self.gui or not self.gui.root:
                self._gui_pump_id = None
                return

        if not self._is_exiting and self.gui and self.gui.root:
            try:
                if self.gui.root.winfo_exists():
                    self._gui_pump_id = self.gui.root.after(50, self._drain_gui_queue)
            except Exception:
                self._gui_pump_id = None

    def _on_power_state_changed(self, status: PowerStatus):
        """Dispatches power state updates to GUI badge and System Tray."""
        self._latest_power_status = status
        if self.tray:
            power_key = (status.is_plugged_in, status.is_battery_saver, status.battery_percent)
            if power_key != self._last_tray_power_key:
                self._last_tray_power_key = power_key
                if hasattr(self.tray, 'update_power_status'):
                    self.tray.update_power_status(status.is_plugged_in, status.is_battery_saver, status.battery_percent)
                power_desc = f" • {status.status_label}"
                hw_status_str = f"{self.service.controller_name} [CONNECTED]{power_desc}" if self.service.is_hw else f"{self.service.controller_name} [EMULATION]{power_desc}"
                if hasattr(self.tray, 'update_hardware_status'):
                    self.tray.update_hardware_status(hw_status_str)

        if self.gui and hasattr(self.gui, 'update_power_status'):
            if self.gui.root:
                self._dispatch_to_gui(lambda s=status: self.gui.update_power_status(s))
            else:
                try:
                    self.gui.update_power_status(status)
                except Exception:
                    pass

    def start_hardware_service(self):
        """Attempts to start AcerLightingService via Windows UAC elevation."""
        try:
            from predator_music_sync.hardware.acer_pipe_windows import AcerLightingNamedPipeBackend
            return AcerLightingNamedPipeBackend.start_service_elevated()
        except Exception:
            return False

    def _on_service_state_tick(self, colors: List[RGBColor], track: Optional[MediaTrackInfo], state: Optional[AudioBeatState]):
        """Transfers live 60 FPS service data to GUI buffers."""
        if self._is_exiting or not self.gui:
            return
        self.gui.update_zone_colors(colors)
        if track:
            tid = track.track_id
            if tid != self._last_gui_track_id:
                self._last_gui_track_id = tid
                self.gui.update_track_info(track)
        if state:
            self.gui.update_audio_state(state)
        if hasattr(self.service, "is_hardware_connected") and hasattr(self.gui, "update_hardware_connection"):
            is_conn = self.service.is_hardware_connected
            if is_conn != self._last_gui_hw_connected:
                self._last_gui_hw_connected = is_conn
                if self.tray and hasattr(self.tray, "update_hardware_status"):
                    power_desc = f" • {self._latest_power_status.status_label}" if self._latest_power_status else ""
                    if not self.service.is_hw:
                        hw_status_str = f"{self.service.controller_name} [EMULATION]{power_desc}"
                    elif is_conn:
                        hw_status_str = f"{self.service.controller_name} [CONNECTED]{power_desc}"
                    else:
                        hw_status_str = f"{self.service.controller_name} [SERVICE STOPPED]{power_desc}"
                    self.tray.update_hardware_status(hw_status_str)
                self._dispatch_to_gui(lambda c=is_conn: self.gui.update_hardware_connection(c))

    def _on_window_hidden_to_tray(self):
        """Called when user closes the window with the 'X' button or 'Hide to Tray' button."""
        self.tray.notify_minimized_to_tray()

    def _restore_and_sync_gui(self):
        """Restores GUI window and refreshes buffered state after tray hiding."""
        if not self.gui:
            return
        self.gui.restore_from_tray()
        if self._latest_power_status and hasattr(self.gui, "update_power_status"):
            try:
                self.gui.update_power_status(self._latest_power_status)
            except Exception:
                pass
        if hasattr(self.gui, "update_hardware_connection"):
            try:
                self.gui.update_hardware_connection(self.service.is_hardware_connected)
            except Exception:
                pass
        latest_track = getattr(self.service, "_latest_track", None)
        if latest_track:
            self.gui.update_track_info(latest_track)
        if hasattr(self.gui, "set_brightness"):
            try:
                self.gui.set_brightness(self.service.get_brightness(), notify=False)
            except Exception:
                pass

    def restore_window(self):
        """Restores and brings the GUI window to the foreground."""
        self._dispatch_to_gui(self._restore_and_sync_gui)

    def hide_window(self):
        """Hides the GUI window to the system tray."""
        self._dispatch_to_gui(self.gui.hide_to_tray)

    def set_animation_mode(self, mode_name: str):
        self.service.set_animation_mode(mode_name)
        self.tray.update_mode(mode_name)
        self._dispatch_to_gui(lambda m=mode_name: self.gui.set_mode(m, notify=False))

    def set_brightness(self, level: int):
        self.service.set_brightness(level, source="software")

    def _on_brightness_changed(self, level: int, source: str = "software"):
        """Synchronizes GUI slider and Tray brightness readout when brightness changes."""
        if self.tray and hasattr(self.tray, "update_brightness"):
            self.tray.update_brightness(level)
        if self.gui and hasattr(self.gui, "set_brightness"):
            self._dispatch_to_gui(lambda b=level, s=source: self.gui.set_brightness(b, notify=False, source=s))

    def toggle_lighting(self, enabled: bool):
        self.service.toggle_lighting(enabled)
        self.tray.update_lighting_state(enabled)
        self._dispatch_to_gui(lambda e=enabled: self.gui.set_lighting_active(e, notify=False))

    def toggle_autostart(self, enabled: bool):
        set_autostart(enabled)
        if self.tray:
            self.tray.update_autostart_state()
        self._dispatch_to_gui(lambda e=enabled: self.gui.set_autostart_state(e))

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
        with self._gui_dispatch_lock:
            if self._is_exiting:
                return
            self._is_exiting = True
        print("Shutting down Predator Sync Application completely...", flush=True)
        try:
            self.service.remove_state_listener(self._on_service_state_tick)
            self.service.remove_power_listener(self._on_power_state_changed)
            self.service.remove_brightness_listener(self._on_brightness_changed)
        except Exception:
            pass
        self.service.stop()
        self.tray.stop()
        if self.gui and self.gui.root:
            root = self.gui.root
            if threading.get_ident() == self._main_thread_id:
                if self._gui_pump_id:
                    try:
                        root.after_cancel(self._gui_pump_id)
                    except Exception:
                        pass
                    self._gui_pump_id = None
                try:
                    self.gui.exit_application()
                except Exception:
                    pass
            else:
                try:
                    self._gui_queue.put_nowait(self.gui.exit_application)
                except Exception:
                    pass

    def start(self):
        """Starts background service, tray icon, and launches GUI."""
        # 1. Start background service
        self.service.start()

        # 2. Start Windows System Tray Icon
        self.tray.start()

        # 3. Create GUI Window and start main-thread cross-thread queue pump
        self.gui.create_window()
        self._start_gui_queue_pump()

        if self.start_minimized:
            self.gui.hide_to_tray()

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
