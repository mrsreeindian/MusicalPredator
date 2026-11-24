"""
In-App Update System for MusicalPredator.

Handles:
- SemVer 2.0.0 parsing & comparison (supports 'v1.1.0', '1.1.0', prereleases, build metadata)
- GitHub Releases metadata fetching ('mrsreeindian/MusicalPredator') with clean offline/rate-limit errors
- Runtime mode detection (Installed via Setup vs Portable EXE vs Python Source)
- Streaming downloads with progress callback, cancellation, size, PE 'MZ', and SHA-256 verification
- Detached post-exit update application (in-place EXE swap with rollback or silent Setup upgrade)
- Persistent update preferences (%LOCALAPPDATA%\\MusicalPredator\\update_config.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import __version__ as APP_VERSION

DEFAULT_REPO = "mrsreeindian/MusicalPredator"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_RELEASES_PAGE_URL = "https://github.com/{repo}/releases"
SETUP_ASSET_NAME = "MusicalPredator-Setup.exe"
PORTABLE_ASSET_NAME = "MusicalPredator.exe"
STAGING_DIR_PREFIX = "MusicalPredatorUpdate_"
UNINSTALL_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicalPredator"

_SEMVER_RE = re.compile(
    r"^[vV]?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """Base error for all updater failures."""


class UpdateNetworkError(UpdateError):
    """Raised on offline, DNS, timeout, or non-rate-limit HTTP errors."""


class UpdateRateLimitError(UpdateError):
    """Raised when GitHub API rate limit (HTTP 403/429) is reached."""


class UpdateNotFoundError(UpdateError):
    """Raised when no published release exists (HTTP 404)."""


class UpdateVerificationError(UpdateError):
    """Raised when downloaded payload fails size, header, or SHA-256 verification."""


class UpdateCancelledError(UpdateError):
    """Raised when an active download is cancelled by the user."""


class RuntimeMode(str, Enum):
    INSTALLED = "installed"
    PORTABLE = "portable"
    SOURCE = "source"

    @property
    def label(self) -> str:
        if self == RuntimeMode.INSTALLED:
            return "Installed App"
        if self == RuntimeMode.PORTABLE:
            return "Portable Executable"
        return "Python Source"


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: Tuple[Tuple[int, Any], ...] = ()
    raw: str = ""

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    @property
    def normalized(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            pre = ".".join(str(part[1]) for part in self.prerelease)
            return f"{base}-{pre}"
        return base

    def sort_key(self) -> Tuple[int, int, int, int, Tuple[Tuple[int, Any], ...]]:
        # Stable release (1) sorts higher than prerelease (0) for same major.minor.patch
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, self.prerelease)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() < other.sort_key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() <= other.sort_key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() > other.sort_key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() >= other.sort_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() == other.sort_key()


def parse_version(raw: str) -> SemVer:
    """Parses a version string such as 'v1.1.0', '1.1.0', or '1.2.0-beta.1+build'."""
    if not isinstance(raw, str):
        raise ValueError(f"Invalid version type: {type(raw).__name__}")
    cleaned = raw.strip()
    match = _SEMVER_RE.match(cleaned)
    if not match:
        raise ValueError(f"Invalid semantic version: {raw!r}")

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) is not None else 0
    pre_raw = match.group(4)

    pre_parts: List[Tuple[int, Any]] = []
    if pre_raw:
        for token in pre_raw.split("."):
            if not token:
                raise ValueError(f"Invalid prerelease segment in version: {raw!r}")
            if token.isdigit():
                pre_parts.append((0, int(token)))
            else:
                pre_parts.append((1, token))

    return SemVer(major=major, minor=minor, patch=patch, prerelease=tuple(pre_parts), raw=cleaned)


def compare_versions(a: str, b: str) -> int:
    """Returns -1 if a < b, 0 if a == b, 1 if a > b."""
    va = parse_version(a)
    vb = parse_version(b)
    if va < vb:
        return -1
    if va > vb:
        return 1
    return 0


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    """Returns True if 'latest' is strictly newer than 'current'."""
    return parse_version(latest) > parse_version(current)


@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0
    content_type: str = ""
    sha256: Optional[str] = None


@dataclass
class ReleaseInfo:
    tag_name: str
    version: str
    name: str
    body: str
    html_url: str
    published_at: str = ""
    prerelease: bool = False
    draft: bool = False
    assets: List[ReleaseAsset] = field(default_factory=list)


@dataclass
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    runtime_mode: RuntimeMode
    release: ReleaseInfo
    selected_asset: Optional[ReleaseAsset] = None
    is_skipped: bool = False


@dataclass
class UpdateConfig:
    auto_check_on_startup: bool = True
    skipped_version: Optional[str] = None
    last_checked_at: Optional[float] = None


def get_config_dir() -> str:
    """Returns per-user config directory (%LOCALAPPDATA%\\MusicalPredator on Windows)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "MusicalPredator")


