"""
Build Script for MusicalPredator Standalone Application & Installer
1. Compiles standalone application: 'dist/MusicalPredator.exe'
2. Compiles standalone Windows Installer: 'dist/MusicalPredator-Setup.exe'
3. Creates distribution package folder and 'dist/MusicalPredator-v1.0.0-Windows-x64.zip'
"""

import os
import sys
import shutil
import zipfile
import subprocess
import PyInstaller.__main__

def build():
    print("=" * 80)
    print("BUILDING MUSICALPREDATOR: Application & Standalone Installer")
    print("=" * 80)

    project_root = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(project_root, "assets")
    ico_path = os.path.join(assets_dir, "predator_icon.ico")
    manifest_path = os.path.join(assets_dir, "app.manifest")

    # 1. Ensure assets (icon & manifest) are present
    if not os.path.exists(ico_path) or not os.path.exists(manifest_path):
        print("[*] Generating icon assets...")
        import generate_assets
        generate_assets.generate_icons(assets_dir)

    print(f"[*] Icon asset     : {ico_path}")
    print(f"[*] Manifest asset : {manifest_path}")

    # Terminate any running instances
    try:
        subprocess.run(["taskkill", "/F", "/IM", "MusicalPredator.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "MusicalPredator-Setup.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "PredatorSync.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "PredatorSync-Setup.exe"], capture_output=True)
    except Exception:
        pass

    # --------------------------------------------------------------------------
    # STAGE 1: Compile Standalone Application (MusicalPredator.exe)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STAGE 1: Compiling Standalone App: dist/MusicalPredator.exe")
    print("-" * 80)

    app_entry = os.path.join(project_root, "run_app.pyw")
    app_args = [
        app_entry,
        "--name=MusicalPredator",
        "--noconsole",          # Pure Windows GUI application (no CMD prompt)
        "--clean",
        "--onefile",            # Standalone single executable
        f"--paths={project_root}",
        f"--icon={ico_path}",
        f"--manifest={manifest_path}",
        f"--add-data={assets_dir}{os.pathsep}assets",
        "--hidden-import=pystray",
        "--hidden-import=pystray._win32",
        "--hidden-import=sounddevice",
        "--hidden-import=_sounddevice",
        "--hidden-import=_sounddevice_data",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageDraw",
        "--hidden-import=numpy",
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.filedialog",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=tkinter.scrolledtext",
        "--hidden-import=winreg",
        "--hidden-import=ctypes",
        "--hidden-import=ctypes.wintypes",
        "--hidden-import=predator_music_sync.utils.autostart",
        "--hidden-import=predator_music_sync.utils.power",
        "--hidden-import=predator_music_sync.hardware.device_detector",
        "--collect-all=sounddevice",
        "--collect-all=_sounddevice_data",
        "--collect-all=pystray",
        "--collect-submodules=predator_music_sync",
        "--noconfirm",
    ]

    PyInstaller.__main__.run(app_args)

    dist_exe = os.path.join(project_root, "dist", "MusicalPredator.exe")
    if not os.path.exists(dist_exe):
        raise RuntimeError(f"App build failed! Not found: {dist_exe}")

    exe_size_mb = os.path.getsize(dist_exe) / (1024 * 1024)
    print(f"[SUCCESS] Standalone application compiled: {dist_exe} ({exe_size_mb:.2f} MB)")

    # --------------------------------------------------------------------------
    # STAGE 2: Compile Standalone Installer Wizard (MusicalPredator-Setup.exe)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STAGE 2: Compiling Standalone Installer: dist/MusicalPredator-Setup.exe")
    print("-" * 80)

    installer_entry = os.path.join(project_root, "installer", "setup_gui.py")
    installer_args = [
        installer_entry,
        "--name=MusicalPredator-Setup",
        "--noconsole",          # GUI wizard
        "--clean",
        "--onefile",            # Single setup executable
        f"--paths={project_root}",
        f"--icon={ico_path}",
        f"--manifest={manifest_path}",
        f"--add-data={dist_exe}{os.pathsep}payload",
        f"--add-data={assets_dir}{os.pathsep}payload{os.sep}assets",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageTk",
        "--hidden-import=PIL.ImageDraw",
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.filedialog",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=tkinter.messagebox",
        "--hidden-import=winreg",
        "--noconfirm",
    ]

    PyInstaller.__main__.run(installer_args)

    setup_exe = os.path.join(project_root, "dist", "MusicalPredator-Setup.exe")
    if not os.path.exists(setup_exe):
        raise RuntimeError(f"Installer build failed! Not found: {setup_exe}")

    setup_size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
    print(f"[SUCCESS] Standalone installer compiled: {setup_exe} ({setup_size_mb:.2f} MB)")

    # --------------------------------------------------------------------------
    # STAGE 3: Assemble Release Package and ZIP
    # --------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STAGE 3: Assembling Distribution Package & ZIP Archive")
    print("-" * 80)

    package_dir = os.path.join(project_root, "dist", "MusicalPredator-v1.0.0-Windows-x64")
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir)
    os.makedirs(package_dir, exist_ok=True)

    # Copy installer and standalone executable
    shutil.copy2(setup_exe, os.path.join(package_dir, "MusicalPredator-Setup.exe"))
    shutil.copy2(dist_exe, os.path.join(package_dir, "MusicalPredator.exe"))

    # Copy assets folder
    shutil.copytree(assets_dir, os.path.join(package_dir, "assets"))

    # Setup helper VBS
    shortcut_vbs = r'''Set WshShell = CreateObject("WScript.Shell")
strScriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
strDesktop = WshShell.SpecialFolders("Desktop")
strTarget = strScriptDir & "\MusicalPredator.exe"

Set oShortcut = WshShell.CreateShortcut(strDesktop & "\MusicalPredator.lnk")
oShortcut.TargetPath = strTarget
oShortcut.WorkingDirectory = strScriptDir
oShortcut.IconLocation = strScriptDir & "\assets\predator_icon.ico, 0"
oShortcut.Description = "MusicalPredator - 4-Zone RGB Music Sync"
oShortcut.Save
Set oShortcut = Nothing
Set WshShell = Nothing
MsgBox "Desktop shortcut created successfully for MusicalPredator!", 64, "MusicalPredator"
'''
    with open(os.path.join(package_dir, "Create-Desktop-Shortcut.vbs"), "w", encoding="utf-8") as f:
        f.write(shortcut_vbs)

    # Setup BAT
    setup_bat = r'''@echo off
title MusicalPredator - Setup & Launcher
echo ======================================================================
echo MusicalPredator
echo ======================================================================
echo.
echo [1] Run Standalone Installer (MusicalPredator-Setup.exe)
echo [2] Launch Portable App Directly (MusicalPredator.exe)
echo [3] Create Desktop Shortcut
echo [4] Exit
echo.
set /p opt="Select an option (1-4): "

if "%opt%"=="1" (
    start "" "%~dp0MusicalPredator-Setup.exe"
    exit
)
if "%opt%"=="2" (
    start "" "%~dp0MusicalPredator.exe"
    exit
)
if "%opt%"=="3" (
    cscript //nologo "%~dp0Create-Desktop-Shortcut.vbs"
    pause
    exit
)
exit
'''
    with open(os.path.join(package_dir, "Setup-MusicalPredator.bat"), "w", encoding="utf-8") as f:
        f.write(setup_bat)

    # README
    readme = """===============================================================================
MUSICALPREDATOR (v1.0.0)
Hardware Optimized for Acer Predator Helios Neo 16 (PHN16-71) 4-Zone RGB
===============================================================================

INSTALLATION OPTIONS:
1. Recommended: Run 'MusicalPredator-Setup.exe'
   - Elegant setup wizard.
   - Installs to %LOCALAPPDATA%\\Programs\\MusicalPredator (Zero UAC elevation required).
   - Creates Desktop & Start Menu shortcuts with high-resolution Predator icon.
   - Configures automatic Start on Windows Boot (silent start into system tray).
   - Registers in Windows Settings -> Apps -> Installed Apps with clean uninstaller.

2. Portable Mode: Run 'MusicalPredator.exe' directly
   - Single standalone executable with zero installation needed.

FEATURES:
- Pure Black Industrial Aesthetic (Predator Minimalist Style)
- Real-time 60 FPS Audio-Reactive Keyboard Illumination (Sub-Bass, Low-Mid, High-Mid, Treble)
- Zero-Elevation Physical ACPI EC Named Pipe Driver (No Admin Privileges Required)
- Windows System Tray Integration (Double-click to open, close minimizes to tray)
- 12 Audio-Reactive Animation Algorithms (Dynamic Studio EQ, Bass Drop Strobe, Aurora, etc.)
- Static Album Art Mode & Windows SMTC Media Integration
- Per-Monitor V2 DPI Awareness (Clean, razor-sharp rendering at 125% & 150% scaling)
- Ultra-Low Idle Resource Usage (~0.1% CPU when minimized and during silence)
- Start on Boot Registry Integration

REQUIREMENTS:
- Windows 10 or Windows 11 (64-bit)
- Acer Predator Helios Neo 16 or compatible 4-Zone Acer RGB laptop
- Acer Lighting Service running in background (standard Acer OEM pre-install)
"""
    with open(os.path.join(package_dir, "README.txt"), "w", encoding="utf-8") as f:
        f.write(readme)

    # ZIP Package
    zip_path = os.path.join(project_root, "dist", "MusicalPredator-v1.0.0-Windows-x64.zip")
    print(f"[*] Packaging ZIP archive: {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(package_dir))
                zipf.write(file_path, arcname)

    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    print("\n" + "=" * 80)
    print("ALL PACKAGING & INSTALLER TASKS COMPLETED SUCCESSFULLY!")
    print(f"1. Standalone Installer  : {setup_exe} ({setup_size_mb:.2f} MB)")
    print(f"2. Standalone Application: {dist_exe} ({exe_size_mb:.2f} MB)")
    print(f"3. Distribution Folder   : {package_dir}")
    print(f"4. Distribution ZIP      : {zip_path} ({zip_size_mb:.2f} MB)")
    print("=" * 80)

if __name__ == "__main__":
    build()
