"""
PredatorTrayManager - Windows System Tray Manager
Provides persistent notification area icon with quick controls:
- Double-click / Open Dashboard restores GUI window
- Close window hides into system tray without interrupting music sync
- Quick lighting toggle (Active / Paused)
- Quick mode selection (including Static Album Art)
- Clean complete exit
"""

import os
import sys
import threading
from typing import Optional, Callable
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu

from ..utils.autostart import is_autostart_enabled, set_autostart


def generate_predator_tray_icon(size: int = 64) -> Image.Image:
    """Generates a high-contrast Predator / Predator emblem icon for Windows system tray."""
    # Check if pre-rendered high quality icon asset exists
    asset_candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "assets", f"icon_{size}x{size}.png"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "assets", "predator_icon.png"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "predator_icon.png"),
        os.path.join(os.path.dirname(sys.executable), "assets", "predator_icon.png"),
        "assets/predator_icon.png",
    ]
    for candidate in asset_candidates:
        if candidate and os.path.exists(candidate):
            try:
                with Image.open(candidate) as raw_loaded:
                    loaded = raw_loaded.convert("RGBA")
                    if loaded.size != (size, size):
                        loaded = loaded.resize((size, size), Image.Resampling.LANCZOS)
                    return loaded
            except Exception:
                pass

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size, size

    # Outer dark rounded emblem with Predator yellow border
    draw.rounded_rectangle(
        [2, 2, w - 3, h - 3],
        radius=10,
        fill=(12, 12, 12, 255),
        outline=(255, 209, 0, 255),
        width=2
    )

    # Predator chevron / crown in Predator electric yellow
    pts = [
        (w * 0.22, h * 0.72),
        (w * 0.50, h * 0.22),
        (w * 0.78, h * 0.72),
        (w * 0.62, h * 0.72),
        (w * 0.50, h * 0.46),
        (w * 0.38, h * 0.72),
    ]
    draw.polygon(pts, fill=(255, 209, 0, 255))
    return img


