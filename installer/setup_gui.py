r"""
MusicalPredator - Standalone Setup Wizard
Professional, zero-UAC user-level Windows Installer.
Installs to %LOCALAPPDATA%\Programs\MusicalPredator, creates shortcuts,
configures autostart, and registers in Windows Add/Remove Programs.
"""

import os
import sys
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, Optional, Sequence
from PIL import Image, ImageTk, ImageDraw

try:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT_DIR not in sys.path:
        sys.path.insert(0, _ROOT_DIR)
    from predator_music_sync import __version__ as APP_VERSION
except Exception:
    APP_VERSION = "1.1.0"


# Theme Palette (MusicalPredator Dark Aesthetic)
COLOR_BG = "#000000"
COLOR_PANEL = "#0B0B0B"
COLOR_CARD = "#121212"
COLOR_BORDER = "#1F1F1F"
COLOR_ACCENT = "#FFD100"      # Predator Electric Yellow
COLOR_ACCENT_HOVER = "#FFE033"
COLOR_TEXT = "#FFFFFF"
COLOR_MUTED = "#888888"
COLOR_DARK_TEXT = "#555555"
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"


def get_default_install_dir() -> str:
    """Returns %LOCALAPPDATA%\\Programs\\MusicalPredator for zero-UAC installation."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = os.path.expanduser(r"~\AppData\Local")
    return os.path.join(local_app_data, "Programs", "MusicalPredator")


def get_payload_paths():
    """Finds bundled or local MusicalPredator.exe and assets."""
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # Running from project source
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates_exe = [
        os.path.join(base_dir, "payload", "MusicalPredator.exe"),
        os.path.join(base_dir, "dist", "MusicalPredator.exe"),
        os.path.join(base_dir, "MusicalPredator.exe"),
        os.path.join(base_dir, "payload", "PredatorSync.exe"),
        os.path.join(base_dir, "dist", "PredatorSync.exe"),
    ]
    exe_path = None
    for c in candidates_exe:
        if os.path.exists(c):
            exe_path = c
            break

    candidates_assets = [
        os.path.join(base_dir, "payload", "assets"),
        os.path.join(base_dir, "assets"),
        os.path.join(base_dir, "dist", "assets"),
    ]
    assets_path = None
    for a in candidates_assets:
        if os.path.isdir(a):
            assets_path = a
            break

    return exe_path, assets_path


def get_existing_install_dir() -> Optional[str]:
    """Reads existing InstallLocation from HKCU Uninstall registry if present."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicalPredator"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, "InstallLocation")
            if val and os.path.isdir(str(val).strip()):
                return os.path.normpath(str(val).strip())
    except Exception:
        pass
    return None


def _is_autostart_registered() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, "MusicalPredator")
            return bool(val)
    except Exception:
        return False


def _copy_with_retry(src: str, dst: str, retries: int = 10, delay: float = 0.5) -> None:
    """Copies payload binary with retry in case previous process is still releasing locks."""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError as exc:
            last_err = exc
            if attempt == 2:
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "MusicalPredator.exe"], capture_output=True)
                    subprocess.run(["taskkill", "/F", "/IM", "PredatorSync.exe"], capture_output=True)
                except Exception:
                    pass
            time.sleep(delay)
    if last_err is not None:
        raise last_err


def _create_shortcut(shortcut_name: str, folder: str, target: str, work_dir: str, icon: str = "", desc: str = ""):
    """Creates a Windows .lnk shortcut using temporary VBScript execution."""
    os.makedirs(folder, exist_ok=True)
    lnk_path = os.path.join(folder, shortcut_name)
    vbs_script = f"""
Set WshShell = CreateObject("WScript.Shell")
Set oShortcut = WshShell.CreateShortcut("{lnk_path.replace('\\', '\\\\')}")
oShortcut.TargetPath = "{target.replace('\\', '\\\\')}"
oShortcut.WorkingDirectory = "{work_dir.replace('\\', '\\\\')}"
oShortcut.Description = "{desc}"
"""
    if icon:
        vbs_script += f'oShortcut.IconLocation = "{icon.replace("\\", "\\\\")}"\n'
    vbs_script += "oShortcut.Save\n"

    subprocess.run(["cscript", "//nologo", "/E:VBScript"], input=vbs_script, text=True, capture_output=True)


