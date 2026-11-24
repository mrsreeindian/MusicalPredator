"""
Media Session and Album Cover Extractor
Extracts current track metadata and album cover thumbnail from Windows (SMTC) or Linux (MPRIS).
"""

import os
import sys
import json
import time
import hashlib
import platform
import subprocess
import threading
from typing import Optional, Dict, Callable, Any

class MediaTrackInfo:
    def __init__(self, title: str = "", artist: str = "", album: str = "", cover_path: Optional[str] = None):
        self.title = title
        self.artist = artist
        self.album = album
        self.cover_path = cover_path

    @property
    def track_id(self) -> str:
        has_cover = bool(self.cover_path and os.path.exists(self.cover_path))
        s = f"{self.title}|{self.artist}|{self.album}|{has_cover}"
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def __repr__(self):
        return f"<MediaTrackInfo title='{self.title}' artist='{self.artist}' album='{self.album}' cover='{self.cover_path}'>"


class MediaSessionEngine:
    """
    Monitors active media playback and extracts album artwork and metadata.
    """

    def __init__(self, cache_dir: Optional[str] = None, poll_interval: float = 2.0):
        self.poll_interval = poll_interval
        self._current_track: Optional[MediaTrackInfo] = None
        self._on_track_change_callbacks = []
        self._is_running = False
        self._is_paused = False
        self._query_lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None

        # Preconfigure hidden startupinfo to prevent console popups on Windows
        self._startupinfo = None
        self._creationflags = 0
        if sys.platform == "win32":
            self._creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            self._startupinfo = subprocess.STARTUPINFO()
            self._startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self._startupinfo.wShowWindow = subprocess.SW_HIDE

        if cache_dir is None:
            base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.cache_dir = os.path.join(base_dir, "cache", "covers")
        else:
            self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self._ps_script_path = os.path.join(self.cache_dir, "get_smtc_media.ps1")
        self._ensure_ps_script()

    def _ensure_ps_script(self):
        """Create the optimized PowerShell SMTC extraction script."""
        script_content = r"""Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
}
function AwaitOp($op, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait()
    return $t.Result
}
try {
    $asyncOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media, ContentType = WindowsRuntime]::RequestAsync()
    $mgr = AwaitOp $asyncOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $mgr.GetCurrentSession()
    if ($session) {
        $props = AwaitOp ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $outObj = @{
            Title = $props.Title
            Artist = $props.Artist
            AlbumTitle = $props.AlbumTitle
            HasThumbnail = ($props.Thumbnail -ne $null)
        }
        $targetDir = $args[0]
        if ($props.Thumbnail -and $targetDir) {
            $stream = AwaitOp ($props.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
            $asStreamMethod = [System.IO.WindowsRuntimeStreamExtensions].GetMethod("AsStream", [Type[]]@([Windows.Storage.Streams.IRandomAccessStream]))
            if ($asStreamMethod) {
                $netStream = $asStreamMethod.Invoke($null, @($stream))
                $hash = [BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($props.Title + $props.Artist))).Replace('-', '')
                $outFile = [System.IO.Path]::Combine($targetDir, "cover_" + $hash + ".jpg")
                $fileStream = [System.IO.File]::Create($outFile)
                $netStream.CopyTo($fileStream)
                $fileStream.Close()
                $netStream.Close()
                $outObj["SavedPath"] = $outFile
            }
        }
        $outObj | ConvertTo-Json -Compress
    } else {
        '{"NoSession": true}'
    }
} catch {
    '{"Error": "' + $_.Exception.Message.Replace('"', '\"') + '"}'
}
"""
        with open(self._ps_script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

    def add_track_change_callback(self, callback: Callable[[MediaTrackInfo], None]):
        self._on_track_change_callbacks.append(callback)

    @property
    def current_track(self) -> Optional[MediaTrackInfo]:
        return self._current_track

    def get_current_media_track(self) -> Optional[MediaTrackInfo]:
        """Fetch current media track once."""
        system = platform.system().lower()
        if "windows" in system:
            return self._query_windows_smtc()
        elif "linux" in system:
            return self._query_linux_mpris()
        return None

    def _cleanup_cover_cache(self, max_files: int = 50):
        """
        Ensures thumbnail cache doesn't accumulate unbounded temporary files.
        Retains the newest `max_files` and cleans up old covers.
        """
        try:
            if not os.path.exists(self.cache_dir):
                return
            files = [
                os.path.join(self.cache_dir, f)
                for f in os.listdir(self.cache_dir)
                if f.startswith("cover_") and f.endswith(".jpg")
            ]
            if len(files) > max_files:
                # Sort by last modified time (oldest first)
                files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
                current_cover = self._current_track.cover_path if self._current_track else None
                excess = len(files) - max_files
                deleted = 0
                for f in files:
                    if deleted >= excess:
                        break
                    if current_cover and os.path.abspath(f) == os.path.abspath(current_cover):
                        continue
                    try:
                        os.remove(f)
                        deleted += 1
                    except Exception:
                        pass
        except Exception:
            pass

    def _query_windows_smtc(self) -> Optional[MediaTrackInfo]:
        # Lock to ensure PowerShell background processes never pile up
        if not self._query_lock.acquire(blocking=False):
            return self._current_track

        proc = None
        try:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", self._ps_script_path, self.cache_dir]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.5,
                creationflags=self._creationflags,
                startupinfo=self._startupinfo
            )
            out = res.stdout.strip()
            if not out or "NoSession" in out or "Error" in out:
                return None
            data = json.loads(out)
            title = data.get("Title", "")
            artist = data.get("Artist", "")
            album = data.get("AlbumTitle", "")
            cover_path = data.get("SavedPath", None)
            if not title and not artist:
                return None
            if cover_path:
                self._cleanup_cover_cache(50)
            return MediaTrackInfo(title=title, artist=artist, album=album, cover_path=cover_path)
        except subprocess.TimeoutExpired as te:
            # Explicit cleanup on timeout to prevent zombie PowerShell processes
            try:
                if hasattr(te, 'process') and te.process:
                    te.process.kill()
                    te.process.communicate(timeout=0.2)
            except Exception:
                pass
            return None
        except Exception:
            return None
        finally:
            self._query_lock.release()

    def _query_linux_mpris(self) -> Optional[MediaTrackInfo]:
        try:
            import dbus
            bus = dbus.SessionBus()
            for service in bus.list_names():
                if service.startswith("org.mpris.MediaPlayer2."):
                    player = bus.get_object(service, "/org/mpris/MediaPlayer2")
                    props_iface = dbus.Interface(player, "org.freedesktop.DBus.Properties")
                    metadata = props_iface.Get("org.mpris.MediaPlayer2.Player", "Metadata")
                    title = str(metadata.get("xesam:title", ""))
                    artists = metadata.get("xesam:artist", [""])
                    artist = str(artists[0]) if artists else ""
                    album = str(metadata.get("xesam:album", ""))
                    art_url = str(metadata.get("mpris:artUrl", ""))
                    cover_path = None
                    if art_url.startswith("file://"):
                        cover_path = art_url[7:]
                    return MediaTrackInfo(title=title, artist=artist, album=album, cover_path=cover_path)
        except Exception:
            pass
        return None

    def start_monitoring(self):
        """Start background polling thread for real-time track changes."""
        if self._is_running:
            return
        self._is_running = True
        self._is_paused = False
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        self._is_running = False
        self._is_paused = False

    def pause_monitoring(self):
        """Suspends media polling to save CPU (e.g. during battery saver or app pause)."""
        self._is_paused = True

    def resume_monitoring(self):
        """Resumes media polling."""
        self._is_paused = False

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def _monitor_loop(self):
        last_id = None
        while self._is_running:
            if self._is_paused:
                time.sleep(1.0)
                continue
            track = self.get_current_media_track()
            if track:
                curr_id = track.track_id
                cover_just_arrived = (
                    self._current_track is not None
                    and not self._current_track.cover_path
                    and bool(track.cover_path and os.path.exists(track.cover_path))
                )
                if curr_id != last_id or cover_just_arrived:
                    last_id = curr_id
                    self._current_track = track
                    for cb in self._on_track_change_callbacks:
                        try:
                            cb(track)
                        except Exception:
                            pass
                interval = self.poll_interval  # Active playback: 2.0s
            else:
                # Adaptive backoff: 3.5s when no active media session to reduce CPU usage
                interval = min(4.0, max(3.0, self.poll_interval * 1.75))
            time.sleep(interval)
