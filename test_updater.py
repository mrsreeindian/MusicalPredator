"""
Tests for the MusicalPredator In-App Update System (Phase 2A):
- SemVer parsing, normalization, and prerelease precedence
- GitHub Releases API parsing and error handling (offline, 403/429 rate-limit, 404, malformed JSON)
- Runtime mode detection (INSTALLED, PORTABLE, SOURCE) and asset selection
- Streaming HTTP download with progress callback, cancellation, size check, SHA-256 verification, and PE 'MZ' header check
- Portable & Installed Windows helper script generation
- UpdateConfig persistence and UpdateManager check/skip/download orchestration
- UpdateDialog UI rendering and state transitions
- Setup wizard CLI arg parsing & dynamic version binding
"""

import hashlib
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import tkinter as tk
import unittest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from predator_music_sync import __version__ as PKG_VERSION
from predator_music_sync.utils.updater import (
    RuntimeMode,
    UpdateCancelledError,
    UpdateConfig,
    UpdateManager,
    UpdateNetworkError,
    UpdateNotFoundError,
    UpdateRateLimitError,
    UpdateVerificationError,
    build_installed_update_script,
    build_portable_update_script,
    cleanup_stale_staging_dirs,
    compare_versions,
    detect_runtime_mode,
    download_asset,
    fetch_latest_release,
    is_newer_version,
    load_update_config,
    parse_github_release,
    parse_version,
    save_update_config,
    select_update_asset,
)
from predator_music_sync.gui.update_dialog import UpdateDialog
from predator_music_sync.gui.toolbar import PredatorMusicToolbar
from predator_music_sync.tray.tray_manager import PredatorTrayManager
from predator_music_sync.main import PredatorMusicSyncApp
from installer import setup_gui


class _MockReleaseHTTPServer:
    """Lightweight local HTTP server for deterministic release metadata & binary download tests."""

    def __init__(self, routes):
        self.routes = routes
        self._server = None
        self._thread = None
        self.base_url = ""

    def __enter__(self):
        routes = self.routes

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                spec = routes.get(self.path)
                if spec is None:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'{"message": "Not Found"}')
                    return

                status, headers, body = spec
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                if callable(body):
                    body(self.wfile)
                else:
                    self.wfile.write(body)

        self._server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
        port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


class TestSemVerAndReleaseParsing(unittest.TestCase):
    def test_semver_parsing_and_ordering(self):
        self.assertEqual(parse_version("v1.1.0").normalized, "1.1.0")
        self.assertEqual(parse_version("1.1").normalized, "1.1.0")
        self.assertTrue(is_newer_version("v1.1.0", "1.0.0"))
        self.assertFalse(is_newer_version("1.0.0", "v1.0.0"))
        self.assertFalse(is_newer_version("1.1.0-beta.1", "1.1.0"))
        self.assertTrue(is_newer_version("1.1.0", "1.1.0-beta.1"))
        self.assertEqual(compare_versions("v1.2.0-alpha.1", "1.2.0-beta.2"), -1)
        self.assertEqual(compare_versions("1.2.0-beta.2", "1.2.0-beta.11"), -1)
        self.assertEqual(compare_versions("v1.2.0+build99", "1.2.0"), 0)

        with self.assertRaises(ValueError):
            parse_version("not-a-version")

    def test_parse_github_release_extracts_assets_and_digest(self):
        sha = "a" * 64
        payload = {
            "tag_name": "v1.1.0",
            "name": "MusicalPredator v1.1.0",
            "body": "- Physical brightness sync\n- In-app updater",
            "html_url": "https://github.com/mrsreeindian/MusicalPredator/releases/tag/v1.1.0",
            "published_at": "2026-11-24T12:00:00Z",
            "assets": [
                {
                    "name": "MusicalPredator-Setup.exe",
                    "browser_download_url": "https://example.com/MusicalPredator-Setup.exe",
                    "size": 123456,
                    "digest": f"sha256:{sha}",
                },
                {
                    "name": "MusicalPredator.exe",
                    "browser_download_url": "https://example.com/MusicalPredator.exe",
                    "size": 99999,
                },
            ],
        }
        rel = parse_github_release(payload)
        self.assertEqual(rel.version, "1.1.0")
        self.assertEqual(len(rel.assets), 2)
        self.assertEqual(rel.assets[0].sha256, sha)
        self.assertIsNone(rel.assets[1].sha256)

        setup_asset = select_update_asset(rel, RuntimeMode.INSTALLED)
        portable_asset = select_update_asset(rel, RuntimeMode.PORTABLE)
        self.assertEqual(setup_asset.name, "MusicalPredator-Setup.exe")
        self.assertEqual(portable_asset.name, "MusicalPredator.exe")


