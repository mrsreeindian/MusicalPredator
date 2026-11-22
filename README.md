# Predator Keyboard Music Sync

Real-time audio-reactive RGB synchronization and album art color illumination for the 4-zone keyboard on Acer Predator Helios Neo 16 laptops.

---

## Overview

**Predator Keyboard Music Sync** connects system audio playback directly to your laptop's 4-zone RGB backlit keyboard. It samples loopback audio, performs fast Fourier transform (FFT) frequency analysis and transient beat detection, extracts album art color palettes via Windows System Media Transport Controls (SMTC), and updates physical LED zones at up to 60 FPS.

---

## Features

- **Direct Hardware Driver**: Communicates directly through the local Acer Lighting Service named pipe (`\\.\pipe\AcerLightingService_NamedPipe`), bypassing heavy vendor control panels and running in user space with zero administrator prompts.
- **Audio-Reactive Engine**: Real-time frequency decomposition across sub-bass, low-mid, high-mid, and treble bands with adaptive beat-detection latching.
- **14 Lighting Modes**: Includes 12 rhythmic animation styles (Spectrum Equalizer, EDM Strobe, Ripple Wave, Scanner, etc.) and 2 static album cover modes that keep static colors without motion.
- **Album Art Color Sync**: Live dominant color extraction from currently playing media tracks across Spotify, Apple Music, YouTube, and browser sessions.
- **System Tray Suite**: Persistent background lighting service. Minimizing or closing the dashboard hides the app to the Windows notification area with a quick-action right-click menu.
- **Ultra-Low Resource Footprint**: When hidden in the tray or during audio silence, rendering loops throttle automatically to reduce idle CPU utilization to ~0.1%.
- **Windows Startup Integration**: Option to launch silently into the system tray on Windows boot.

---

## Hardware Compatibility

- **Target Device**: Acer Predator Helios Neo 16 (`PHN16-71`)
- **Operating System**: Windows 10 / Windows 11 (64-bit)
- **Dependency**: Acer Lighting Service (standard OEM service running in background)

---

## Installation

### Option 1: Standalone Installer (Recommended)
1. Download `PredatorSync-Setup.exe` from the latest release.
2. Run the setup wizard to install to `%LOCALAPPDATA%\Programs\PredatorSync`.
3. Choose shortcut and startup options, then click **Finish**.

### Option 2: Portable Executable
1. Download `PredatorSync.exe` from the latest release.
2. Place it in any folder and run directly.

---

## Building from Source

### Prerequisites
- Python 3.10 or higher
- Git

### Setup
```bash
git clone https://github.com/your-username/predator-keyboard-music-sync.git
cd predator-keyboard-music-sync
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Running the App
```bash
# Launch interactive dashboard
python run_app.pyw

# Run in background (minimized to system tray)
python run_app.pyw --minimized
```

### Running Tests and Benchmarks
```bash
# Run full component audit test suite
python test_component_audit.py

# Run physical hardware latency benchmark
python run_benchmark.py
```

### Compiling Standalone Binaries
```bash
python build_exe.py
```
Compiled outputs will be generated in the `dist/` directory:
- `dist/PredatorSync.exe`: Standalone portable executable
- `dist/PredatorSync-Setup.exe`: Standalone setup wizard installer
- `dist/PredatorSync-v1.0.0-Windows-x64.zip`: Full release distribution package

---

## Project Structure

```
├── assets/                  # Icons and Windows DPI application manifest
├── installer/               # Setup wizard GUI source code
├── predator_music_sync/     # Core application package
│   ├── benchmark/           # Hardware latency benchmark suite
│   ├── core/                # Audio FFT, beat detection, and animation engines
│   ├── gui/                 # Dashboard user interface
│   ├── hardware/            # Acer named pipe and ACPI communication layer
│   ├── service/             # Dedicated background sync service thread
│   ├── tray/                # Windows notification area system tray manager
│   └── utils/               # Windows autostart and registry utilities
├── build_exe.py             # PyInstaller packaging and release assembler
├── requirements.txt         # Project dependencies
└── test_component_audit.py  # Automated integration test suite
```

---

## License

This project is licensed under the MIT License.