def get_config_path() -> str:
    return os.path.join(get_config_dir(), "update_config.json")


def load_update_config(config_path: Optional[str] = None) -> UpdateConfig:
    path = config_path or get_config_path()
    if not os.path.exists(path):
        return UpdateConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return UpdateConfig()
        skipped = data.get("skipped_version")
        if skipped is not None:
            skipped = str(skipped).strip() or None
        last_checked = data.get("last_checked_at")
        return UpdateConfig(
            auto_check_on_startup=bool(data.get("auto_check_on_startup", True)),
            skipped_version=skipped,
            last_checked_at=float(last_checked) if last_checked is not None else None,
        )
    except Exception:
        return UpdateConfig()


def save_update_config(config: UpdateConfig, config_path: Optional[str] = None) -> bool:
    path = config_path or get_config_path()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = {
            "auto_check_on_startup": bool(config.auto_check_on_startup),
            "skipped_version": config.skipped_version,
            "last_checked_at": config.last_checked_at,
        }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception:
        return False


def _read_registry_install_location() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, "InstallLocation")
            return str(val).strip() if val else None
    except Exception:
        return None


def detect_runtime_mode(
    frozen: Optional[bool] = None,
    executable: Optional[str] = None,
    uninstall_install_location: Optional[str] = None,
) -> RuntimeMode:
    """
    Detects whether the app is running as:
    - INSTALLED: frozen PyInstaller binary inside a Setup-installed directory
    - PORTABLE: frozen standalone MusicalPredator.exe
    - SOURCE: Python interpreter running from source tree
    """
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    if not is_frozen:
        return RuntimeMode.SOURCE

    exe_path = os.path.abspath(executable or sys.executable)
    exe_dir = os.path.normcase(os.path.normpath(os.path.dirname(exe_path)))

    if os.path.exists(os.path.join(os.path.dirname(exe_path), "uninstall.bat")):
        return RuntimeMode.INSTALLED

    reg_loc = uninstall_install_location if uninstall_install_location is not None else _read_registry_install_location()
    if reg_loc:
        norm_reg = os.path.normcase(os.path.normpath(reg_loc))
        if exe_dir == norm_reg:
            return RuntimeMode.INSTALLED

    return RuntimeMode.PORTABLE


def _extract_sha256_digest(raw_digest: Any) -> Optional[str]:
    if not isinstance(raw_digest, str):
        return None
    text = raw_digest.strip()
    if text.lower().startswith("sha256:"):
        text = text.split(":", 1)[1].strip()
    if _SHA256_HEX_RE.match(text):
        return text.lower()
    return None


