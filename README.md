# MusicalPredator

[![Release](https://img.shields.io/badge/Release-v1.1.0-blue.svg)](https://github.com/mrsreeindian/MusicalPredator/releases/tag/v1.1.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-lightgrey.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hardware](https://img.shields.io/badge/Acer%20Predator-Helios%20%7C%20Triton%20%7C%20Nitro-red.svg)](https://www.acer.com/predator)

> **Real-time audio-reactive RGB lighting synchronization and Material Design 3 album art illumination for Acer Predator and Nitro gaming laptops.**

---

## Overview

**MusicalPredator** connects Windows system audio playback directly to your laptop's RGB backlit keyboard, lid logo, and rear lightbars. By interfacing directly with the Acer Lighting Service named pipe, MusicalPredator captures WASAPI loopback audio, performs real-time Fast Fourier Transform (FFT) spectral decomposition, executes adaptive beat and transient detection, and extracts high-fidelity dynamic color palettes from Windows System Media Transport Controls (SMTC) at up to 60 FPS—running completely in user-space with zero administrator prompts.

---

## Key Features

- **Direct Hardware Interfacing**:
  - Connects directly to `\\.\pipe\AcerLightingService_NamedPipe` in user space.
  - Zero heavy vendor bloatware or background CPU drag.
  - Built-in automatic named pipe reconnection worker and service crash recovery watchdog.

- **Universal Predator & Nitro Compatibility**:
  - Automatic DMI/WMI BIOS hardware detection.
  - Native support for **4-Zone RGB** laptops (Helios Neo 16, Helios 300, Nitro 5/16).
  - Native support for **Per-Key RGB** laptops (Helios 16, Triton 16/500) with dynamic gradient interpolation.
  - Multi-device auxiliary synchronization for **Rear Lightbars** and **Lid Logos**.

- **Material Design 3 Album Art Color Extraction**:
  - Extracts dominant and harmonic tonal palettes from active media playback (Spotify, Apple Music, YouTube, Tidal, Chrome/Firefox/Edge).
  - Material You Color dynamic tonal mapping produces vivid, high-saturation LED underglow.
  - Seamless cover retention prevents harsh fallback flashes during track transitions.

- **Intelligent Dual Power Profiles & Battery Saver**:
  - **AC Power Profile**: High-performance 60 FPS pacing, aggressive transient flash, and full dynamic range.
  - **Battery Profile**: Automatic switch to 30 FPS eco mode, brightness capped at 50%, and zero-motion album art ambient mode.
  - **Windows Battery Saver Integration**: Automatically turns off physical LEDs (0,0,0) and suspends audio capture threads (0.0% CPU usage) when Battery Saver engages.

- **14 Studio Lighting Modes**:
  - **Dynamic Audio Reactive**: Spectrum Equalizer, EDM Strobe, Ripple Wave, Scanner, Beat Pulse, Smooth Wave, Cyberpunk Shift, Plasma Vortex, Dual Split, Aurora Borealis, Firefly, Starlight Sparkle.
  - **Static & Ambient**: Static Album Art (steady underglow matched to album artwork) and Static Album Dominant (pure unified album glow).

- **Physical EC Keyboard Brightness & Hotkey Sync**:
  - Direct Embedded Controller (EC) brightness control via `\\.\pipe\AcerLightingService_NamedPipe` with anti-double-dimming RGB scaling.
  - Bidirectional `Fn+F9` / `Fn+F10` physical hotkey sync keeping the GUI slider, `EC SYNC` indicator badge, and tray **Brightness** submenu (`0%`–`100%`) aligned.

- **Windows Notification Area Tray Suite & Sleep/Resume Resilience**:
  - Runs reliably in the system notification tray with EcoQoS throttling opt-out, `WM_POWERBROADCAST` sleep/resume recovery, `PeekNamedPipe` health checks, and stalled WASAPI stream recovery.
  - Right-click tray menu for instant mode switching, EC brightness presets, pause controls, and **Check for Updates...**.
  - High-DPI responsive dashboard with hardware-accurate stepped 4-zone / 3-zone / Per-Key virtual keyboard mirror (full 6-row numpad), real-time 4-band audio EQ visualizer, and smooth 60 FPS projection.
  - Optional **Start on Windows Boot** autostart integration.

- **Built-In In-App Updater**:
  - Checks GitHub Releases (`mrsreeindian/MusicalPredator`) using SemVer 2.0.0 comparison, streaming progress, PE `MZ` & SHA-256 verification, and detached post-exit self-updating for both Portable EXE and silent Installed Setup upgrades.

---

## Hardware Compatibility

MusicalPredator automatically detects and configures itself for your laptop model:

| Laptop Family | Model Series | Keyboard Layout | Auxiliary Lighting |
| :--- | :--- | :--- | :--- |
| **Predator Helios Neo 16** | `PHN16-71`, `PHN16-72` | 4-Zone RGB | Zone-synced logo |
| **Predator Helios 16 / 18** | `PH16-71`, `PH16-72`, `PH18-71` | Per-Key RGB (84 keys) | Rear Lightbar (12 LEDs) & Lid Logo |
| **Predator Helios 300** | `PH315-53`, `PH315-54`, `PH315-55` | 4-Zone RGB | Lid Logo |
| **Predator Triton 16 / 500** | `PT516-52`, `PT515-52` | Per-Key / 3-Zone RGB | Lid Logo |
| **Predator Triton 300** | `PT315-52`, `PT315-53` | 3-Zone RGB | Unified logo |
| **Acer Nitro 5 / 16 / 17** | `AN515-58`, `AN16-41`, `AN17-51` | 4-Zone RGB | Standard keyboard zones |

---

## Installation

### Option 1: Standalone Installer (Recommended)
1. Download **`MusicalPredator-Setup.exe`** from the [Latest Release](https://github.com/mrsreeindian/MusicalPredator/releases/tag/v1.1.0).
2. Run the wizard to install to `%LOCALAPPDATA%\Programs\MusicalPredator`.
3. Choose desktop shortcuts and Windows startup preferences, then click **Finish**.

### Option 2: Portable Executable
1. Download **`MusicalPredator.exe`** from the [Latest Release](https://github.com/mrsreeindian/MusicalPredator/releases/tag/v1.1.0).
2. Place the executable in any folder and run directly.

### Option 3: Full Release Archive
1. Download **`MusicalPredator-v1.1.0-Windows-x64.zip`**.
2. Extract to your desired location and launch `Setup-MusicalPredator.bat` or `MusicalPredator.exe`.

---

## Building from Source

### Prerequisites
- Python 3.10+ (64-bit)
- Git for Windows
- Acer Lighting Service (preinstalled on Acer Predator & Nitro laptops)

### Setup
```powershell
git clone https://github.com/mrsreeindian/MusicalPredator.git
cd MusicalPredator
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Running the Application
```powershell
# Interactive Dashboard GUI
python run_app.pyw

# Run Minimized to System Tray
python run_app.pyw --minimized
```

### Running Tests and Benchmarks
```powershell
# Run all 5 automated test & verification suites
python test_component_audit.py
python test_tray_longevity.py
python test_keyboard_projection.py
python test_physical_brightness.py
python test_updater.py

# Run hardware latency and pipe roundtrip benchmark
python run_benchmark.py
```

### Compiling Standalone Executables
```powershell
python build_exe.py
```
Outputs generated in `dist/`:
- `dist/MusicalPredator-Setup.exe`: Standalone GUI setup wizard
- `dist/MusicalPredator.exe`: Standalone portable binary
- `dist/MusicalPredator-v1.1.0-Windows-x64.zip`: Complete distribution package

---

## Troubleshooting & Maintenance

If the keyboard does not react or AcerLightingService enters a stale state:
1. Run **`Fix-AcerLightingService.bat`** as Administrator to purge corrupted temporary lighting profiles, restart `AcerLightingService`, and configure automatic Windows service recovery.
2. Ensure loopback audio is capturing from the active audio output device in the MusicalPredator GUI audio settings.

---

## Project Structure

```
├── .github/workflows/       # GitHub Actions CI/CD automated build and release
├── assets/                  # High-DPI Windows application manifests and icons
├── installer/               # Modern dark-mode setup wizard GUI
├── predator_music_sync/     # Core application source
│   ├── benchmark/           # Hardware roundtrip latency benchmark runner
│   ├── core/                # FFT audio analysis, beat detection, and animations
│   ├── gui/                 # Sleek dark-mode dashboard, keyboard mirror & update dialog
│   ├── hardware/            # Named pipe driver, EC brightness, model detector, and ACPI layer
│   ├── service/             # Dedicated 60 FPS background sync thread
│   ├── tray/                # Windows notification area system tray manager
│   └── utils/               # Windows registry, power throttling, autostart & GitHub updater
├── build_exe.py             # Release packager & binary compiler
├── requirements.txt         # Production dependencies
├── test_component_audit.py  # Core component integration & hardware audit suite
├── test_tray_longevity.py   # Long-running tray, EcoQoS, pipe & SMTC resilience tests
├── test_keyboard_projection.py # Keyboard layout, zone alignment & animation fidelity tests
├── test_physical_brightness.py # EC brightness & Fn+F9/F10 sync tests
└── test_updater.py          # GitHub Releases updater & silent upgrade tests
```

---

## License

This project is licensed under the [MIT License](LICENSE).
