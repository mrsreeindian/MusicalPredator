# MusicalPredator v1.1.0 Release

**MusicalPredator v1.1.0** is a major stability, hardware-control, and quality-of-life update to the real-time audio-reactive RGB synchronization and Material Design 3 album art lighting engine for Acer Predator and Nitro laptops.

---

### What's New in v1.1.0

- **Long-Running Tray Stability (5-Minute Malfunction Fixed)**:
  - Thread-safe main-loop Tkinter UI queue eliminating cross-thread Tcl stalls when minimized or closed to the system tray.
  - Windows EcoQoS power-throttling opt-out (`ProcessPowerThrottling`) and `WM_POWERBROADCAST` sleep/resume & display-wake recovery.
  - Named-pipe health checks (`PeekNamedPipe`) with automatic worker reconnection, stalled WASAPI stream recovery, and a persistent `-File` PowerShell SMTC worker.
- **True-to-Hardware Keyboard Projection**:
  - Aligned stepped 4-zone polygons, complete 6-row numpad (`+`, `Enter`, `0`, `.`), and corrected keycap legends and arrow symbols.
  - Accurate 3-zone, 1-zone, and Per-Key (`PH16-71`, `PH16-72`, `PT516-52`) projection parity with real 60 FPS hardware/brightness sync and smooth exponential decay.
- **Physical EC Keyboard Brightness & `Fn+F9` / `Fn+F10` Sync**:
  - Direct Embedded Controller (EC) brightness read/write over `\\.\pipe\AcerLightingService_NamedPipe` with anti-double-dimming RGB scaling.
  - Bidirectional `Fn+F9` / `Fn+F10` hotkey synchronization reflected live in the GUI slider, `EC SYNC` indicator badge, and tray **Brightness** submenu (`0%`–`100%`).
- **In-App GitHub Releases Updater**:
  - Built-in SemVer update checker (`mrsreeindian/MusicalPredator`) with dark-mode `UpdateDialog`, release notes preview, skip-version persistence, and startup auto-check toggle.
  - Streaming downloads with progress, cancellation, PE `MZ` header and SHA-256 verification, and detached post-exit self-updating for both Portable EXE and silent Installed Setup upgrades.

---

### Core Features

- **Direct Hardware Driver**: User-space communication via `\\.\pipe\AcerLightingService_NamedPipe` with non-blocking dispatch (< 0.02ms latency) and auto-reconnecting worker thread.
- **Universal Hardware Support**: Automatic BIOS/WMI model detection supporting 4-Zone, 3-Zone, and Per-Key RGB across Acer Predator Helios Neo 16, Helios 16/18, Helios 300, Triton 16/300/500, and Nitro 5/16/17.
- **Auxiliary Lighting Sync**: Simultaneous multi-device lighting control for Rear Lightbars (12 LEDs) and Lid Logos.
- **Material Design 3 Album Art**: Dynamic tonal palette extraction using Material You algorithms from active Spotify, Apple Music, YouTube, and browser playback.
- **14 Lighting Modes**: 12 audio-reactive visualizer modes + 2 steady static album art underglow modes.
- **Intelligent Power Profiles**: 60 FPS on AC power, automatic 30 FPS eco mode with brightness cap on battery, and zero-power/zero-CPU sleep on Windows Battery Saver.

---

### Release Downloads

| File | Type | Description |
| :--- | :--- | :--- |
| **`MusicalPredator-Setup.exe`** | Installer | Modern GUI setup wizard with desktop shortcuts, silent upgrade support & uninstaller |
| **`MusicalPredator.exe`** | Standalone | Portable single-file executable (no installation required) |
| **`MusicalPredator-v1.1.0-Windows-x64.zip`** | Archive | Full release distribution package with batch launchers & utilities |

---

### Verification & Checksums
All build assets have passed the 5 automated verification and audit test suites (`test_component_audit.py`, `test_tray_longevity.py`, `test_keyboard_projection.py`, `test_physical_brightness.py`, and `test_updater.py`).