def parse_github_release(payload: Dict[str, Any]) -> ReleaseInfo:
    """Parses a GitHub Releases API JSON object into ReleaseInfo."""
    if not isinstance(payload, dict):
        raise UpdateError("Unexpected GitHub release response format.")

    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        raise UpdateError("Release metadata is missing 'tag_name'.")
    try:
        parsed_ver = parse_version(tag_name)
    except ValueError as e:
        raise UpdateError(f"Release tag '{tag_name}' is not a valid version: {e}") from e

    raw_assets = payload.get("assets") or []
    assets: List[ReleaseAsset] = []
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("browser_download_url") or "").strip()
            if not name or not url:
                continue
            size_val = item.get("size") or 0
            try:
                size_int = max(0, int(size_val))
            except (TypeError, ValueError):
                size_int = 0
            assets.append(
                ReleaseAsset(
                    name=name,
                    download_url=url,
                    size=size_int,
                    content_type=str(item.get("content_type") or ""),
                    sha256=_extract_sha256_digest(item.get("digest")),
                )
            )

    html_url = str(payload.get("html_url") or GITHUB_RELEASES_PAGE_URL.format(repo=DEFAULT_REPO)).strip()
    title = str(payload.get("name") or tag_name).strip()
    body = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()

    return ReleaseInfo(
        tag_name=tag_name,
        version=parsed_ver.normalized,
        name=title,
        body=body,
        html_url=html_url,
        published_at=published_at,
        prerelease=bool(payload.get("prerelease", False)),
        draft=bool(payload.get("draft", False)),
        assets=assets,
    )


