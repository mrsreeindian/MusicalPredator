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
        self._state = AudioBeatState()
        self._lock = threading.Lock()

        # Auto-detect optimal device and its native sample rate
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

        # Safely stop existing stream outside the lock to prevent deadlock with audio callback
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
        self._beat_callbacks.append(cb)

    def start(self):
        if self._is_running:
            return
        self._is_running = True
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
        except Exception:
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.BUFFER_SIZE,
                    channels=1,
                    callback=self._audio_callback
                )
                self._stream.start()
            except Exception:
                self._is_running = False

    def stop(self):
        self._is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def get_state(self) -> AudioBeatState:
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
        if not self._is_running:
            return

        if indata.ndim > 1:
            mono = np.mean(indata, axis=1)
        else:
            mono = indata.flatten()

        rms = float(np.sqrt(np.mean(mono ** 2)))
        fft_data = np.abs(np.fft.rfft(mono * self._window))

        # 4 Band energies
        e_sub = float(np.mean(fft_data[self._mask_subbass])) if np.any(self._mask_subbass) else 0.0
        e_low = float(np.mean(fft_data[self._mask_lowmid])) if np.any(self._mask_lowmid) else 0.0
        e_mid = float(np.mean(fft_data[self._mask_highmid])) if np.any(self._mask_highmid) else 0.0
        e_treble = float(np.mean(fft_data[self._mask_treble])) if np.any(self._mask_treble) else 0.0

        raw_bands = np.array([e_sub, e_low, e_mid, e_treble], dtype=np.float32) * self.band_gains

        # =========================================================================
        # DYNAMIC NOISE FLOOR GATING:
        # If signal is below noise threshold, snap all energies to 0 and suppress beats.
        # Silence must remain pure silence (no false triggers or ambient room noise).
        # =========================================================================
        if rms < self.noise_floor and np.max(raw_bands) < (self.noise_floor * 4.0):
            t_end = time.perf_counter()
            with self._lock:
                self._state.is_beat = False
                self._state.is_hard_kick = False
                self._state.beat_strength = 0.0
                self._state.overall_energy = 0.0
                # Smoothly drop bands to absolute zero
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

        now = time.time()
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

        if is_beat:
            for cb in self._beat_callbacks:
                try:
                    cb(self._state)
                except Exception:
                    pass
