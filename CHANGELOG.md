# Changelog

All notable changes to the MusicalPredator project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-11-25

### Stability, Projection Fidelity, Physical EC Brightness & In-App Updater - MusicalPredator V1.1.0

### Added
- **Physical EC Keyboard Brightness Control & Hotkey Sync**:
  - Added direct Embedded Controller (EC) brightness read and write via `\\.\pipe\AcerLightingService_NamedPipe` (Commands `1`, `2`, and `3`) in `AcerLightingNamedPipeBackend`.
  - Added anti-double-dimming RGB scaling so software brightness and hardware EC brightness (`0..100%`) stay synchronized without compounding dimness.
  - Added bidirectional `Fn+F9` / `Fn+F10` physical hotkey sync polling so hardware brightness changes reflect immediately in the GUI slider, `EC SYNC` badge, and system tray.
  - Extended hardware brightness control across Windows WMI (`acer_wmi_windows.py`), Linux sysfs (`acer_linux.py`), and Virtual (`virtual_keyboard.py`) backends.
  - Added `EC SYNC` indicator badge in the GUI toolbar and a **Brightness** submenu (`0%`, `25%`, `50%`, `75%`, `100%`) in the system tray menu.

- **In-App GitHub Releases Update System**:
  - Added SemVer 2.0.0 parser, comparator, and GitHub Releases checker (`mrsreeindian/MusicalPredator`) with clean offline, 404, and rate-limit error handling (`predator_music_sync/utils/updater.py`).
  - Added dark-mode `UpdateDialog` (`predator_music_sync/gui/update_dialog.py`) with release notes viewer, **Skip This Version**, **Auto-check on startup** preference persistence (`%LOCALAPPDATA%\MusicalPredator\update_config.json`), and a main-thread Tkinter UI dispatch queue.
  - Added streaming 64 KB downloads with live progress, cancellation, file-size check, PE `MZ` header validation, and SHA-256 checksum verification.
  - Added detached post-exit `.cmd` self-updater supporting both Portable EXE replacement (with automatic rollback on failure) and silent Installed setup upgrades (`MusicalPredator-Setup.exe --silent --dir=... --launch`) using `cmd.exe` quote-doubled PID waiting.
  - Added toolbar **UPDATES** button / version badge indicator and tray **Check for Updates...** menu item.

- **Automated Verification Suites**:
  - Added `test_tray_longevity.py`, `test_keyboard_projection.py`, `test_physical_brightness.py`, and `test_updater.py` covering long-running tray stability, keyboard projection fidelity, EC brightness sync, and in-app update flows.

### Fixed
- **5-Minute Close-to-Tray Malfunction & Background Stability**:
  - Replaced cross-thread Tkinter UI updates with a thread-safe main-loop dispatch queue so background threads never invoke Tcl while minimized or hidden to tray.
  - Added Windows EcoQoS (`ProcessPowerThrottling`) opt-out via `SetProcessInformation` and `WM_POWERBROADCAST` (`PBT_APMRESUMEAUTOMATIC`, `PBT_APMRESUMESUSPEND`, `PBT_POWERSETTINGCHANGE`) sleep/resume and display-on recovery hooks.
  - Added `PeekNamedPipe` health checks, broken-pipe/no-data error handling, write failure thresholds, and automatic pipe worker reconnection in `AcerLightingNamedPipeBackend`.
  - Added stalled WASAPI audio stream detection and automatic recovery (`recover_stream`) alongside safe device switching.
  - Replaced stdin-bound PowerShell invocation with a persistent `-File` SMTC media worker with stall/exit recovery.
  - Made `pystray` tray menu dispatch and deferred icon updates thread-safe.

- **Keyboard Projection & Animation Fidelity**:
  - Aligned stepped 4-zone polygons across rows in both `VirtualKeyboardBackend` and `toolbar.py` to match physical Predator keyboard hardware zones.
  - Completed the 6-row numpad layout (`+`, `Enter`, `0`, `.`) and fixed keycap symbols, modifier widths, and arrow legends.
  - Fixed 3-zone, 1-zone, and Per-Key (`PH16-71`, `PH16-72`, `PT516-52`) projection parity with actual hardware frame outputs.
  - Replaced UI-only animation drift with smooth exponential decay (`1 - exp(-dt / tau)`) and real 60 FPS hardware/brightness-synchronized projection.

