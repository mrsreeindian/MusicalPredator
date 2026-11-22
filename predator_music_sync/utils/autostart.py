"""
Windows Autostart (Start on Boot) Management
Uses Python standard library 'winreg' to register PredatorSync in
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run with '--minimized' flag
for seamless background startup into the system tray on Windows boot.
"""

import os
import sys

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "PredatorMusicSync"


def get_launch_command() -> str:
    """
    Determines the appropriate command to launch PredatorSync minimized on Windows boot.
    Supports both compiled standalone binary (dist/PredatorSync.exe) and Python source runtime.
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller compiled executable
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}" --minimized'
    else:
        # Running from Python source
        python_exe = sys.executable
        # Prefer pythonw.exe to prevent console window if available
        pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        launcher = pythonw if os.path.exists(pythonw) else python_exe

        # Main script path
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_script = os.path.join(package_dir, "main.py")
        return f'"{launcher}" "{main_script}" --minimized'


def is_autostart_enabled() -> bool:
    """Checks whether PredatorSync is registered in Windows Startup (HKCU Run)."""
    if sys.platform != "win32":
        return False

    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    """
    Enables or disables automatic startup on Windows boot.
    Registers in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    """
    if sys.platform != "win32":
        return False

    import winreg
    try:
        if enabled:
            cmd = get_launch_command()
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            return True
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, APP_VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        print(f"Autostart configuration error: {e}", flush=True)
        return False


def toggle_autostart() -> bool:
    """Toggles current autostart state and returns new state."""
    current = is_autostart_enabled()
    new_state = not current
    set_autostart(new_state)
    return is_autostart_enabled()