def _create_uninstaller(install_dir: str):
    """Creates clean uninstallation scripts."""
    uninst_bat_path = os.path.join(install_dir, "uninstall.bat")
    bat_content = f"""@echo off
title MusicalPredator Uninstaller
echo ======================================================================
echo Uninstalling MusicalPredator...
echo ======================================================================

:: Kill running instances
taskkill /F /IM MusicalPredator.exe >nul 2>&1
taskkill /F /IM PredatorSync.exe >nul 2>&1

:: Remove Autostart Key
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "MusicalPredator" /f >nul 2>&1
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "PredatorMusicSync" /f >nul 2>&1

:: Remove Uninstall Registration Key
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MusicalPredator" /f >nul 2>&1
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PredatorSync" /f >nul 2>&1

:: Remove Shortcuts
del /Q "%USERPROFILE%\\Desktop\\MusicalPredator.lnk" >nul 2>&1
del /Q "%USERPROFILE%\\Desktop\\Predator Keyboard Sync.lnk" >nul 2>&1
rd /S /Q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\MusicalPredator" >nul 2>&1
rd /S /Q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Predator Sync" >nul 2>&1

:: Delete installation files (self-deleting batch)
start /b "" cmd /c timeout /t 1 /nobreak ^>nul ^& rd /S /Q "{install_dir}"
echo.
echo Uninstallation Complete.
if "%1"=="" pause
exit
"""
    with open(uninst_bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)


def _register_uninstall_entry(install_dir: str, exe_path: str, ico_path: str):
    """Registers the application in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MusicalPredator."""
    try:
        import winreg
        uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicalPredator"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, uninstall_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "MusicalPredator")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Predator Community")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            if os.path.exists(ico_path):
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, ico_path)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{os.path.join(install_dir, "uninstall.bat")}"')
            winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{os.path.join(install_dir, "uninstall.bat")} /quiet"')
            winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, 36000)
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        print(f"Warning: Failed to write uninstall registry: {e}")


def _configure_autostart(exe_path: str):
    """Registers start on boot in HKCU Run."""
    try:
        import winreg
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        cmd = f'"{exe_path}" --minimized'
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "MusicalPredator", 0, winreg.REG_SZ, cmd)
    except Exception as e:
        print(f"Warning: Failed to set autostart: {e}")


