# Changelog

All notable changes to the MusicalPredator project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
