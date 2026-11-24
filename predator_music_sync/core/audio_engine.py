"""
Real-time Audio Capture, Multi-band Spectrum Analysis, AGC, Dynamic Noise Floor Gating,
and Punchy Beat Detection Engine.
Captures system audio loopback (Stereo Mix, WASAPI, or Default Input) with ultra-low latency.
"""

import time
import threading
from typing import Optional, Callable, Dict, Any, List, Tuple
import sounddevice as sd
import numpy as np

class AudioBeatState:
    def __init__(self):
        self.is_beat: bool = False
        self.is_hard_kick: bool = False
        self.beat_strength: float = 0.0   # 0.0 to 1.5+
        self.overall_energy: float = 0.0   # Normalized 0.0 to 1.0 (snaps to 0.0 in silence)
        self.band_energies: np.ndarray = np.zeros(4, dtype=np.float32)   # Raw [SubBass, LowMid, HighMid, Treble]
        self.smoothed_bands: np.ndarray = np.zeros(4, dtype=np.float32)  # Normalized 0.0 to 1.0 (snaps to 0.0 in silence)
        self.bpm_estimate: float = 120.0
        self.latency_ms: float = 0.0
        self.is_silent: bool = True


class AudioBeatSyncEngine:
    """
    Real-time audio processing engine with Automatic Gain Control (AGC),
    dynamic noise floor gating to eliminate background noise triggers,
    and dynamic audio input device switching.
    """

    BUFFER_SIZE = 1024  # ~21.3ms window at 48kHz for instant transient response
    DEFAULT_NOISE_FLOOR = 0.001  # Signals below this RMS are gated as pure silence

    def __init__(
        self,
        device_index: Optional[int] = None,
        sensitivity: float = 1.15,
        noise_floor: float = DEFAULT_NOISE_FLOOR
    ):
        self.sensitivity = sensitivity
        self.noise_floor = noise_floor
        self.device_index = device_index
        self.band_gains = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
        self._stream: Optional[sd.InputStream] = None
        self._is_running = False
        self._is_paused = False
        self._last_reconnect_time = 0.0
        self._last_callback_time = 0.0
        self._state = AudioBeatState()
        self._lock = threading.Lock()
        self._stream_lock = threading.RLock()

        # Auto-detect optimal device and its native sample rate
        self._preferred_device_index = device_index
        self.device_index, self.sample_rate = self._find_optimal_device_and_rate(prefer_device=device_index)

        # Automatic Gain Control (AGC) trackers
        self._reset_agc()

        # Beat detection variables
        self._energy_history: List[float] = []
        self._history_len = 45  # ~1 second history
        self._prev_fft: Optional[np.ndarray] = None
        self._last_beat_time: float = 0.0
        self._beat_intervals: List[float] = []
        self._min_beat_interval = 0.16  # Snappy ~375 max BPM limit

        # Precompute FFT frequency bins & window
        self._setup_fft_bins()
        self._window = np.hanning(self.BUFFER_SIZE)

        # Callbacks
        self._beat_callbacks: List[Callable[[AudioBeatState], None]] = []

    @property
    def silence_threshold(self) -> float:
        """Alias for noise floor threshold."""
        return self.noise_floor

    @silence_threshold.setter
    def silence_threshold(self, value: float):
        with self._lock:
            self.noise_floor = max(0.0001, min(0.05, float(value)))

    def set_band_gain(self, band_idx: int, gain: float):
        """Sets individual band gain multiplier (0: Sub-Bass, 1: Low-Mid, 2: High-Mid, 3: Treble)."""
        if 0 <= band_idx < 4:
            with self._lock:
                self.band_gains[band_idx] = max(0.0, min(5.0, float(gain)))

    def set_band_gains(self, gains: List[float]):
        """Sets all 4 band gain multipliers at once."""
        with self._lock:
            for i in range(min(4, len(gains))):
                self.band_gains[i] = max(0.0, min(5.0, float(gains[i])))

    def _reset_agc(self):
        """Resets AGC trackers to baseline."""
        self._peak_energy = 0.05
        self._peak_bands = np.array([0.5, 0.4, 0.3, 0.1], dtype=np.float32)
        self._energy_history = []
        self._prev_fft = None

    def _setup_fft_bins(self):
        """Precomputes frequency mask arrays for the active sample rate."""
        self._freq_bins = np.fft.rfftfreq(self.BUFFER_SIZE, 1.0 / self.sample_rate)
        self._mask_subbass = (self._freq_bins >= 20) & (self._freq_bins < 120)
        self._mask_lowmid = (self._freq_bins >= 120) & (self._freq_bins < 500)
        self._mask_highmid = (self._freq_bins >= 500) & (self._freq_bins < 3500)
        self._mask_treble = (self._freq_bins >= 3500) & (self._freq_bins < 16000)

    @classmethod
    def get_available_input_devices(cls) -> List[Tuple[int, str, str]]:
        """
        Returns a list of all audio devices capable of input capture:
        List of (device_index, device_name, host_api_name).
        """
        devices = []
        try:
            devs = sd.query_devices()
            apis = sd.query_hostapis()
            for i, d in enumerate(devs):
                if d.get('max_input_channels', 0) > 0:
                    hostapi_idx = d.get('hostapi', 0)
                    api_name = apis[hostapi_idx]['name'] if hostapi_idx < len(apis) else "Unknown"
                    devices.append((i, str(d['name']), str(api_name)))
        except Exception:
            pass
        return devices

    def set_device(self, device_index: int) -> bool:
        """
        Dynamically restarts the input stream on a chosen device without crashing or deadlocking.
        Returns True if the device was successfully opened and started.
        """
        try:
            dev = sd.query_devices(device_index)
            if dev.get('max_input_channels', 0) <= 0:
                return False
            sr = int(dev.get('default_samplerate', 48000))
        except Exception:
            return False

        was_running = self._is_running

        with self._stream_lock:
            # Safely stop existing stream outside audio callback lock to prevent deadlock
            self._is_running = False
            old_stream = self._stream
            self._stream = None
            if old_stream is not None:
                try:
                    old_stream.stop()
                    old_stream.close()
                except Exception:
                    pass

            with self._lock:
                self._preferred_device_index = device_index
                self.device_index = device_index
                self.sample_rate = sr
                self._setup_fft_bins()
                self._reset_agc()

            if was_running:
                self.start()

        return True

    def _probe_device_rms(self, dev_idx: int, duration: float = 0.04) -> float:
        """Quickly probes a device to see if it carries active audio signal."""
        rms_val = [0.0]
        def _cb(indata, frames, time_info, status):
            rms_val[0] = max(rms_val[0], float(np.sqrt(np.mean(indata ** 2))))
        try:
            ch = min(2, sd.query_devices(dev_idx)['max_input_channels'])
            s = sd.InputStream(device=dev_idx, channels=ch, callback=_cb)
            s.start()
            time.sleep(duration)
            s.stop()
            s.close()
            return rms_val[0]
        except Exception:
            return -1.0

    def _find_optimal_device_and_rate(self, prefer_device: Optional[int] = None) -> Tuple[Optional[int], int]:
        """
        Auto-detects optimal input device:
        1. Explicitly preferred device if valid.
        2. Device with active music signal (RMS > 0.002).
        3. System Stereo Mix (cleanest system loopback without room mic noise).
        4. Virtual audio devices (FxSound, VAC).
        5. Default Input device.
        """
        try:
            devices = sd.query_devices()
            if prefer_device is not None and 0 <= prefer_device < len(devices):
                d = devices[prefer_device]
                if d.get('max_input_channels', 0) > 0:
                    return prefer_device, int(d.get('default_samplerate', 48000))

            # 1. Look for Stereo Mix (clean direct music loopback)
            stereo_mix_idx = None
            for i, d in enumerate(devices):
                name = d['name'].lower()
                if ('stereo mix' in name or 'what u hear' in name or 'wave out mix' in name) and d['max_input_channels'] > 0:
                    stereo_mix_idx = i
                    break

            if stereo_mix_idx is not None:
                sr = int(devices[stereo_mix_idx].get('default_samplerate', 48000))
                return stereo_mix_idx, sr

            # 2. Look for virtual loopbacks
            for i, d in enumerate(devices):
                name = d['name'].lower()
                if ('fxsound' in name or 'virtual audio' in name or 'cable' in name) and d['max_input_channels'] > 0:
                    sr = int(d.get('default_samplerate', 48000))
                    return i, sr

            # 3. Default input
            default_in = sd.default.device[0]
            if default_in is not None and default_in >= 0 and default_in < len(devices):
                d = devices[default_in]
                sr = int(d.get('default_samplerate', 48000))
                return default_in, sr
        except Exception:
            pass

        return None, 48000

    def add_beat_callback(self, cb: Callable[[AudioBeatState], None]):
        with self._lock:
            self._beat_callbacks.append(cb)

    def _open_input_stream(self) -> bool:
        """Opens the sounddevice InputStream on the preferred or fallback device."""
        try:
            channels = min(2, sd.query_devices(self.device_index)['max_input_channels']) if self.device_index is not None else 1
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.BUFFER_SIZE,
                device=self.device_index,
                channels=channels,
                callback=self._audio_callback
            )
            self._stream.start()
            self._last_callback_time = time.monotonic()
            return True
        except Exception:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.BUFFER_SIZE,
                    channels=1,
                    callback=self._audio_callback
                )
                self._stream.start()
                self._last_callback_time = time.monotonic()
                return True
            except Exception:
                if self._stream is not None:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
                return False

    def start(self):
        with self._stream_lock:
            if self._is_running:
                return
            self._is_running = True
            self._last_callback_time = time.monotonic()
            # Keep _is_running True even if initial stream open fails transiently
            # so _check_stream_health() can automatically recover when device returns.
            self._open_input_stream()

    def stop(self):
        with self._stream_lock:
            self._is_running = False
            self._is_paused = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def pause(self):
        """
        Suspends audio stream capture, dropping CPU to 0.0%.
        Resets active state to pure silence.
        """
        with self._stream_lock:
            with self._lock:
                self._is_paused = True
                self._state.is_beat = False
                self._state.is_hard_kick = False
                self._state.beat_strength = 0.0
                self._state.overall_energy = 0.0
                self._state.smoothed_bands = np.zeros(4, dtype=np.float32)
                self._state.band_energies = np.zeros(4, dtype=np.float32)
                self._state.is_silent = True
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass

    def resume(self):
        """Resumes audio stream capture from paused state."""
        with self._stream_lock:
            with self._lock:
                if not self._is_paused:
                    return
                self._is_paused = False
            if self._is_running:
                self._last_callback_time = time.monotonic()
                if self._stream is not None:
                    try:
                        self._stream.start()
                    except Exception:
                        self._recover_stream_locked()
                else:
                    self._open_input_stream()

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def _reset_state_silence(self):
        with self._lock:
            self._state.is_beat = False
            self._state.is_hard_kick = False
            self._state.beat_strength = 0.0
            self._state.overall_energy = 0.0
            self._state.smoothed_bands = np.zeros(4, dtype=np.float32)
            self._state.band_energies = np.zeros(4, dtype=np.float32)
            self._state.is_silent = True

    def _recover_stream_locked(self):
        """Closes any broken/stalled stream and re-opens audio capture."""
        old = self._stream
        self._stream = None
        if old is not None:
            try:
                old.stop()
                old.close()
            except Exception:
                pass
        self._reset_state_silence()
        prefer = self._preferred_device_index if self._preferred_device_index is not None else self.device_index
        self.device_index, self.sample_rate = self._find_optimal_device_and_rate(prefer_device=prefer)
        with self._lock:
            self._setup_fft_bins()
        if not self._open_input_stream():
            # Refresh PortAudio's cached Windows device table if stream failed to reopen
            try:
                sd._terminate()
                sd._initialize()
                self.device_index, self.sample_rate = self._find_optimal_device_and_rate(prefer_device=prefer)
                with self._lock:
                    self._setup_fft_bins()
                self._open_input_stream()
            except Exception:
                pass

    def recover_if_stalled(self):
        """Public hook called on system resume / display wake to validate and restart stalled streams."""
        if not self._is_running or self._is_paused:
            return
        with self._stream_lock:
            self._last_reconnect_time = 0.0
            self._check_stream_health()

    def _check_stream_health(self):
        """Auto-recovers audio stream if disconnected, stopped, or stalled (no callbacks)."""
        if not self._is_running or self._is_paused:
            return
        now = time.monotonic()
        if (now - self._last_reconnect_time) < 2.0:
            return
        # If stream died, was invalidated, or WASAPI stopped delivering callbacks (stalled >2.5s)
        stream_dead = (self._stream is None) or (hasattr(self._stream, "active") and not self._stream.active)
        stream_stalled = (self._last_callback_time > 0.0) and ((now - self._last_callback_time) > 2.5)
        if stream_dead or stream_stalled:
            if not self._stream_lock.acquire(blocking=False):
                return
            try:
                if not self._is_running or self._is_paused:
                    return
                self._last_reconnect_time = now
                self._recover_stream_locked()
            except Exception:
                pass
            finally:
                self._stream_lock.release()

    def get_state(self) -> AudioBeatState:
        self._check_stream_health()
        with self._lock:
            st = AudioBeatState()
            st.is_beat = self._state.is_beat
            st.is_hard_kick = self._state.is_hard_kick
            st.beat_strength = self._state.beat_strength
            st.overall_energy = self._state.overall_energy
            st.band_energies = np.copy(self._state.band_energies)
            st.smoothed_bands = np.copy(self._state.smoothed_bands)
            st.bpm_estimate = self._state.bpm_estimate
            st.latency_ms = self._state.latency_ms
            st.is_silent = self._state.is_silent
            return st

    def _audio_callback(self, indata, frames, time_info, status):
        t0 = time.perf_counter()
        self._last_callback_time = time.monotonic()
        if not self._is_running or self._is_paused:
            return

        if status:
            # Underflow/overflow notification; sounddevice handles buffer recycling internally
            pass

        if indata.ndim > 1:
            mono = np.mean(indata, axis=1)
        else:
            mono = indata.flatten()

        # Fast RMS check on raw signal before performing heavy FFT calculations
        rms = float(np.sqrt(np.mean(mono ** 2)))

        # =========================================================================
        # DYNAMIC NOISE FLOOR GATING:
        # If signal is below noise threshold, snap all energies to 0 immediately.
        # Skip FFT completely in silence to minimize CPU utilization to ~0.0%.
        # =========================================================================
        if rms < self.noise_floor:
            t_end = time.perf_counter()
            with self._lock:
                self._state.is_beat = False
                self._state.is_hard_kick = False
                self._state.beat_strength = 0.0
                self._state.overall_energy = 0.0
                self._state.smoothed_bands = np.maximum(0.0, self._state.smoothed_bands * 0.70)
                if np.max(self._state.smoothed_bands) < 0.01:
                    self._state.smoothed_bands = np.zeros(4, dtype=np.float32)
                self._state.band_energies = np.zeros(4, dtype=np.float32)
                self._state.is_silent = True
                self._state.latency_ms = (t_end - t0) * 1000.0
            self._prev_fft = None
            return

        fft_data = np.abs(np.fft.rfft(mono * self._window))

        # 4 Band energies
        e_sub = float(np.mean(fft_data[self._mask_subbass])) if np.any(self._mask_subbass) else 0.0
        e_low = float(np.mean(fft_data[self._mask_lowmid])) if np.any(self._mask_lowmid) else 0.0
        e_mid = float(np.mean(fft_data[self._mask_highmid])) if np.any(self._mask_highmid) else 0.0
        e_treble = float(np.mean(fft_data[self._mask_treble])) if np.any(self._mask_treble) else 0.0

        raw_bands = np.array([e_sub, e_low, e_mid, e_treble], dtype=np.float32) * self.band_gains

        # Secondary noise check for high-frequency hiss or background ambient noise
        if rms < self.noise_floor and np.max(raw_bands) < (self.noise_floor * 4.0):
            t_end = time.perf_counter()
            with self._lock:
                self._state.is_beat = False
                self._state.is_hard_kick = False
                self._state.beat_strength = 0.0
                self._state.overall_energy = 0.0
                self._state.smoothed_bands = np.maximum(0.0, self._state.smoothed_bands * 0.70)
                if np.max(self._state.smoothed_bands) < 0.01:
                    self._state.smoothed_bands = np.zeros(4, dtype=np.float32)
                self._state.band_energies = raw_bands
                self._state.is_silent = True
                self._state.latency_ms = (t_end - t0) * 1000.0
            self._prev_fft = None
            return

        # Active audio signal present
        # Spectral flux (difference from previous frame's positive bins)
        if self._prev_fft is not None:
            flux = float(np.sum(np.maximum(0.0, fft_data - self._prev_fft)))
        else:
            flux = float(np.sum(fft_data))
        self._prev_fft = fft_data

        # Automatic Gain Control (AGC) with sane floor to prevent boosting silence
        self._peak_energy = max(float(rms), float(self._peak_energy * 0.992), 0.02)
        self._peak_bands = np.maximum(raw_bands, self._peak_bands * 0.992)
        self._peak_bands = np.maximum(self._peak_bands, 0.02)

        norm_energy = min(1.0, float(rms / self._peak_energy))
        norm_bands = np.clip(raw_bands / (self._peak_bands + 1e-5), 0.0, 1.0)
        # Apply musical contrast exponent to separate loud beats from soft background
        norm_bands = np.power(norm_bands, 1.35)

        # Punchy beat detection: heavily weight sub-bass kicks & flux transients
        punch_score = (norm_bands[0] * 3.2) + (norm_bands[1] * 1.6) + (flux * 0.001)
        self._energy_history.append(punch_score)
        if len(self._energy_history) > self._history_len:
            self._energy_history.pop(0)

        now = time.monotonic()
        is_beat = False
        is_hard_kick = False
        beat_strength = 0.0

        if len(self._energy_history) >= 8:
            avg_e = float(np.mean(self._energy_history))
            std_e = float(np.std(self._energy_history))
            threshold = avg_e + (std_e * self.sensitivity)

            if punch_score > threshold and (now - self._last_beat_time) > self._min_beat_interval:
                is_beat = True
                interval = now - self._last_beat_time
                self._last_beat_time = now

                diff = punch_score - threshold
                beat_strength = min(1.5, float(0.7 + (diff / (std_e + 1e-4) * 0.6)))
                is_hard_kick = norm_bands[0] > 0.60 or beat_strength > 1.1

                if 0.25 <= interval <= 1.5:
                    self._beat_intervals.append(interval)
                    if len(self._beat_intervals) > 8:
                        self._beat_intervals.pop(0)

        # Estimate BPM
        bpm = 120.0
        if self._beat_intervals:
            avg_interval = sum(self._beat_intervals) / len(self._beat_intervals)
            if avg_interval > 0:
                bpm = round(60.0 / avg_interval, 1)

        t_end = time.perf_counter()
        lat_ms = (t_end - t0) * 1000.0

        with self._lock:
            self._state.is_beat = is_beat
            self._state.is_hard_kick = is_hard_kick
            self._state.beat_strength = beat_strength
            self._state.overall_energy = norm_energy
            self._state.band_energies = raw_bands
            # Fast attack, smooth release
            alpha = 0.65
            self._state.smoothed_bands = (self._state.smoothed_bands * (1.0 - alpha)) + (norm_bands * alpha)
            self._state.bpm_estimate = bpm
            self._state.latency_ms = lat_ms
            self._state.is_silent = False
            beat_cbs = list(self._beat_callbacks) if is_beat else []

        if is_beat and beat_cbs:
            for cb in beat_cbs:
                try:
                    cb(self._state)
                except Exception:
                    pass