---

## [1.0.0] - 2026-11-25

### Initial Production Release - MusicalPredator V1.0.0

MusicalPredator delivers real-time audio-reactive RGB lighting synchronization and dynamic album art extraction for Acer Predator and Nitro gaming laptops.

### Added
- **Direct Hardware Driver**:
  - Implemented low-latency user-space communication with `\\.\pipe\AcerLightingService_NamedPipe`.
  - Added non-blocking asynchronous dispatch with latest-frame latching to guarantee < 0.02ms pipe latency.
  - Implemented auto-reconnecting worker thread to survive vendor service restarts seamlessly.
  - Added `Fix-AcerLightingService.bat` for instant one-click recovery and profile cache purging.

- **Universal Hardware Compatibility Layer**:
  - Automatic DMI/WMI BIOS laptop hardware model detection.
  - Native 4-Zone RGB support for Predator Helios Neo 16 (`PHN16-71`, `PHN16-72`), Predator Helios 300 (`PH315-55`), and Acer Nitro 5 (`AN515-58`).
  - Native Per-Key RGB gradient mapping (84-key layout) for Predator Helios 16 (`PH16-71`, `PH16-72`) and Predator Triton (`PT516-52`).
  - Multi-device auxiliary lighting synchronization for Rear Lightbars (12 LEDs) and Lid Logos.

- **Audio & Beat Engine**:
  - Windows WASAPI loopback audio capture with silence gating and decay.
  - High-precision Fast Fourier Transform (FFT) decomposing into 4 frequency bands: Sub-Bass, Low-Mids, High-Mids, and Treble.
  - Transient beat-detection latch with priority hardware override.
  - Dynamic audio device switching without service restart.

- **Material Design 3 Album Art Color Extraction**:
  - Live color palette extraction from active media playback (Spotify, Apple Music, YouTube, Tidal, browsers).
  - Material You Color dynamic tonal mapping produces rich, high-saturation LED underglow.
  - Seamless artwork caching and cover retention preventing abrupt white fallback on track changes.

- **14 Lighting Animation Modes**:
  - 12 Dynamic Audio Reactive Modes: Spectrum Equalizer, EDM Strobe, Ripple Wave, Scanner, Beat Pulse, Smooth Wave, Cyberpunk Shift, Plasma Vortex, Dual Split, Aurora Borealis, Firefly, Starlight Sparkle.
  - 2 Static Album Art Modes: Static Album Art (zero-motion steady underglow) and Static Album Dominant.

- **Power Management & Battery Saver**:
  - AC Power Profile: 60 FPS pacing, full dynamic flash, maximum visual fidelity.
  - Battery Power Profile: Automatic switch to Static Album Art, 30 FPS eco pacing, brightness capped at 50%.
  - Windows Battery Saver Integration: Instantly extinguishes physical LEDs (0,0,0) and suspends audio threads (0.0% CPU usage) when Battery Saver is engaged.

- **UI & System Tray Suite**:
  - High-DPI Per-Monitor V2 dark-mode GUI dashboard with custom Predator aesthetics.
  - Interactive 98-key virtual keyboard mirror with live underglow preview.
  - Real-time 4-band audio EQ visualizer and VU meters.
  - System notification area (tray) integration with quick-switch right-click context menu.
  - Minimize-to-tray and close-to-tray lifecycle management with CPU loop idling (~0.1% CPU).
  - Optional Windows startup integration (`HKCU\...\Run\MusicalPredator`).

- **Packaging & CI/CD**:
  - PyInstaller automated multi-target compilation via `build_exe.py`.
  - Standalone GUI Setup Wizard (`MusicalPredator-Setup.exe`).
  - Standalone Portable Executable (`MusicalPredator.exe`).
  - Zip distribution package (`MusicalPredator-v1.0.0-Windows-x64.zip`).
  - GitHub Actions automated build and release workflow (`.github/workflows/build.yml`).
  - Comprehensive 8-part automated test and audit suite (`test_component_audit.py`).