def fetch_latest_release(
    repo: str = DEFAULT_REPO,
    timeout: float = 10.0,
    api_url: Optional[str] = None,
) -> ReleaseInfo:
    """Fetches latest release metadata from GitHub Releases."""
    url = api_url or GITHUB_LATEST_RELEASE_URL.format(repo=repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MusicalPredator/{APP_VERSION}",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as e:
        try:
            if e.code in (403, 429):
                remaining = e.headers.get("X-RateLimit-Remaining") if e.headers else None
                reset_ts = e.headers.get("X-RateLimit-Reset") if e.headers else None
                if e.code == 429 or remaining == "0":
                    reset_hint = ""
                    if reset_ts and str(reset_ts).isdigit():
                        wait_min = max(1, int((int(reset_ts) - time.time()) // 60) + 1)
                        reset_hint = f" Resets in ~{wait_min} min."
                    raise UpdateRateLimitError(
                        f"GitHub API rate limit exceeded (HTTP {e.code}).{reset_hint} "
                        "Please try again later or download from the GitHub Releases page."
                    ) from e
                raise UpdateNetworkError(f"GitHub access denied (HTTP {e.code}): {e.reason}") from e
            if e.code == 404:
                raise UpdateNotFoundError("No published releases were found for this repository yet.") from e
            raise UpdateNetworkError(f"GitHub returned HTTP {e.code}: {e.reason}") from e
        finally:
            try:
                e.close()
            except Exception:
                pass
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateNetworkError(
            "Unable to reach GitHub. Please check your internet connection and try again."
        ) from e

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise UpdateError(f"Failed to parse GitHub release metadata: {e}") from e

    return parse_github_release(payload)


def select_update_asset(release: ReleaseInfo, mode: RuntimeMode) -> Optional[ReleaseAsset]:
    """Selects the most appropriate release asset for the current runtime mode."""
    by_lower = {asset.name.lower(): asset for asset in release.assets}

    if mode == RuntimeMode.INSTALLED:
        return by_lower.get(SETUP_ASSET_NAME.lower()) or by_lower.get(PORTABLE_ASSET_NAME.lower())
    if mode == RuntimeMode.PORTABLE:
        return by_lower.get(PORTABLE_ASSET_NAME.lower())
    return by_lower.get(SETUP_ASSET_NAME.lower()) or by_lower.get(PORTABLE_ASSET_NAME.lower())


def cleanup_stale_staging_dirs(temp_root: Optional[str] = None, max_age_seconds: float = 86400.0) -> int:
    """Removes abandoned update staging directories older than max_age_seconds."""
    root = temp_root or tempfile.gettempdir()
    removed = 0
    now = time.time()
    try:
        for entry in os.scandir(root):
            if not entry.is_dir() or not entry.name.startswith(STAGING_DIR_PREFIX):
                continue
            try:
                age = now - entry.stat().st_mtime
                if age >= max_age_seconds:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


def create_staging_dir(version: str, temp_root: Optional[str] = None) -> str:
    safe_ver = re.sub(r"[^0-9A-Za-z._-]", "_", version or "latest")
    root = temp_root or tempfile.gettempdir()
    return tempfile.mkdtemp(prefix=f"{STAGING_DIR_PREFIX}{safe_ver}_", dir=root)


def _validate_download_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("https", "http"):
        raise UpdateVerificationError(f"Unsupported download URL scheme: {parsed.scheme!r}")


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def download_asset(
    asset: ReleaseAsset,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 30.0,
    expected_sha256: Optional[str] = None,
) -> str:
    """
    Streams a release asset to dest_dir with progress reporting, cancellation,
    size matching, optional SHA-256 verification, and PE 'MZ' header validation.
    """
    _validate_download_url(asset.download_url)
    os.makedirs(dest_dir, exist_ok=True)

    safe_name = os.path.basename(asset.name) or "update_payload.bin"
    final_path = os.path.join(dest_dir, safe_name)
    part_path = f"{final_path}.part"
    _remove_quietly(part_path)

    req = urllib.request.Request(
        asset.download_url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"MusicalPredator/{APP_VERSION}",
        },
        method="GET",
    )

    hasher = hashlib.sha256()
    downloaded = 0
    total_bytes = max(0, int(asset.size or 0))
    first_chunk_header = b""

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if total_bytes <= 0 and resp.headers:
                content_len = resp.headers.get("Content-Length")
                if content_len and str(content_len).isdigit():
                    total_bytes = int(content_len)

            if progress_cb:
                progress_cb(0, total_bytes)

            with open(part_path, "wb") as out_f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateCancelledError("Update download cancelled.")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    if not first_chunk_header:
                        first_chunk_header = chunk[:2]
                    out_f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total_bytes)
    except UpdateCancelledError:
        _remove_quietly(part_path)
        raise
    except urllib.error.HTTPError as e:
        _remove_quietly(part_path)
        raise UpdateNetworkError(f"Download failed (HTTP {e.code}): {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _remove_quietly(part_path)
        raise UpdateNetworkError(f"Download interrupted: {e}") from e

    if downloaded <= 0:
        _remove_quietly(part_path)
        raise UpdateVerificationError("Downloaded update file is empty.")

    if asset.size > 0 and downloaded != asset.size:
        _remove_quietly(part_path)
        raise UpdateVerificationError(
            f"Downloaded size mismatch: expected {asset.size} bytes, got {downloaded} bytes."
        )

    sha_expected = _extract_sha256_digest(expected_sha256) if expected_sha256 else asset.sha256
    if sha_expected:
        actual_sha = hasher.hexdigest().lower()
        if actual_sha != sha_expected.lower():
            _remove_quietly(part_path)
            raise UpdateVerificationError(
                f"SHA-256 verification failed: expected {sha_expected}, got {actual_sha}."
            )

    if safe_name.lower().endswith(".exe") and first_chunk_header != b"MZ":
        _remove_quietly(part_path)
        raise UpdateVerificationError("Downloaded file is not a valid Windows executable (missing PE header).")

    os.replace(part_path, final_path)
    return final_path


def _escape_cmd_arg(value: str) -> str:
    return value.replace('"', '""')


def _build_pid_wait_loop(goto_label: str) -> str:
    """Returns a Windows batch loop waiting until %PID_WAIT% exits (exact CSV PID match)."""
    return (
        "for /L %%i in (1,1,30) do (\n"
        '    tasklist /FI "PID eq %PID_WAIT%" /FO CSV /NH 2>nul | find """%PID_WAIT%""" >nul\n'
        f"    if errorlevel 1 goto :{goto_label}\n"
        "    ping -n 2 127.0.0.1 >nul\n"
        ")"
    )


def build_portable_update_script(
    pid: int,
    downloaded_exe: str,
    target_exe: str,
    staging_dir: str,
    relaunch_minimized: bool = False,
) -> str:
    """Builds a detached Windows batch script that swaps the portable EXE after PID exits."""
    target_dir = os.path.dirname(os.path.abspath(target_exe))
    backup_exe = f"{target_exe}.bak"
    launch_args = " --minimized" if relaunch_minimized else ""
    wait_loop = _build_pid_wait_loop("do_swap")

    return f"""@echo off
setlocal enabledelayedexpansion
set "PID_WAIT={int(pid)}"
set "NEW_EXE={_escape_cmd_arg(os.path.abspath(downloaded_exe))}"
set "TARGET_EXE={_escape_cmd_arg(os.path.abspath(target_exe))}"
set "TARGET_DIR={_escape_cmd_arg(target_dir)}"
set "BACKUP_EXE={_escape_cmd_arg(backup_exe)}"
set "STAGING_DIR={_escape_cmd_arg(os.path.abspath(staging_dir))}"

{wait_loop}

:do_swap
ping -n 2 127.0.0.1 >nul
if exist "%TARGET_EXE%" (
    copy /Y "%TARGET_EXE%" "%BACKUP_EXE%" >nul 2>&1
)

set "SWAPPED=0"
for /L %%r in (1,1,6) do (
    copy /Y "%NEW_EXE%" "%TARGET_EXE%" >nul 2>&1
    if not errorlevel 1 (
        set "SWAPPED=1"
        goto :after_swap
    )
    ping -n 2 127.0.0.1 >nul
)

:after_swap
if "%SWAPPED%"=="0" (
    if exist "%BACKUP_EXE%" (
        copy /Y "%BACKUP_EXE%" "%TARGET_EXE%" >nul 2>&1
    )
    exit /b 1
)

if exist "%BACKUP_EXE%" del /F /Q "%BACKUP_EXE%" >nul 2>&1
start "" /D "%TARGET_DIR%" "%TARGET_EXE%"{launch_args}
rd /S /Q "%STAGING_DIR%" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""


def build_installed_update_script(
    pid: int,
    downloaded_setup: str,
    install_dir: str,
    staging_dir: str,
    relaunch_minimized: bool = False,
) -> str:
    """Builds a detached Windows batch script that runs MusicalPredator-Setup.exe silently after PID exits."""
    min_flag = " --minimized" if relaunch_minimized else ""
    wait_loop = _build_pid_wait_loop("run_setup")
    return f"""@echo off
setlocal enabledelayedexpansion
set "PID_WAIT={int(pid)}"
set "SETUP_EXE={_escape_cmd_arg(os.path.abspath(downloaded_setup))}"
set "INSTALL_DIR={_escape_cmd_arg(os.path.abspath(install_dir))}"
set "STAGING_DIR={_escape_cmd_arg(os.path.abspath(staging_dir))}"

{wait_loop}

:run_setup
ping -n 2 127.0.0.1 >nul
start /wait "" "%SETUP_EXE%" --silent --dir="%INSTALL_DIR%" --launch{min_flag}
rd /S /Q "%STAGING_DIR%" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""


def _launch_detached_cmd(script_path: str) -> None:
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    subprocess.Popen(
        ["cmd.exe", "/c", script_path],
        creationflags=creation_flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def apply_update_and_restart(
    downloaded_path: str,
    mode: RuntimeMode,
    prepare_shutdown_cb: Optional[Callable[[], None]] = None,
    relaunch_minimized: bool = False,
    target_executable: Optional[str] = None,
) -> None:
    """
    Launches the appropriate update mechanism for the runtime mode and triggers
    clean application shutdown so file locks are released before replacement.
    """
    if not os.path.exists(downloaded_path):
        raise UpdateError(f"Update payload not found: {downloaded_path}")

    if sys.platform != "win32":
        raise UpdateError("Self-updating Windows binaries is only supported on Windows.")

    staging_dir = os.path.dirname(os.path.abspath(downloaded_path))
    exe_path = os.path.abspath(target_executable or sys.executable)
    exe_dir = os.path.dirname(exe_path)

    if mode == RuntimeMode.SOURCE:
        # In source mode, just launch the downloaded setup wizard without exiting the dev process forcefully
        subprocess.Popen([downloaded_path], close_fds=True)
        return

    if mode == RuntimeMode.INSTALLED and os.path.basename(downloaded_path).lower() == SETUP_ASSET_NAME.lower():
        script_text = build_installed_update_script(
            pid=os.getpid(),
            downloaded_setup=downloaded_path,
            install_dir=exe_dir,
            staging_dir=staging_dir,
            relaunch_minimized=relaunch_minimized,
        )
    else:
        script_text = build_portable_update_script(
            pid=os.getpid(),
            downloaded_exe=downloaded_path,
            target_exe=exe_path,
            staging_dir=staging_dir,
            relaunch_minimized=relaunch_minimized,
        )

    # Write helper script outside staging_dir so rd /S /Q staging_dir doesn't race the running script
    fd, script_path = tempfile.mkstemp(prefix="MusicalPredator_apply_", suffix=".cmd")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_text)
    except Exception:
        _remove_quietly(script_path)
        raise

    _launch_detached_cmd(script_path)
    if prepare_shutdown_cb:
        prepare_shutdown_cb()


def open_release_page(url: Optional[str] = None, repo: str = DEFAULT_REPO) -> bool:
    target = url or GITHUB_RELEASES_PAGE_URL.format(repo=repo)
    try:
        return bool(webbrowser.open(target))
    except Exception:
        return False


class UpdateManager:
    """Stateful coordinator for checking, downloading, verifying, and applying updates."""

    def __init__(
        self,
        current_version: str = APP_VERSION,
        repo: str = DEFAULT_REPO,
        config_path: Optional[str] = None,
        api_url: Optional[str] = None,
        on_prepare_shutdown: Optional[Callable[[], None]] = None,
        relaunch_minimized: bool = False,
    ):
        self.current_version = current_version
        self.repo = repo
        self.config_path = config_path
        self.api_url = api_url
        self.on_prepare_shutdown = on_prepare_shutdown
        self.relaunch_minimized = relaunch_minimized

        self._lock = threading.Lock()
        self.config = load_update_config(self.config_path)
        self.runtime_mode = detect_runtime_mode()
        self.last_result: Optional[UpdateCheckResult] = None

        cleanup_stale_staging_dirs()

    def reload_config(self) -> UpdateConfig:
        with self._lock:
            self.config = load_update_config(self.config_path)
            return self.config

    def set_auto_check(self, enabled: bool) -> None:
        with self._lock:
            self.config.auto_check_on_startup = bool(enabled)
            save_update_config(self.config, self.config_path)

    def skip_version(self, version: str) -> None:
        with self._lock:
            self.config.skipped_version = parse_version(version).normalized
            save_update_config(self.config, self.config_path)
            if self.last_result and self.last_result.latest_version == self.config.skipped_version:
                self.last_result.is_skipped = True

    def clear_skipped_version(self) -> None:
        with self._lock:
            self.config.skipped_version = None
            save_update_config(self.config, self.config_path)

    def check_for_updates(self, respect_skip: bool = False, timeout: float = 10.0) -> UpdateCheckResult:
        release = fetch_latest_release(repo=self.repo, timeout=timeout, api_url=self.api_url)
        newer = is_newer_version(release.version, self.current_version)
        asset = select_update_asset(release, self.runtime_mode)

        with self._lock:
            self.config.last_checked_at = time.time()
            save_update_config(self.config, self.config_path)

            skipped_ver = self.config.skipped_version
            is_skipped = bool(
                skipped_ver
                and parse_version(skipped_ver) == parse_version(release.version)
            )
            result = UpdateCheckResult(
                current_version=parse_version(self.current_version).normalized,
                latest_version=release.version,
                update_available=newer and (not respect_skip or not is_skipped),
                runtime_mode=self.runtime_mode,
                release=release,
                selected_asset=asset,
                is_skipped=is_skipped,
            )
            self.last_result = result
            return result

    def download_update(
        self,
        result: UpdateCheckResult,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        temp_root: Optional[str] = None,
    ) -> str:
        if not result.selected_asset:
            raise UpdateError(
                f"No compatible installer/executable asset found in release v{result.latest_version}."
            )
        staging_dir = create_staging_dir(result.latest_version, temp_root=temp_root)
        try:
            return download_asset(
                asset=result.selected_asset,
                dest_dir=staging_dir,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def apply_update(self, downloaded_path: str) -> None:
        apply_update_and_restart(
            downloaded_path=downloaded_path,
            mode=self.runtime_mode,
            prepare_shutdown_cb=self.on_prepare_shutdown,
            relaunch_minimized=self.relaunch_minimized,
        )