class TestRuntimeModeAndScripts(unittest.TestCase):
    def test_detect_runtime_modes(self):
        self.assertEqual(detect_runtime_mode(frozen=False), RuntimeMode.SOURCE)

        with tempfile.TemporaryDirectory() as tmp:
            exe_path = os.path.join(tmp, "MusicalPredator.exe")
            with open(exe_path, "wb") as f:
                f.write(b"MZ")
            self.assertEqual(
                detect_runtime_mode(frozen=True, executable=exe_path, uninstall_install_location=""),
                RuntimeMode.PORTABLE,
            )

            # Registry InstallLocation match -> INSTALLED
            self.assertEqual(
                detect_runtime_mode(frozen=True, executable=exe_path, uninstall_install_location=tmp),
                RuntimeMode.INSTALLED,
            )

            # uninstall.bat marker -> INSTALLED
            with open(os.path.join(tmp, "uninstall.bat"), "w", encoding="utf-8") as f:
                f.write("@echo off\n")
            self.assertEqual(
                detect_runtime_mode(frozen=True, executable=exe_path, uninstall_install_location=""),
                RuntimeMode.INSTALLED,
            )

    def test_script_builders_include_pid_backup_and_silent_flags(self):
        portable_cmd = build_portable_update_script(
            pid=4321,
            downloaded_exe=r"C:\Temp\stage\MusicalPredator.exe",
            target_exe=r"C:\Apps\MusicalPredator\MusicalPredator.exe",
            staging_dir=r"C:\Temp\stage",
            relaunch_minimized=True,
        )
        self.assertIn("4321", portable_cmd)
        self.assertIn(".bak", portable_cmd)
        self.assertIn("--minimized", portable_cmd)
        self.assertIn("rd /S /Q", portable_cmd)

        installed_cmd = build_installed_update_script(
            pid=9876,
            downloaded_setup=r"C:\Temp\stage\MusicalPredator-Setup.exe",
            install_dir=r"C:\Users\Test\AppData\Local\Programs\MusicalPredator",
            staging_dir=r"C:\Temp\stage",
            relaunch_minimized=False,
        )
        self.assertIn("9876", installed_cmd)
        self.assertIn("--silent --dir=", installed_cmd)
        self.assertIn("--launch", installed_cmd)

    def test_setup_gui_version_and_cli_flags(self):
        self.assertEqual(setup_gui.APP_VERSION, PKG_VERSION)
        parsed = setup_gui.parse_installer_args(["--silent", "--dir=C:\\Custom\\Path", "--launch", "--minimized"])
        self.assertTrue(parsed["silent"])
        self.assertEqual(parsed["install_dir"], os.path.normpath("C:\\Custom\\Path"))
        self.assertTrue(parsed["launch"])
        self.assertTrue(parsed["minimized"])


