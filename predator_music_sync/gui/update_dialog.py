"""
Predator Dark-themed In-App Update Center Dialog.

Provides:
- Current vs latest version comparison and runtime mode badge
- Scrollable release notes viewer
- Streaming download progress bar with MB/s & percentage
- One-click "Update & Restart", "Skip This Version", "Auto-check on startup",
  and clean error/rate-limit/source-mode handling.
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext
from typing import Callable, Optional

from ..utils.updater import (
    RuntimeMode,
    UpdateCancelledError,
    UpdateCheckResult,
    UpdateError,
    UpdateManager,
    open_release_page,
)


class UpdateDialog:
    """Modal/top-level Update Center dialog styled in Predator Dark."""

    BG_ROOT = "#000000"
    SURFACE_PANEL = "#0A0A0A"
    SURFACE_CARD = "#111111"
    SURFACE_INPUT = "#161616"
    SURFACE_ACTIVE = "#1E1E1E"
    BORDER_HAIRLINE = "#1F1F1F"
    ACCENT_YELLOW = "#FFD100"
    ACCENT_GREEN = "#00E676"
    ACCENT_WARN = "#FF9900"
    ACCENT_ERR = "#FF5533"
    TEXT_WHITE = "#FFFFFF"
    TEXT_SECONDARY = "#999999"
    TEXT_MUTED = "#666666"
    FONT_FAMILY = "Segoe UI"
    FONT_MONO = "Consolas"

    def __init__(
        self,
        parent: tk.Misc,
        update_manager: UpdateManager,
        initial_result: Optional[UpdateCheckResult] = None,
        auto_check: bool = True,
        on_result_cb: Optional[Callable[[Optional[UpdateCheckResult]], None]] = None,
    ):
        self.parent = parent
        self.manager = update_manager
        self._result: Optional[UpdateCheckResult] = initial_result
        self._auto_check = auto_check
        self.on_result_cb = on_result_cb

        self.win: Optional[tk.Toplevel] = None
        self._is_checking = False
        self._is_downloading = False
        self._cancel_event: Optional[threading.Event] = None

        # Widgets
        self._lbl_status: Optional[tk.Label] = None
        self._lbl_versions: Optional[tk.Label] = None
        self._lbl_meta: Optional[tk.Label] = None
        self._txt_notes: Optional[scrolledtext.ScrolledText] = None
        self._progress_track: Optional[tk.Frame] = None
        self._progress_fill: Optional[tk.Frame] = None
        self._lbl_progress: Optional[tk.Label] = None
        self._btn_primary: Optional[tk.Button] = None
        self._btn_check: Optional[tk.Button] = None
        self._btn_skip: Optional[tk.Button] = None
        self._btn_browser: Optional[tk.Button] = None
        self._btn_close: Optional[tk.Button] = None
        self._var_auto_check: Optional[tk.BooleanVar] = None

    def show(self) -> None:
        if self.win and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self.win = tk.Toplevel(self.parent)
        self.win.title("MusicalPredator // Software Update")
        self.win.configure(bg=self.BG_ROOT)
        self.win.resizable(False, False)

        win_w, win_h = 560, 470
        try:
            sx = self.win.winfo_screenwidth()
            sy = self.win.winfo_screenheight()
            px = max(0, (sx - win_w) // 2)
            py = max(0, (sy - win_h) // 2)
            self.win.geometry(f"{win_w}x{win_h}+{px}+{py}")
        except Exception:
            self.win.geometry(f"{win_w}x{win_h}")

        self._apply_window_icon()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.win.transient(self.parent)
        except Exception:
            pass

        self._build_ui()

        if self._result is not None:
            self._apply_check_result(self._result)
        elif self._auto_check:
            self.start_check()

    def _apply_window_icon(self) -> None:
        if not self.win:
            return
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "assets", "predator_icon.ico"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "predator_icon.ico"),
            os.path.join(os.path.dirname(sys.executable), "assets", "predator_icon.ico"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                try:
                    self.win.iconbitmap(c)
                    break
                except Exception:
                    pass

    def _build_ui(self) -> None:
        assert self.win is not None

        # Header
        header = tk.Frame(
            self.win, bg=self.SURFACE_PANEL, height=48,
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE
        )
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Frame(header, bg=self.ACCENT_YELLOW, width=4).pack(side="left", fill="y")

        h_left = tk.Frame(header, bg=self.SURFACE_PANEL)
        h_left.pack(side="left", padx=12, fill="y")
        tk.Label(
            h_left, text="MUSICALPREDATOR // SOFTWARE UPDATE",
            font=(self.FONT_FAMILY, 10, "bold"), fg=self.TEXT_WHITE, bg=self.SURFACE_PANEL
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(
            h_left, text=f"Installed: v{self.manager.current_version}  •  Mode: {self.manager.runtime_mode.label}",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL
        ).pack(anchor="w")

        # Main container
        body = tk.Frame(self.win, bg=self.BG_ROOT)
        body.pack(fill="both", expand=True, padx=14, pady=10)

        # Status Card
        status_card = tk.Frame(
            body, bg=self.SURFACE_CARD,
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE
        )
        status_card.pack(fill="x", pady=(0, 8))

        s_in = tk.Frame(status_card, bg=self.SURFACE_CARD)
        s_in.pack(fill="x", padx=12, pady=10)

        self._lbl_status = tk.Label(
            s_in, text="Ready to check for updates.",
            font=(self.FONT_FAMILY, 10, "bold"), fg=self.ACCENT_YELLOW, bg=self.SURFACE_CARD, anchor="w"
        )
        self._lbl_status.pack(fill="x")

        self._lbl_versions = tk.Label(
            s_in, text=f"Current Version: v{self.manager.current_version}",
            font=(self.FONT_MONO, 8), fg=self.TEXT_WHITE, bg=self.SURFACE_CARD, anchor="w"
        )
        self._lbl_versions.pack(fill="x", pady=(2, 0))

        self._lbl_meta = tk.Label(
            s_in, text="Source: GitHub Releases (mrsreeindian/MusicalPredator)",
            font=(self.FONT_FAMILY, 7), fg=self.TEXT_MUTED, bg=self.SURFACE_CARD, anchor="w"
        )
        self._lbl_meta.pack(fill="x", pady=(2, 0))

        # Release Notes
        tk.Label(
            body, text="RELEASE NOTES",
            font=(self.FONT_FAMILY, 7, "bold"), fg=self.TEXT_SECONDARY, bg=self.BG_ROOT, anchor="w"
        ).pack(fill="x", pady=(0, 3))

        self._txt_notes = scrolledtext.ScrolledText(
            body, height=10, bg="#080808", fg="#D8D8D8",
            font=(self.FONT_FAMILY, 8), bd=0, wrap="word",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            padx=8, pady=6
        )
        self._txt_notes.pack(fill="both", expand=True, pady=(0, 8))
        self._set_notes_text("Click 'Check Now' to inspect the latest MusicalPredator release.")

        # Download Progress Area
        prog_box = tk.Frame(body, bg=self.SURFACE_PANEL, highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE)
        prog_box.pack(fill="x", pady=(0, 8))

        prog_in = tk.Frame(prog_box, bg=self.SURFACE_PANEL)
        prog_in.pack(fill="x", padx=10, pady=8)

        self._lbl_progress = tk.Label(
            prog_in, text="Idle",
            font=(self.FONT_MONO, 7), fg=self.TEXT_SECONDARY, bg=self.SURFACE_PANEL, anchor="w"
        )
        self._lbl_progress.pack(fill="x", pady=(0, 4))

        self._progress_track = tk.Frame(
            prog_in, bg="#181818", height=10,
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE
        )
        self._progress_track.pack(fill="x")
        self._progress_track.pack_propagate(False)

        self._progress_fill = tk.Frame(self._progress_track, bg=self.ACCENT_YELLOW, width=0)
        self._progress_fill.pack(side="left", fill="y")

        # Footer Preferences + Actions
        pref_row = tk.Frame(body, bg=self.BG_ROOT)
        pref_row.pack(fill="x", pady=(0, 8))

        self._var_auto_check = tk.BooleanVar(value=self.manager.config.auto_check_on_startup)
        chk_auto = tk.Checkbutton(
            pref_row,
            text="Check for updates automatically on startup",
            variable=self._var_auto_check,
            font=(self.FONT_FAMILY, 8),
            fg=self.TEXT_SECONDARY,
            bg=self.BG_ROOT,
            activebackground=self.BG_ROOT,
            activeforeground=self.TEXT_WHITE,
            selectcolor=self.SURFACE_INPUT,
            command=self._on_toggle_auto_check,
        )
        chk_auto.pack(side="left")

        btn_row = tk.Frame(body, bg=self.BG_ROOT)
        btn_row.pack(fill="x")

        self._btn_check = tk.Button(
            btn_row, text="CHECK NOW", font=(self.FONT_FAMILY, 8, "bold"),
            bg=self.SURFACE_INPUT, fg=self.TEXT_WHITE, bd=0, padx=12, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self.start_check
        )
        self._btn_check.pack(side="left", padx=(0, 6))

        self._btn_skip = tk.Button(
            btn_row, text="SKIP VERSION", font=(self.FONT_FAMILY, 8, "bold"),
            bg=self.SURFACE_INPUT, fg=self.TEXT_MUTED, bd=0, padx=10, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            state="disabled", command=self._on_skip_version
        )
        self._btn_skip.pack(side="left", padx=(0, 6))

        self._btn_browser = tk.Button(
            btn_row, text="RELEASE PAGE", font=(self.FONT_FAMILY, 8, "bold"),
            bg=self.SURFACE_INPUT, fg=self.TEXT_SECONDARY, bd=0, padx=10, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._on_open_release_page
        )
        self._btn_browser.pack(side="left")

        self._btn_close = tk.Button(
            btn_row, text="CLOSE", font=(self.FONT_FAMILY, 8, "bold"),
            bg=self.SURFACE_INPUT, fg=self.TEXT_SECONDARY, bd=0, padx=12, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground=self.BORDER_HAIRLINE,
            command=self._on_close
        )
        self._btn_close.pack(side="right", padx=(6, 0))

        self._btn_primary = tk.Button(
            btn_row, text="UPDATE & RESTART", font=(self.FONT_FAMILY, 8, "bold"),
            bg=self.ACCENT_YELLOW, fg="#000000", bd=0, padx=14, pady=5, cursor="hand2",
            state="disabled", command=self._on_primary_action
        )
        self._btn_primary.pack(side="right")

    def _safe_ui(self, fn) -> None:
        if self.win and self.win.winfo_exists():
            try:
                self.win.after(0, fn)
            except Exception:
                pass

    def _set_notes_text(self, text: str) -> None:
        if not self._txt_notes:
            return
        self._txt_notes.config(state="normal")
        self._txt_notes.delete("1.0", tk.END)
        self._txt_notes.insert("1.0", text or "No release notes provided.")
        self._txt_notes.config(state="disabled")

    def _set_progress(self, downloaded: int, total: int, status_text: Optional[str] = None) -> None:
        if not (self._progress_track and self._progress_fill and self._lbl_progress):
            return
        if total > 0:
            pct = max(0.0, min(100.0, (downloaded / total) * 100.0))
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            msg = status_text or f"Downloading... {pct:.0f}% ({dl_mb:.2f} / {tot_mb:.2f} MB)"
        else:
            pct = 0.0
            dl_mb = downloaded / (1024 * 1024)
            msg = status_text or f"Downloading... {dl_mb:.2f} MB"

        self._lbl_progress.config(text=msg)
        try:
            self._progress_track.update_idletasks()
            track_w = max(0, self._progress_track.winfo_width() - 2)
            self._progress_fill.config(width=int(track_w * (pct / 100.0)))
        except Exception:
            pass

    def start_check(self) -> None:
        if self._is_checking or self._is_downloading:
            return
        self._is_checking = True
        if self._lbl_status:
            self._lbl_status.config(text="Checking GitHub Releases for updates...", fg=self.ACCENT_YELLOW)
        if self._lbl_progress:
            self._lbl_progress.config(text="Contacting api.github.com...")
        if self._btn_check:
            self._btn_check.config(state="disabled")
        if self._btn_primary:
            self._btn_primary.config(state="disabled")
        if self._btn_skip:
            self._btn_skip.config(state="disabled")

        def _worker():
            try:
                res = self.manager.check_for_updates(respect_skip=False)
                self._safe_ui(lambda: self._on_check_success(res))
            except Exception as exc:
                err_msg = str(exc)
                self._safe_ui(lambda: self._on_check_error(err_msg))

        threading.Thread(target=_worker, daemon=True, name="UpdateCheckWorker").start()

    def _on_check_success(self, res: UpdateCheckResult) -> None:
        self._is_checking = False
        if self._btn_check:
            self._btn_check.config(state="normal")
        self._apply_check_result(res)
        if self.on_result_cb:
            try:
                self.on_result_cb(res)
            except Exception:
                pass

    def _on_check_error(self, err_msg: str) -> None:
        self._is_checking = False
        if self._btn_check:
            self._btn_check.config(state="normal")
        if self._lbl_status:
            self._lbl_status.config(text="Update check failed", fg=self.ACCENT_ERR)
        if self._lbl_progress:
            self._lbl_progress.config(text=err_msg, fg=self.ACCENT_ERR)
        self._set_notes_text(
            f"Could not complete update check:\n\n{err_msg}\n\n"
            "You can retry with 'Check Now' or open the GitHub Releases page directly."
        )

    def _apply_check_result(self, res: UpdateCheckResult) -> None:
        self._result = res
        rel = res.release
        has_newer = res.latest_version != res.current_version and res.update_available

        if self._lbl_versions:
            self._lbl_versions.config(
                text=f"Current: v{res.current_version}   |   Latest: v{res.latest_version}"
            )

        asset_desc = (
            f"{res.selected_asset.name} ({res.selected_asset.size / (1024 * 1024):.1f} MB)"
            if res.selected_asset and res.selected_asset.size > 0
            else (res.selected_asset.name if res.selected_asset else "No binary asset attached")
        )
        pub_date = rel.published_at[:10] if rel.published_at else "Unknown date"
        if self._lbl_meta:
            self._lbl_meta.config(text=f"Release: {rel.name}  •  Published: {pub_date}  •  Package: {asset_desc}")

        self._set_notes_text(rel.body or f"Release {rel.tag_name}")

        if has_newer:
            skip_note = " (previously skipped)" if res.is_skipped else ""
            if self._lbl_status:
                self._lbl_status.config(
                    text=f"Update Available: v{res.latest_version}{skip_note}",
                    fg=self.ACCENT_GREEN
                )
            if self._btn_skip:
                self._btn_skip.config(state="normal", fg=self.TEXT_WHITE)
            if self._btn_primary:
                if res.runtime_mode == RuntimeMode.SOURCE:
                    btn_text = "DOWNLOAD INSTALLER" if res.selected_asset else "OPEN RELEASE PAGE"
                else:
                    btn_text = "UPDATE & RESTART" if res.selected_asset else "OPEN RELEASE PAGE"
                self._btn_primary.config(text=btn_text, state="normal", bg=self.ACCENT_YELLOW, fg="#000000")
            if self._lbl_progress:
                msg = (
                    "Running from Python source: click Download Installer or Open Release Page."
                    if res.runtime_mode == RuntimeMode.SOURCE
                    else f"Ready to download {asset_desc}."
                )
                self._lbl_progress.config(text=msg, fg=self.TEXT_SECONDARY)
        else:
            if self._lbl_status:
                self._lbl_status.config(text="You are on the latest version.", fg=self.ACCENT_YELLOW)
            if self._btn_skip:
                self._btn_skip.config(state="disabled", fg=self.TEXT_MUTED)
            if self._btn_primary:
                self._btn_primary.config(text="UP TO DATE", state="disabled")
            if self._lbl_progress:
                self._lbl_progress.config(text="No update required.", fg=self.TEXT_SECONDARY)

    def _on_primary_action(self) -> None:
        if self._is_downloading:
            if self._cancel_event:
                self._cancel_event.set()
            return

        if not self._result:
            return

        if not self._result.selected_asset:
            open_release_page(self._result.release.html_url, repo=self.manager.repo)
            return

        self._start_download_and_apply(self._result)

    def _start_download_and_apply(self, res: UpdateCheckResult) -> None:
        self._is_downloading = True
        self._cancel_event = threading.Event()
        if self._btn_check:
            self._btn_check.config(state="disabled")
        if self._btn_skip:
            self._btn_skip.config(state="disabled")
        if self._btn_primary:
            self._btn_primary.config(text="CANCEL DOWNLOAD", bg=self.ACCENT_ERR, fg=self.TEXT_WHITE, state="normal")
        if self._lbl_status:
            self._lbl_status.config(text=f"Downloading v{res.latest_version}...", fg=self.ACCENT_YELLOW)
        if self._lbl_progress:
            self._lbl_progress.config(fg=self.TEXT_SECONDARY)

        def _progress(dl: int, total: int) -> None:
            self._safe_ui(lambda: self._set_progress(dl, total))

        def _worker() -> None:
            try:
                path = self.manager.download_update(
                    res,
                    progress_cb=_progress,
                    cancel_event=self._cancel_event,
                )
                self._safe_ui(lambda: self._on_download_complete(path, res))
            except UpdateCancelledError:
                self._safe_ui(self._on_download_cancelled)
            except Exception as exc:
                err = str(exc)
                self._safe_ui(lambda: self._on_download_error(err))

        threading.Thread(target=_worker, daemon=True, name="UpdateDownloadWorker").start()

    def _on_download_complete(self, downloaded_path: str, res: UpdateCheckResult) -> None:
        self._is_downloading = False
        self._set_progress(1, 1, "Download verified! Launching updater and restarting...")
        if self._lbl_status:
            self._lbl_status.config(text="Applying update...", fg=self.ACCENT_GREEN)
        if self._btn_primary:
            self._btn_primary.config(state="disabled", text="RESTARTING...")

        try:
            self.manager.apply_update(downloaded_path)
            if res.runtime_mode == RuntimeMode.SOURCE:
                if self._lbl_status:
                    self._lbl_status.config(text="Installer launched.", fg=self.ACCENT_GREEN)
                if self._lbl_progress:
                    self._lbl_progress.config(text=f"Launched: {os.path.basename(downloaded_path)}", fg=self.ACCENT_GREEN)
                if self._btn_check:
                    self._btn_check.config(state="normal")
                if self._btn_primary:
                    self._btn_primary.config(text="DOWNLOAD INSTALLER", state="normal", bg=self.ACCENT_YELLOW, fg="#000000")
        except UpdateError as exc:
            self._on_download_error(str(exc))

    def _on_download_cancelled(self) -> None:
        self._is_downloading = False
        self._set_progress(0, 1, "Download cancelled.")
        if self._lbl_status:
            self._lbl_status.config(text="Download cancelled", fg=self.ACCENT_WARN)
        if self._btn_check:
            self._btn_check.config(state="normal")
        if self._result:
            self._apply_check_result(self._result)

    def _on_download_error(self, err_msg: str) -> None:
        self._is_downloading = False
        self._set_progress(0, 1, f"Update failed: {err_msg}")
        if self._lbl_progress:
            self._lbl_progress.config(fg=self.ACCENT_ERR)
        if self._lbl_status:
            self._lbl_status.config(text="Update failed", fg=self.ACCENT_ERR)
        if self._btn_check:
            self._btn_check.config(state="normal")
        if self._result and self._btn_primary:
            self._btn_primary.config(text="RETRY UPDATE", bg=self.ACCENT_YELLOW, fg="#000000", state="normal")

    def _on_skip_version(self) -> None:
        if not self._result:
            return
        self.manager.skip_version(self._result.latest_version)
        self._result.is_skipped = True
        if self._lbl_status:
            self._lbl_status.config(text=f"Skipped v{self._result.latest_version}", fg=self.TEXT_SECONDARY)
        if self._btn_skip:
            self._btn_skip.config(state="disabled", fg=self.TEXT_MUTED)
        if self.on_result_cb:
            try:
                self.on_result_cb(self._result)
            except Exception:
                pass

    def _on_toggle_auto_check(self) -> None:
        if self._var_auto_check is not None:
            self.manager.set_auto_check(bool(self._var_auto_check.get()))

    def _on_open_release_page(self) -> None:
        url = self._result.release.html_url if self._result else None
        open_release_page(url, repo=self.manager.repo)

    def _on_close(self) -> None:
        if self._is_downloading and self._cancel_event:
            self._cancel_event.set()
        if self.win and self.win.winfo_exists():
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None