def perform_installation(
    install_dir: str,
    create_desktop_shortcut: bool = True,
    create_start_shortcut: bool = True,
    enable_autostart: bool = True,
    progress_cb=None,
) -> str:
    """Performs the actual installation or in-place upgrade and returns installed MusicalPredator.exe path."""
    def _report(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    target_dir = os.path.normpath(install_dir)
    _report(10, f"Creating destination directory: {target_dir}")
    os.makedirs(target_dir, exist_ok=True)

    _report(20, "Checking running processes...")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "MusicalPredator.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "PredatorSync.exe"], capture_output=True)
    except Exception:
        pass

    exe_src, assets_src = get_payload_paths()
    if not exe_src or not os.path.exists(exe_src):
        raise RuntimeError("MusicalPredator.exe payload not found in installer package.")

    _report(40, "Copying MusicalPredator.exe binary...")
    target_exe = os.path.join(target_dir, "MusicalPredator.exe")
    _copy_with_retry(exe_src, target_exe)

    if assets_src and os.path.isdir(assets_src):
        _report(55, "Copying application assets and icons...")
        target_assets = os.path.join(target_dir, "assets")
        if os.path.exists(target_assets):
            shutil.rmtree(target_assets)
        shutil.copytree(assets_src, target_assets)

    target_ico = os.path.join(target_dir, "assets", "predator_icon.ico")
    icon_loc = f"{target_ico}, 0" if os.path.exists(target_ico) else ""

    if create_desktop_shortcut:
        _report(70, "Creating Desktop shortcut...")
        _create_shortcut(
            shortcut_name="MusicalPredator.lnk",
            folder=os.path.expanduser(r"~\Desktop"),
            target=target_exe,
            work_dir=target_dir,
            icon=icon_loc,
            desc="Acer Predator Helios Neo 16 4-Zone RGB Music Sync"
        )

    if create_start_shortcut:
        _report(80, "Creating Start Menu shortcuts...")
        start_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\MusicalPredator")
        os.makedirs(start_dir, exist_ok=True)
        _create_shortcut(
            shortcut_name="MusicalPredator.lnk",
            folder=start_dir,
            target=target_exe,
            work_dir=target_dir,
            icon=icon_loc,
            desc="Acer Predator Helios Neo 16 4-Zone RGB Music Sync"
        )

    _report(85, "Creating uninstaller...")
    _create_uninstaller(target_dir)

    _report(90, "Registering in Windows Installed Apps...")
    _register_uninstall_entry(target_dir, target_exe, target_ico)

    if enable_autostart:
        _report(95, "Configuring Start on Windows Boot...")
        _configure_autostart(target_exe)

    _report(100, "Installation completed successfully!")
    return target_exe


def parse_installer_args(argv: Sequence[str]) -> Dict[str, object]:
    """Parses CLI flags for unattended/silent updates (--silent, --dir=..., --launch, --minimized)."""
    opts: Dict[str, object] = {
        "silent": False,
        "install_dir": None,
        "launch": False,
        "minimized": False,
    }
    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        low = arg.lower()
        if low in ("--silent", "/s", "-s", "--unattended"):
            opts["silent"] = True
        elif low == "--launch":
            opts["launch"] = True
        elif low == "--minimized":
            opts["minimized"] = True
        elif low.startswith("--dir="):
            opts["install_dir"] = os.path.normpath(arg.split("=", 1)[1].strip('"'))
        elif low == "--dir" and i + 1 < len(args):
            opts["install_dir"] = os.path.normpath(args[i + 1].strip('"'))
            i += 1
        i += 1
    return opts


def run_silent_install(opts: Dict[str, object]) -> int:
    """Runs an unattended in-place installation/upgrade and optionally launches MusicalPredator.exe."""
    install_dir = opts.get("install_dir") or get_existing_install_dir() or get_default_install_dir()
    preserve_autostart = _is_autostart_registered()
    target_exe = perform_installation(
        install_dir=str(install_dir),
        create_desktop_shortcut=False,
        create_start_shortcut=True,
        enable_autostart=preserve_autostart,
    )
    if opts.get("launch") and os.path.exists(target_exe):
        launch_cmd = [target_exe]
        if opts.get("minimized"):
            launch_cmd.append("--minimized")
        subprocess.Popen(launch_cmd, cwd=os.path.dirname(target_exe), close_fds=True)
    return 0


class MusicalPredatorSetupWizard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MusicalPredator // Setup Wizard")
        self.root.configure(bg=COLOR_BG)
        self.root.resizable(False, False)

        # Window geometry
        win_w, win_h = 640, 480
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (screen_h - win_h) // 2)
        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

        # Installation options state
        self.var_install_dir = tk.StringVar(value=get_default_install_dir())
        self.var_shortcut_desktop = tk.BooleanVar(value=True)
        self.var_shortcut_start = tk.BooleanVar(value=True)
        self.var_autostart = tk.BooleanVar(value=True)
        self.var_launch_now = tk.BooleanVar(value=True)

        # Set Window Icon
        self._load_icon()

        # Build UI Container
        self.main_container = tk.Frame(self.root, bg=COLOR_BG)
        self.main_container.pack(fill="both", expand=True)

        self.current_screen = 0
        self.screens = []

        # Header Bar
        self._build_header()

        # Content Area
        self.content_frame = tk.Frame(self.main_container, bg=COLOR_BG)
        self.content_frame.pack(fill="both", expand=True, padx=24, pady=16)

        # Bottom Navigation Bar
        self._build_footer()

        # Show Screen 1
        self.show_screen(1)

    def _load_icon(self):
        """Loads and sets the window icon."""
        _, assets_dir = get_payload_paths()
        if assets_dir:
            ico = os.path.join(assets_dir, "predator_icon.ico")
            if os.path.exists(ico):
                try:
                    self.root.iconbitmap(ico)
                except Exception:
                    pass

    def _build_header(self):
        """Sleek pure black Predator header with brand text and status indicator."""
        header = tk.Frame(self.main_container, bg=COLOR_PANEL, height=56, highlightthickness=1, highlightbackground=COLOR_BORDER)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Predator electric yellow accent bar on left
        accent_strip = tk.Frame(header, bg=COLOR_ACCENT, width=4)
        accent_strip.pack(side="left", fill="y")

        info_box = tk.Frame(header, bg=COLOR_PANEL)
        info_box.pack(side="left", padx=16, fill="y")

        lbl_title = tk.Label(
            info_box,
            text="MUSICALPREDATOR // SETUP",
            font=(FONT_FAMILY, 11, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL
        )
        lbl_title.pack(anchor="w", pady=(8, 0))

        lbl_sub = tk.Label(
            info_box,
            text="Acer Predator Helios Neo 16",
            font=(FONT_FAMILY, 8),
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL
        )
        lbl_sub.pack(anchor="w")

        # Version Badge on Right
        lbl_ver = tk.Label(
            header,
            text=f"v{APP_VERSION}",
            font=(FONT_MONO, 8, "bold"),
            fg=COLOR_BG,
            bg=COLOR_ACCENT,
            padx=8,
            pady=2
        )
        lbl_ver.pack(side="right", padx=18)

    def _build_footer(self):
        """Bottom navigation footer with aligned Predator buttons."""
        footer = tk.Frame(self.main_container, bg=COLOR_PANEL, height=52, highlightthickness=1, highlightbackground=COLOR_BORDER)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        btn_box = tk.Frame(footer, bg=COLOR_PANEL)
        btn_box.pack(side="right", padx=18, pady=10)

        self.btn_back = tk.Button(
            btn_box,
            text="< BACK",
            font=(FONT_FAMILY, 9, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            activeforeground=COLOR_ACCENT,
            activebackground=COLOR_BORDER,
            bd=0,
            padx=16,
            pady=4,
            cursor="hand2",
            command=self.on_back
        )
        self.btn_back.pack(side="left", padx=6)

        self.btn_next = tk.Button(
            btn_box,
            text="NEXT >",
            font=(FONT_FAMILY, 9, "bold"),
            fg=COLOR_BG,
            bg=COLOR_ACCENT,
            activeforeground=COLOR_BG,
            activebackground=COLOR_ACCENT_HOVER,
            bd=0,
            padx=20,
            pady=4,
            cursor="hand2",
            command=self.on_next
        )
        self.btn_next.pack(side="left", padx=6)

        self.btn_cancel = tk.Button(
            footer,
            text="CANCEL",
            font=(FONT_FAMILY, 8),
            fg=COLOR_MUTED,
            bg=COLOR_PANEL,
            activeforeground=COLOR_TEXT,
            activebackground=COLOR_PANEL,
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.root.destroy
        )
        self.btn_cancel.pack(side="left", padx=18, pady=10)

    def _clear_content(self):
        for w in self.content_frame.winfo_children():
            w.destroy()

    def show_screen(self, screen_id: int):
        self.current_screen = screen_id
        self._clear_content()

        if screen_id == 1:
            self._render_screen_welcome()
        elif screen_id == 2:
            self._render_screen_options()
        elif screen_id == 3:
            self._render_screen_installing()
        elif screen_id == 4:
            self._render_screen_finish()

    # --------------------------------------------------------------------------
    # SCREEN 1: Welcome & Overview
    # --------------------------------------------------------------------------
    def _render_screen_welcome(self):
        self.btn_back.config(state="disabled")
        self.btn_next.config(text="NEXT >", state="normal")

        card = tk.Frame(self.content_frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=6, pady=6)

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=20)

        # Title
        tk.Label(
            inner,
            text="Welcome to MusicalPredator Setup",
            font=(FONT_FAMILY, 15, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            inner,
            text="This wizard will install MusicalPredator on your system.",
            font=(FONT_FAMILY, 9),
            fg=COLOR_MUTED,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 16))

        # Features Card
        feat_box = tk.Frame(inner, bg=COLOR_PANEL, highlightthickness=1, highlightbackground=COLOR_BORDER)
        feat_box.pack(fill="x", pady=6)

        features = [
            ("⚡ 60 FPS Real-Time Music Sync", "Ultra-low latency FFT audio analysis & 4-zone beat detection"),
            ("⌨ Hardware ACPI EC Driver", "Direct physical keyboard RGB control (Zero-Elevation, No Admin needed)"),
            ("🎨 Audio-Reactive Lighting", "12 animations, studio EQ bars, and album art color sync"),
            ("🔔 Background System Tray Suite", "Persistent notification area service with quick mode switcher"),
            ("🚀 Start on Boot Ready", "Silent background startup directly into Windows System Tray")
        ]

        for title, desc in features:
            f_row = tk.Frame(feat_box, bg=COLOR_PANEL)
            f_row.pack(fill="x", padx=12, pady=5)

            tk.Label(
                f_row,
                text=title,
                font=(FONT_FAMILY, 8, "bold"),
                fg=COLOR_ACCENT,
                bg=COLOR_PANEL,
                width=26,
                anchor="w"
            ).pack(side="left")

            tk.Label(
                f_row,
                text=desc,
                font=(FONT_FAMILY, 8),
                fg=COLOR_TEXT,
                bg=COLOR_PANEL,
                anchor="w"
            ).pack(side="left", fill="x")

        tk.Label(
            inner,
            text="Click Next to customize installation directory and shortcuts.",
            font=(FONT_FAMILY, 8),
            fg=COLOR_DARK_TEXT,
            bg=COLOR_CARD
        ).pack(side="bottom", anchor="w", pady=(10, 0))

    # --------------------------------------------------------------------------
    # SCREEN 2: Installation Options
    # --------------------------------------------------------------------------
    def _render_screen_options(self):
        self.btn_back.config(state="normal")
        self.btn_next.config(text="INSTALL", state="normal")

        card = tk.Frame(self.content_frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=6, pady=6)

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=16)

        # 1. Directory Section
        tk.Label(
            inner,
            text="Destination Folder",
            font=(FONT_FAMILY, 11, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            inner,
            text="MusicalPredator will be installed to user folder without requiring UAC elevation:",
            font=(FONT_FAMILY, 8),
            fg=COLOR_MUTED,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 8))

        dir_box = tk.Frame(inner, bg=COLOR_CARD)
        dir_box.pack(fill="x", pady=(0, 16))

        entry_dir = tk.Entry(
            dir_box,
            textvariable=self.var_install_dir,
            font=(FONT_MONO, 8),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
            insertbackground=COLOR_ACCENT,
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_ACCENT
        )
        entry_dir.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

        btn_browse = tk.Button(
            dir_box,
            text="BROWSE...",
            font=(FONT_FAMILY, 8, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
            activeforeground=COLOR_ACCENT,
            activebackground=COLOR_BORDER,
            bd=0,
            padx=10,
            cursor="hand2",
            command=self._browse_directory
        )
        btn_browse.pack(side="right")

        # 2. Options / Checkboxes Section
        tk.Label(
            inner,
            text="Shortcuts & Startup Options",
            font=(FONT_FAMILY, 11, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(4, 4))

        opt_frame = tk.Frame(inner, bg=COLOR_PANEL, highlightthickness=1, highlightbackground=COLOR_BORDER)
        opt_frame.pack(fill="x", pady=6)

        cb1 = tk.Checkbutton(
            opt_frame,
            text="Create Desktop Shortcut",
            variable=self.var_shortcut_desktop,
            font=(FONT_FAMILY, 9),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
            activebackground=COLOR_PANEL,
            activeforeground=COLOR_ACCENT,
            selectcolor=COLOR_BORDER,
            anchor="w"
        )
        cb1.pack(fill="x", padx=12, pady=4)

        cb2 = tk.Checkbutton(
            opt_frame,
            text="Create Start Menu Shortcut",
            variable=self.var_shortcut_start,
            font=(FONT_FAMILY, 9),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
            activebackground=COLOR_PANEL,
            activeforeground=COLOR_ACCENT,
            selectcolor=COLOR_BORDER,
            anchor="w"
        )
        cb2.pack(fill="x", padx=12, pady=4)

        cb3 = tk.Checkbutton(
            opt_frame,
            text="Start MusicalPredator with Windows on Boot (Silently to Tray)",
            variable=self.var_autostart,
            font=(FONT_FAMILY, 9),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
            activebackground=COLOR_PANEL,
            activeforeground=COLOR_ACCENT,
            selectcolor=COLOR_BORDER,
            anchor="w"
        )
        cb3.pack(fill="x", padx=12, pady=4)

    def _browse_directory(self):
        new_dir = filedialog.askdirectory(initialdir=self.var_install_dir.get(), title="Select Destination Folder")
        if new_dir:
            self.var_install_dir.set(os.path.normpath(new_dir))

    # --------------------------------------------------------------------------
    # SCREEN 3: Extraction & Progress
    # --------------------------------------------------------------------------
    def _render_screen_installing(self):
        self.btn_back.config(state="disabled")
        self.btn_next.config(state="disabled")
        self.btn_cancel.config(state="disabled")

        card = tk.Frame(self.content_frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=6, pady=6)

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=24)

        tk.Label(
            inner,
            text="Installing MusicalPredator...",
            font=(FONT_FAMILY, 13, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 6))

        self.lbl_progress_status = tk.Label(
            inner,
            text="Preparing installation...",
            font=(FONT_FAMILY, 8),
            fg=COLOR_MUTED,
            bg=COLOR_CARD
        )
        self.lbl_progress_status.pack(anchor="w", pady=(0, 16))

        # Modern Custom Progress Bar
        bar_bg = tk.Frame(inner, bg=COLOR_PANEL, height=18, highlightthickness=1, highlightbackground=COLOR_BORDER)
        bar_bg.pack(fill="x", pady=8)
        bar_bg.pack_propagate(False)

        self.progress_fill = tk.Frame(bar_bg, bg=COLOR_ACCENT, width=0)
        self.progress_fill.pack(side="left", fill="y")

        self.lbl_progress_pct = tk.Label(
            inner,
            text="0%",
            font=(FONT_MONO, 8, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_CARD
        )
        self.lbl_progress_pct.pack(anchor="e", pady=(4, 0))

        # Launch background installer thread
        threading.Thread(target=self._run_installation, daemon=True).start()

    def _set_progress(self, pct: float, status: str):
        def _update():
            pct_int = int(min(100, max(0, pct)))
            self.lbl_progress_status.config(text=status)
            self.lbl_progress_pct.config(text=f"{pct_int}%")
            self.root.update_idletasks()
            total_w = self.content_frame.winfo_width() - 60
            self.progress_fill.config(width=int(total_w * (pct_int / 100.0)))
        self.root.after(0, _update)

    def _run_installation(self):
        try:
            perform_installation(
                install_dir=self.var_install_dir.get(),
                create_desktop_shortcut=self.var_shortcut_desktop.get(),
                create_start_shortcut=self.var_shortcut_start.get(),
                enable_autostart=self.var_autostart.get(),
                progress_cb=self._set_progress,
            )
            time.sleep(0.3)
            self.root.after(0, lambda: self.show_screen(4))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Installation Error", f"Installation failed:\n{e}"))
            self.root.after(0, lambda: self.show_screen(2))

    # --------------------------------------------------------------------------
    # SCREEN 4: Finish
    # --------------------------------------------------------------------------
    def _render_screen_finish(self):
        self.btn_back.config(state="disabled")
        self.btn_next.config(text="FINISH", state="normal")
        self.btn_cancel.config(state="disabled")

        card = tk.Frame(self.content_frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=6, pady=6)

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(fill="both", expand=True, padx=24, pady=24)

        # Success Emblem / Check
        tk.Label(
            inner,
            text="✔ INSTALLATION COMPLETE",
            font=(FONT_FAMILY, 14, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            inner,
            text="MusicalPredator has been installed successfully.",
            font=(FONT_FAMILY, 9),
            fg=COLOR_TEXT,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 20))

        summary_box = tk.Frame(inner, bg=COLOR_PANEL, highlightthickness=1, highlightbackground=COLOR_BORDER)
        summary_box.pack(fill="x", pady=6)

        rows = [
            ("Installed to:", self.var_install_dir.get()),
            ("System Tray:", "Persistent 60 FPS background sync"),
            ("Start on Boot:", "Enabled (Silent startup to tray)" if self.var_autostart.get() else "Disabled"),
            ("Hardware Target:", "Acer Predator Helios Neo 16 (PHN16-71)")
        ]
        for label, val in rows:
            r = tk.Frame(summary_box, bg=COLOR_PANEL)
            r.pack(fill="x", padx=12, pady=4)
            tk.Label(r, text=label, font=(FONT_FAMILY, 8, "bold"), fg=COLOR_MUTED, bg=COLOR_PANEL, width=16, anchor="w").pack(side="left")
            tk.Label(r, text=val, font=(FONT_MONO, 8), fg=COLOR_TEXT, bg=COLOR_PANEL, anchor="w").pack(side="left", fill="x")

        # Launch checkbox
        cb_launch = tk.Checkbutton(
            inner,
            text="Launch MusicalPredator now",
            variable=self.var_launch_now,
            font=(FONT_FAMILY, 10, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_CARD,
            activebackground=COLOR_CARD,
            activeforeground=COLOR_ACCENT_HOVER,
            selectcolor=COLOR_PANEL
        )
        cb_launch.pack(anchor="w", pady=(20, 0))

    def on_back(self):
        if self.current_screen > 1:
            self.show_screen(self.current_screen - 1)

    def on_next(self):
        if self.current_screen == 1:
            self.show_screen(2)
        elif self.current_screen == 2:
            self.show_screen(3)
        elif self.current_screen == 4:
            # Finish action
            if self.var_launch_now.get():
                target_exe = os.path.join(self.var_install_dir.get(), "MusicalPredator.exe")
                if os.path.exists(target_exe):
                    subprocess.Popen([target_exe], cwd=self.var_install_dir.get())
            self.root.destroy()


def main(argv: Optional[Sequence[str]] = None):
    opts = parse_installer_args(sys.argv[1:] if argv is None else argv)
    if opts.get("silent"):
        try:
            code = run_silent_install(opts)
        except Exception as exc:
            print(f"Silent installation failed: {exc}", file=sys.stderr)
            code = 1
        if argv is None:
            sys.exit(code)
        return code

    root = tk.Tk()
    app = MusicalPredatorSetupWizard(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    main()