class TestNetworkDownloadAndManager(unittest.TestCase):
    def test_fetch_errors_rate_limit_404_and_offline(self):
        routes = {
            "/rate_limit": (
                403,
                {"Content-Type": "application/json", "X-RateLimit-Remaining": "0"},
                b'{"message": "API rate limit exceeded"}',
            ),
            "/missing": (404, {"Content-Type": "application/json"}, b'{"message": "Not Found"}'),
        }
        with _MockReleaseHTTPServer(routes) as srv:
            with self.assertRaises(UpdateRateLimitError):
                fetch_latest_release(api_url=f"{srv.base_url}/rate_limit")
            with self.assertRaises(UpdateNotFoundError):
                fetch_latest_release(api_url=f"{srv.base_url}/missing")

        with self.assertRaises(UpdateNetworkError):
            fetch_latest_release(api_url="http://127.0.0.1:1/unreachable", timeout=0.5)

    def test_streaming_download_verification_and_cancel(self):
        valid_exe = b"MZ" + (b"\x90" * 131070)
        valid_sha = hashlib.sha256(valid_exe).hexdigest()
        bad_html = b"<html>error</html>"

        def _slow_stream(wfile):
            try:
                for _ in range(10):
                    wfile.write(b"MZ" + b"\x00" * 65534)
                    wfile.flush()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass

        routes = {
            "/latest": (
                200,
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "tag_name": "v1.1.0",
                        "name": "v1.1.0",
                        "body": "Bug fixes",
                        "html_url": "https://example.com/release",
                        "assets": [
                            {
                                "name": "MusicalPredator-Setup.exe",
                                "browser_download_url": "__BASE__/setup.exe",
                                "size": len(valid_exe),
                                "digest": f"sha256:{valid_sha}",
                            },
                            {
                                "name": "MusicalPredator.exe",
                                "browser_download_url": "__BASE__/app.exe",
                                "size": len(valid_exe),
                                "digest": f"sha256:{valid_sha}",
                            },
                        ],
                    }
                ).encode("utf-8"),
            ),
            "/setup.exe": (200, {"Content-Length": str(len(valid_exe))}, valid_exe),
            "/bad.exe": (200, {"Content-Length": str(len(bad_html))}, bad_html),
            "/slow.exe": (200, {"Content-Length": str(65536 * 10)}, _slow_stream),
        }

        with _MockReleaseHTTPServer(routes) as srv:
            # Patch placeholder URL inside /latest response
            routes["/latest"] = (
                200,
                {"Content-Type": "application/json"},
                routes["/latest"][2].replace(b"__BASE__", srv.base_url.encode("utf-8")),
            )

            with tempfile.TemporaryDirectory() as tmp:
                cfg_path = os.path.join(tmp, "cfg", "update_config.json")
                mgr = UpdateManager(
                    current_version="1.0.0",
                    config_path=cfg_path,
                    api_url=f"{srv.base_url}/latest",
                )
                res = mgr.check_for_updates()
                self.assertTrue(res.update_available)
                self.assertEqual(res.latest_version, "1.1.0")
                self.assertIsNotNone(res.selected_asset)

                progress_events = []
                dl_path = mgr.download_update(
                    res,
                    progress_cb=lambda dl, tot: progress_events.append((dl, tot)),
                    temp_root=tmp,
                )
                self.assertTrue(os.path.exists(dl_path))
                self.assertEqual(os.path.getsize(dl_path), len(valid_exe))
                self.assertGreaterEqual(len(progress_events), 2)
                self.assertEqual(progress_events[-1][0], len(valid_exe))

                # Skip version persistence
                mgr.skip_version("1.1.0")
                res_skipped = mgr.check_for_updates(respect_skip=True)
                self.assertFalse(res_skipped.update_available)
                self.assertTrue(res_skipped.is_skipped)

                reloaded = load_update_config(cfg_path)
                self.assertEqual(reloaded.skipped_version, "1.1.0")

                # SHA-256 mismatch failure
                bad_sha_asset = res.selected_asset
                bad_sha_asset.sha256 = "0" * 64
                with self.assertRaises(UpdateVerificationError):
                    download_asset(bad_sha_asset, os.path.join(tmp, "sha_fail"))

                # PE 'MZ' header failure
                bad_pe_asset = res.selected_asset
                bad_pe_asset.sha256 = None
                bad_pe_asset.size = len(bad_html)
                bad_pe_asset.download_url = f"{srv.base_url}/bad.exe"
                with self.assertRaises(UpdateVerificationError):
                    download_asset(bad_pe_asset, os.path.join(tmp, "pe_fail"))

                # Cancellation mid-download
                cancel_evt = threading.Event()
                cancel_evt.set()
                slow_asset = res.selected_asset
                slow_asset.size = 65536 * 10
                slow_asset.download_url = f"{srv.base_url}/slow.exe"
                with self.assertRaises(UpdateCancelledError):
                    download_asset(slow_asset, os.path.join(tmp, "cancel"), cancel_event=cancel_evt)

    def test_config_roundtrip_and_staging_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "update_config.json")
            cfg = UpdateConfig(auto_check_on_startup=False, skipped_version="1.2.3", last_checked_at=1234.5)
            self.assertTrue(save_update_config(cfg, cfg_path))
            loaded = load_update_config(cfg_path)
            self.assertFalse(loaded.auto_check_on_startup)
            self.assertEqual(loaded.skipped_version, "1.2.3")

            stale = os.path.join(tmp, "MusicalPredatorUpdate_1.0.1_xyz")
            os.makedirs(stale, exist_ok=True)
            old_ts = 1000.0
            os.utime(stale, (old_ts, old_ts))
            removed = cleanup_stale_staging_dirs(temp_root=tmp, max_age_seconds=60.0)
            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(stale))