class PredatorTrayManager:
    """
    Manages the Windows System Tray Icon, its context menu, notifications,
    and interactions between the background service and GUI window.
    """

    def __init__(
        self,
        on_show_window: Callable[[], None],
        on_hide_window: Callable[[], None],
        on_toggle_lighting: Callable[[bool], None],
        on_set_mode: Callable[[str], None],
        on_exit_app: Callable[[], None],
        on_toggle_autostart: Optional[Callable[[bool], None]] = None,
        on_set_brightness: Optional[Callable[[int], None]] = None,
        initial_lighting_active: bool = True,
        initial_mode: str = "Dynamic Studio EQ",
        initial_brightness: int = 100,
        hardware_status_text: str = "Helios Neo 16 [Connected]"
    ):
        self.on_show_window = on_show_window
        self.on_hide_window = on_hide_window
        self.on_toggle_lighting = on_toggle_lighting
        self.on_set_mode = on_set_mode
        self.on_exit_app = on_exit_app
        self.on_toggle_autostart = on_toggle_autostart
        self.on_set_brightness = on_set_brightness

        self._lighting_active = initial_lighting_active
        self._current_mode = initial_mode
        self._current_brightness = max(0, min(100, int(initial_brightness)))
        self._hw_status_text = hardware_status_text
        self._power_status_text = "Plugged In"
        self._disable_on_battery_saver = True

        self._icon: Optional[pystray.Icon] = None
        self._icon_lock = threading.RLock()
        self._has_notified_tray = False

    def build_menu(self) -> Menu:
        """Constructs the right-click tray context menu."""
        return Menu(
            item(
                "▲ Open MusicalPredator",
                self._handle_show_window,
                default=True
            ),
            Menu.SEPARATOR,
            item(
                "Lighting Enabled",
                self._handle_toggle_lighting,
                checked=lambda item: self._lighting_active
            ),
            item(
                "Start on Windows Boot",
                self._handle_toggle_autostart,
                checked=lambda item: is_autostart_enabled()
            ),
            item(
                lambda it: f"Brightness ({self._current_brightness}%)",
                Menu(
                    item(
                        "Increase (+25%)",
                        lambda icon, it: self._handle_step_brightness(25)
                    ),
                    item(
                        "Decrease (-25%)",
                        lambda icon, it: self._handle_step_brightness(-25)
                    ),
                    Menu.SEPARATOR,
                    item(
                        "100% (Full)",
                        lambda icon, it: self._handle_set_brightness(100),
                        checked=lambda item: self._current_brightness >= 90
                    ),
                    item(
                        "75%",
                        lambda icon, it: self._handle_set_brightness(75),
                        checked=lambda item: 65 <= self._current_brightness < 90
                    ),
                    item(
                        "50%",
                        lambda icon, it: self._handle_set_brightness(50),
                        checked=lambda item: 40 <= self._current_brightness < 65
                    ),
                    item(
                        "25%",
                        lambda icon, it: self._handle_set_brightness(25),
                        checked=lambda item: 1 <= self._current_brightness < 40
                    ),
                    item(
                        "0% (Off)",
                        lambda icon, it: self._handle_set_brightness(0),
                        checked=lambda item: self._current_brightness == 0
                    ),
                )
            ),
            item(
                "Quick Modes",
                Menu(
                    item(
                        "Static Album Art",
                        lambda icon, it: self._handle_set_mode("Static Album Art"),
                        checked=lambda item: self._current_mode == "Static Album Art"
                    ),
                    item(
                        "Dynamic Studio EQ",
                        lambda icon, it: self._handle_set_mode("Dynamic Studio EQ"),
                        checked=lambda item: self._current_mode == "Dynamic Studio EQ"
                    ),
                    item(
                        "Lush Chroma Aurora",
                        lambda icon, it: self._handle_set_mode("Lush Chroma Aurora"),
                        checked=lambda item: self._current_mode == "Lush Chroma Aurora"
                    ),
                    item(
                        "Neon Cyber Wave",
                        lambda icon, it: self._handle_set_mode("Neon Cyber Wave"),
                        checked=lambda item: self._current_mode == "Neon Cyber Wave"
                    ),
                    item(
                        "Bass Drop EDM Strobe",
                        lambda icon, it: self._handle_set_mode("Bass Drop EDM Strobe"),
                        checked=lambda item: self._current_mode == "Bass Drop EDM Strobe"
                    ),
                )
            ),
            Menu.SEPARATOR,
            item(lambda it: f"Power: {self._power_status_text}", lambda icon, it: None, enabled=False),
            item(lambda it: f"Hardware: {self._hw_status_text}", lambda icon, it: None, enabled=False),
            Menu.SEPARATOR,
            item("Hide to System Tray", self._handle_hide_window),
            item("Exit Completely", self._handle_exit_app)
        )

    def start(self):
        """Starts the system tray icon detached on Windows."""
        try:
            icon_img = generate_predator_tray_icon()
            with self._icon_lock:
                self._icon = pystray.Icon(
                    name="MusicalPredator",
                    icon=icon_img,
                    title="MusicalPredator (Helios Neo 16)",
                    menu=self.build_menu()
                )
                self._icon.run_detached()
        except Exception as e:
            print(f"Warning: System tray icon could not be initialized: {e}", flush=True)

    def stop(self):
        """Removes the icon from the system tray."""
        with self._icon_lock:
            icon = self._icon
            self._icon = None
        if icon:
            try:
                icon.stop()
            except Exception:
                pass

    def _safe_update_menu(self):
        with self._icon_lock:
            if self._icon:
                try:
                    self._icon.update_menu()
                except Exception:
                    pass

    def notify_minimized_to_tray(self, force: bool = False):
        """Notifies the user via Windows balloon notification that the app is active in the tray."""
        with self._icon_lock:
            if (not self._has_notified_tray or force) and self._icon:
                self._has_notified_tray = True
                try:
                    self._icon.notify(
                        "MusicalPredator is running in the background.\nClick or double-click this tray icon to open dashboard.",
                        "MusicalPredator"
                    )
                except Exception:
                    pass

    def update_lighting_state(self, active: bool):
        changed = (self._lighting_active != active)
        self._lighting_active = active
        if changed:
            self._safe_update_menu()

    def update_mode(self, mode: str):
        changed = (self._current_mode != mode)
        self._current_mode = mode
        if changed:
            self._safe_update_menu()

    def update_brightness(self, level: int):
        clamped = max(0, min(100, int(level)))
        changed = (self._current_brightness != clamped)
        self._current_brightness = clamped
        if changed:
            self._safe_update_menu()

    def update_autostart_state(self):
        self._safe_update_menu()

    def update_hardware_status(self, status_text: str):
        """Updates the hardware status line shown in the tray context menu."""
        if status_text != self._hw_status_text:
            self._hw_status_text = status_text
            self._safe_update_menu()

    def update_power_status(self, is_plugged: bool, is_saver_active: bool, battery_pct: int = 100):
        """Updates tray icon tooltip and context menu power status line."""
        if is_saver_active:
            new_power_text = "Battery Saver (Suspended)"
            title_text = "MusicalPredator • Battery Saver (Suspended)"
        elif not is_plugged:
            new_power_text = f"On Battery ({battery_pct}%)"
            title_text = f"MusicalPredator • On Battery ({battery_pct}%)"
        else:
            new_power_text = "Plugged In"
            title_text = "MusicalPredator • Plugged In"

        if new_power_text == self._power_status_text:
            return
        self._power_status_text = new_power_text

        with self._icon_lock:
            if self._icon:
                try:
                    self._icon.title = title_text[:120]
                    self._icon.update_menu()
                except Exception:
                    pass

    # Handlers
    def _handle_show_window(self, icon, item):
        if self.on_show_window:
            self.on_show_window()

    def _handle_hide_window(self, icon, item):
        if self.on_hide_window:
            self.on_hide_window()

    def _handle_toggle_lighting(self, icon, item):
        self._lighting_active = not self._lighting_active
        if self.on_toggle_lighting:
            self.on_toggle_lighting(self._lighting_active)
        self._safe_update_menu()

    def _handle_toggle_autostart(self, icon, item):
        new_val = not is_autostart_enabled()
        set_autostart(new_val)
        if self.on_toggle_autostart:
            self.on_toggle_autostart(new_val)
        self._safe_update_menu()

    def _handle_set_mode(self, mode_name: str):
        self._current_mode = mode_name
        if self.on_set_mode:
            self.on_set_mode(mode_name)
        self._safe_update_menu()

    def _handle_set_brightness(self, level: int):
        clamped = max(0, min(100, int(level)))
        self._current_brightness = clamped
        if self.on_set_brightness:
            self.on_set_brightness(clamped)
        self._safe_update_menu()

    def _handle_step_brightness(self, delta: int):
        self._handle_set_brightness(self._current_brightness + int(delta))

    def _handle_exit_app(self, icon, item):
        if self.on_exit_app:
            self.on_exit_app()