class TestUpdateDialogUI(unittest.TestCase):
    def test_update_dialog_renders_with_result(self):
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tkinter display unavailable: {exc}")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                mgr = UpdateManager(current_version="1.0.0", config_path=os.path.join(tmp, "cfg.json"))
                rel = parse_github_release(
                    {
                        "tag_name": "v1.1.0",
                        "name": "MusicalPredator v1.1.0",
                        "body": "In-app update system",
                        "html_url": "https://github.com/mrsreeindian/MusicalPredator/releases/tag/v1.1.0",
                        "published_at": "2026-11-24T12:00:00Z",
                        "assets": [
                            {
                                "name": "MusicalPredator-Setup.exe",
                                "browser_download_url": "https://example.com/setup.exe",
                                "size": 1024 * 1024 * 12,
                            }
                        ],
                    }
                )
                from predator_music_sync.utils.updater import UpdateCheckResult

                res = UpdateCheckResult(
                    current_version="1.0.0",
                    latest_version="1.1.0",
                    update_available=True,
                    runtime_mode=RuntimeMode.INSTALLED,
                    release=rel,
                    selected_asset=rel.assets[0],
                )
                dlg = UpdateDialog(root, mgr, initial_result=res, auto_check=False)
                dlg.show()
                root.update_idletasks()
                self.assertIsNotNone(dlg.win)
                self.assertIn("1.1.0", dlg._lbl_status.cget("text"))
                self.assertIn("1.1.0", dlg._lbl_versions.cget("text"))
                dlg._on_close()
        finally:
            root.destroy()


class TestAppToolbarTrayWiring(unittest.TestCase):
    def test_toolbar_update_button_and_badge(self):
        triggered = []
        tb = PredatorMusicToolbar(on_check_updates=lambda: triggered.append(True))
        try:
            tb.create_window()
        except tk.TclError as exc:
            self.skipTest(f"Tkinter display unavailable: {exc}")

        try:
            self.assertIsNotNone(tb._btn_updates)
            self.assertIsNotNone(tb._lbl_status_version)
            self.assertIn(PKG_VERSION, tb._lbl_status_version.cget("text"))

            tb._btn_updates.invoke()
            self.assertEqual(len(triggered), 1)

            tb.set_update_available("1.1.0")
            self.assertEqual(tb._btn_updates.cget("text"), "UPDATE v1.1.0")
            self.assertIn("1.1.0 AVAILABLE", tb._lbl_status_version.cget("text"))

            tb.set_update_available(None)
            self.assertEqual(tb._btn_updates.cget("text"), "UPDATES")
        finally:
            tb._on_window_close()

    def test_tray_update_menu_item_and_callback(self):
        called = []
        tray = PredatorTrayManager(
            on_show_window=lambda: None,
            on_hide_window=lambda: None,
            on_toggle_lighting=lambda v: None,
            on_set_mode=lambda m: None,
            on_exit_app=lambda: None,
            on_check_updates=lambda: called.append(True),
        )
        menu = tray.build_menu()
        labels = [str(m.text) for m in menu.items]
        self.assertTrue(any("Check for Updates" in lbl for lbl in labels))

        tray.set_update_available("1.1.0")
        menu_avail = tray.build_menu()
        labels_avail = [str(m.text) for m in menu_avail.items]
        self.assertTrue(any("Update Available (v1.1.0)" in lbl for lbl in labels_avail))

        tray._handle_check_updates(None, None)
        self.assertEqual(len(called), 1)

    def test_main_app_wires_updater_to_gui_and_tray(self):
        app = PredatorMusicSyncApp(prefer_virtual=True)
        try:
            self.assertIsNotNone(app.update_manager)
            self.assertEqual(app.gui.on_check_updates, app.open_update_dialog)
            self.assertEqual(app.tray.on_check_updates, app.open_update_dialog)
            self.assertEqual(app.update_manager.on_prepare_shutdown, app.exit_completely)
        finally:
            app.exit_completely()


if __name__ == "__main__":
    unittest.main(verbosity=2)
