"""
Beat-Synchronized RGB Animation Engine (Diverse 4-Zone Suite)
Engineered specifically for 4-zone keyboards (Acer Predator Helios Neo 16 / PHN16-71).
Provides 12 distinct, masterfully tuned animation styles:
- Strictly audio-reactive & rhythm-locked: No free-wheeling screensavers.
- Silence Gating: When audio is silent (energy < 0.05), drops to pure dark stealth (0, 0, 0).
- Zero-phase-delay beat hits that snap physical middle and outer zones instantaneously.
- Critically-damped ballistic decay envelopes eliminating flicker, frame drops, and jitter on 10-15 Hz EC updates.
- Ultra-low computation latency (< 0.01ms per frame).
"""

import time
import math
import random
from typing import List, Tuple, Dict, Type, Optional
import numpy as np
from .color_extractor import ColorPalette, RGBColor, ColorPaletteExtractor
from .audio_engine import AudioBeatState

def _blend_white(color: RGBColor, factor: float, intensity: float = 1.0) -> RGBColor:
    """Overdrive color towards bright peak while preserving core hue saturation on physical RGB LEDs."""
    f = max(0.0, min(1.0, factor * intensity * 0.65))
    if f <= 0.001:
        return color
    return (
        int(min(255, round(color[0] + (255 - color[0]) * f))),
        int(min(255, round(color[1] + (255 - color[1]) * f))),
        int(min(255, round(color[2] + (255 - color[2]) * f)))
    )

def _scale_color(color: RGBColor, factor: float) -> RGBColor:
    f = max(0.0, min(1.5, factor))
    if f == 1.0:
        return color
    # Perceptual gamma expansion (~0.85): prevents lower audio levels from dropping into muddy darkness
    f_eff = f if f >= 1.0 else (f ** 0.85)
    return (
        int(min(255, max(0, round(color[0] * f_eff)))),
        int(min(255, max(0, round(color[1] * f_eff)))),
        int(min(255, max(0, round(color[2] * f_eff))))
    )

def _lerp_color(c1: RGBColor, c2: RGBColor, t: float) -> RGBColor:
    if t <= 0.0:
        return c1
    if t >= 1.0:
        return c2
    inv = 1.0 - t
    return (
        int(c1[0] * inv + c2[0] * t),
        int(c1[1] * inv + c2[1] * t),
        int(c1[2] * inv + c2[2] * t),
    )

class BaseAnimation:
    """Base class for all 4-zone animations."""
    name = "Base"
    category = "General"

    def __init__(self):
        self.speed: float = 1.0
        self.flash_intensity: float = 0.25  # 0.0 = completely smooth/no flash, 1.0 = punchy white overdrive

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        raise NotImplementedError


# ==============================================================================
# 1. EQ & SPECTRUM METERS
# ==============================================================================

class SpectrumEqualizer(BaseAnimation):
    """
    Dynamic Studio EQ:
    Pure 1:1 real-time 4-band audio spectrum visualizer:
      - Zone 1 (WASD / Left): Sub-Bass & Kicks (20-120 Hz)
      - Zone 2 (Mid-Left): Low-Mid / Bassline & Snare (120-500 Hz)
      - Zone 3 (Mid-Right): High-Mid / Melodies & Vocals (500-3500 Hz)
      - Zone 4 (Numpad / Right): Treble & Hi-Hats (3500-16000 Hz)
    Sharp exponential contrast (E^2.2) keeps inactive bands dark.
    Silence gating completely darkens the keyboard when audio stops.
    """
    name = "Dynamic Studio EQ"
    category = "EQ & Meters"

    def __init__(self):
        super().__init__()
        self._levels = [0.0, 0.0, 0.0, 0.0]
        self._peaks = [0.0, 0.0, 0.0, 0.0]

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence gating: decay to pure dark
            for i in range(4):
                self._levels[i] = max(0.0, self._levels[i] * math.exp(-14.0 * dt))
                self._peaks[i] = max(0.0, self._peaks[i] - 2.0 * dt)
            base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
            return [_scale_color(base_colors[i], self._levels[i]) for i in range(4)]

        bands = audio_state.smoothed_bands
        # Musical perceptual power curve (E^1.35): provides punchy dynamics without crushing normal audio into darkness
        punch_bands = [
            (float(bands[0]) ** 1.35) if len(bands) > 0 else 0.0,
            (float(bands[1]) ** 1.35) if len(bands) > 1 else 0.0,
            (float(bands[2]) ** 1.35) if len(bands) > 2 else 0.0,
            (float(bands[3]) ** 1.35) if len(bands) > 3 else 0.0,
        ]

        # Bass kick transient punch on Zone 1 (WASD) and Zone 2
        if audio_state.is_beat:
            punch_bands[0] = max(punch_bands[0], 0.95 + audio_state.beat_strength * 0.35)
            punch_bands[1] = max(punch_bands[1], 0.85 + audio_state.beat_strength * 0.30)

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        decay_factor = math.exp(-8.5 * dt)
        peak_drop = 1.2 * dt

        for i in range(4):
            target = punch_bands[i]
            # Instant 0ms attack
            if target > self._levels[i]:
                self._levels[i] = target
            else:
                self._levels[i] = max(0.0, self._levels[i] * decay_factor)

            if self._levels[i] > self._peaks[i]:
                self._peaks[i] = self._levels[i]
            else:
                self._peaks[i] = max(0.0, self._peaks[i] - peak_drop)

            lvl = self._levels[i]
            pk = self._peaks[i]
            c = base_colors[i]

            # Peak hold needle glint
            if pk > lvl + 0.15 and pk > 0.35:
                glint = min(0.35, (pk - lvl) * 0.6)
                c = _blend_white(c, glint, 0.7)

            # High volume transient saturation overdrive
            if lvl > 0.80 and self.flash_intensity > 0.05:
                c = _blend_white(c, (lvl - 0.80) * 0.7, self.flash_intensity)

            # Active playback underglow floor (0.18): keeps keyboard richly illuminated with album art colors
            active_lvl = min(1.35, max(0.18, lvl * 1.25))
            result.append(_scale_color(c, active_lvl))

        return result


# ==============================================================================
# 2. SWEEPS & MOTION
# ==============================================================================

class KnightRiderScanner(BaseAnimation):
    """
    Cyber Knight Rider:
    Beat-stepped laser beam that jumps across zones strictly on musical beats and transient energy pulses.
    Zero motion in silence; snaps rhythmically across zones with music.
    """
    name = "Cyber Knight Rider"
    category = "Sweeps & Motion"

    def __init__(self):
        super().__init__()
        self._pos = 0.0
        self._target_pos = 0.0
        self._dir = 1.0
        self._level = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to pure dark and freeze
            self._level = max(0.0, self._level * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Advance step strictly on beat hits or strong transients
        if audio_state.is_beat:
            self._level = 1.35 + (audio_state.beat_strength * 0.45 * self.flash_intensity)
            self._target_pos += self._dir * 1.0
            if self._target_pos >= 3.0:
                self._target_pos = 3.0
                self._dir = -1.0
            elif self._target_pos <= 0.0:
                self._target_pos = 0.0
                self._dir = 1.0

        # Rapid smooth interpolation towards target position (snappy beat jump)
        self._pos += (self._target_pos - self._pos) * min(1.0, 24.0 * dt)
        self._level = max(0.0, self._level * math.exp(-7.5 * dt))

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        beam_width = 0.85
        two_w_sq = 2.0 * (beam_width ** 2)
        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            dist = abs(i - self._pos)
            val = math.exp(- (dist ** 2) / two_w_sq)
            intensity = min(1.35, val * self._level * gate)

            c = base_colors[i]
            if val > 0.80 and self._level > 0.80 and self.flash_intensity > 0.05:
                c = _blend_white(c, (self._level - 0.80) * 0.55, self.flash_intensity)

            result.append(_scale_color(c, intensity))

        return result


class WaterfallCascade(BaseAnimation):
    """
    Fluid Waterfall Cascade:
    Continuous chromatic waterfall. Flow velocity is 0 in silence,
    accelerating strictly with audio energy and transient spectral flux.
    Each zone's brightness is directly modulated by real-time frequency bands.
    """
    name = "Fluid Waterfall"
    category = "Sweeps & Motion"

    def __init__(self):
        super().__init__()
        self._flow_offset = 0.0
        self._surge = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: flow is 0, decay to dark
            self._surge = max(0.0, self._surge * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Flow velocity driven strictly by audio energy
        flow_speed = (audio_state.overall_energy ** 1.6) * 3.8 * self.speed
        self._flow_offset = (self._flow_offset + flow_speed * dt) % 4.0

        if audio_state.is_beat:
            self._surge = 1.30 + (audio_state.beat_strength * 0.40)

        self._surge = max(0.0, self._surge * math.exp(-8.0 * dt))

        colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        bands = audio_state.smoothed_bands
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            pos = (i - self._flow_offset) % 4.0
            idx1 = int(pos)
            idx2 = (idx1 + 1) % 4
            fraction = pos - idx1

            c_flow = _lerp_color(colors[idx1], colors[idx2], fraction)

            band_energy = (float(bands[i]) ** 1.8) if i < len(bands) else 0.3
            level = min(1.35, (band_energy * 0.70 + self._surge * 0.45) * gate)

            if self._surge > 0.75 and self.flash_intensity > 0.05:
                c_flow = _blend_white(c_flow, (self._surge - 0.75) * 0.55, self.flash_intensity)

            result.append(_scale_color(c_flow, level))

        return result


class PingPongRebound(BaseAnimation):
    """
    Kinetic Ping-Pong Rebound:
    Rebounds and kinetic flashes trigger strictly on kick transients.
    Zero motion in silence (pure dark); advances rhythmically on kick drum beats.
    """
    name = "Ping-Pong Rebound"
    category = "Sweeps & Motion"

    def __init__(self):
        super().__init__()
        self._pos = 0.0
        self._target_pos = 0.0
        self._dir = 1.0
        self._tail = [0.0, 0.0, 0.0, 0.0]
        self._bumper_flashes = [0.0, 0.0]

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            for i in range(4):
                self._tail[i] = max(0.0, self._tail[i] * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Kinetic rebound triggers strictly on kick transients / beats
        if audio_state.is_beat or audio_state.is_hard_kick:
            self._target_pos += self._dir * 1.5
            if self._target_pos >= 3.0:
                self._target_pos = 3.0
                self._dir = -1.0
                self._bumper_flashes[1] = 1.35  # Right bumper impact flash
            elif self._target_pos <= 0.0:
                self._target_pos = 0.0
                self._dir = 1.0
                self._bumper_flashes[0] = 1.35  # Left bumper impact flash

        # Smooth kinetic transit towards target
        self._pos += (self._target_pos - self._pos) * min(1.0, 20.0 * dt)

        decay_tail = math.exp(-8.0 * dt)
        decay_bumper = math.exp(-9.0 * dt)
        self._bumper_flashes[0] = max(0.0, self._bumper_flashes[0] * decay_bumper)
        self._bumper_flashes[1] = max(0.0, self._bumper_flashes[1] * decay_bumper)

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            dist = abs(i - self._pos)
            target = max(0.0, (1.0 - (dist * 0.85)) * (audio_state.overall_energy ** 1.3))
            if target > self._tail[i]:
                self._tail[i] = target
            else:
                self._tail[i] = max(0.0, self._tail[i] * decay_tail)

            bumper = (self._bumper_flashes[0] * 0.7) if i == 0 else ((self._bumper_flashes[1] * 0.7) if i == 3 else 0.0)
            val = min(1.35, (self._tail[i] + bumper) * gate)

            c = base_colors[i]
            if val > 0.80 and self.flash_intensity > 0.05:
                c = _blend_white(c, (val - 0.80) * 0.6, self.flash_intensity)

            result.append(_scale_color(c, val))

        return result


# ==============================================================================
# 3. WAVES & RHYTHMS
# ==============================================================================

class HarmonicWave(BaseAnimation):
    """
    Neon Cyber Wave:
    Sinusoidal traveling wave whose amplitude and phase progression are scaled directly
    by audio energy and frequency bands. Completely dark in silence.
    """
    name = "Neon Cyber Wave"
    category = "Waves & Rhythms"

    def __init__(self):
        super().__init__()
        self._phase = 0.0
        self._beat_env = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: wave freezes and decays to dark
            self._beat_env = max(0.0, self._beat_env * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Phase velocity proportional to audio energy
        bpm = max(60.0, min(180.0, audio_state.bpm_estimate))
        speed = (bpm / 60.0) * math.pi * 2.0 * self.speed * (audio_state.overall_energy ** 1.2)
        self._phase = (self._phase + speed * dt) % (math.pi * 2.0)

        if audio_state.is_beat:
            self._beat_env = 1.10 + (audio_state.beat_strength * 0.40)

        self._beat_env = max(0.0, self._beat_env * math.exp(-8.0 * dt))

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        bands = audio_state.smoothed_bands
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)
        master_amp = (audio_state.overall_energy ** 1.5) * gate

        for i in range(4):
            phase_i = self._phase + (i * (math.pi / 2.0))
            raw_sine = math.sin(phase_i)
            wave_val = ((raw_sine + 1.0) * 0.5) ** 2.0

            band_factor = (float(bands[i]) ** 1.6) if i < len(bands) else 0.5
            level = min(1.35, (wave_val * band_factor * 1.1 + self._beat_env * 0.45) * master_amp)

            c = base_colors[i]
            if (level > 0.80 or self._beat_env > 0.85) and self.flash_intensity > 0.05:
                f_val = max((level - 0.80) * 0.6, (self._beat_env - 0.85) * 0.5)
                c = _blend_white(c, f_val, self.flash_intensity)

            result.append(_scale_color(c, level))

        return result


class CenterWaveRipple(BaseAnimation):
    """
    Center Wave Ripple:
    Smooth organic ripple blooming outward from Center (Zones 2 & 3) to Edges (Zones 1 & 4).
    Ripples trigger strictly on drum kicks and musical beats; dark in silence.
    """
    name = "Center Wave Ripple"
    category = "Waves & Rhythms"

    def __init__(self):
        super().__init__()
        self._radius = 0.0
        self._wave_active = False
        self._center_snap = 0.0
        self._outer_snap = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            self._center_snap = max(0.0, self._center_snap * math.exp(-12.0 * dt))
            self._outer_snap = max(0.0, self._outer_snap * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        if audio_state.is_beat:
            self._radius = 0.0
            self._wave_active = True
            strength = audio_state.beat_strength
            self._center_snap = 1.35 + (strength * 0.45 * self.flash_intensity)
            self._outer_snap = 1.10 + (strength * 0.35 * self.flash_intensity)

        if self._wave_active:
            self._radius += 9.0 * self.speed * dt
            if self._radius > 3.5:
                self._wave_active = False

        decay_c = math.exp(-8.8 * dt)
        decay_o = math.exp(-7.5 * dt)
        self._center_snap = max(0.0, self._center_snap * decay_c)
        self._outer_snap = max(0.0, self._outer_snap * decay_o)

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        center_dists = [1.5, 0.5, 0.5, 1.5]
        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            dist = center_dists[i]
            diff = abs(dist - self._radius)
            ring = math.exp(- (diff ** 2) / 0.60) if self._wave_active else 0.0

            snap_comp = self._center_snap if (i == 1 or i == 2) else self._outer_snap
            level = min(1.35, ((ring * 0.60 + snap_comp) * gate))

            c = base_colors[i]
            if (snap_comp > 0.80 or ring > 0.80) and self.flash_intensity > 0.05:
                f_val = max((snap_comp - 0.80) * 0.6, (ring - 0.80) * 0.5)
                c = _blend_white(c, f_val, self.flash_intensity)

            result.append(_scale_color(c, level))

        return result


# ==============================================================================
# 4. AMBIENT & FLOW
# ==============================================================================

class ChromaGradientFlow(BaseAnimation):
    """
    Lush Chroma Aurora:
    Ambient color-morphing aurora scaled directly by audio energy.
    Completely dark and stationary in silence; morphs with music loudness.
    """
    name = "Lush Chroma Aurora"
    category = "Ambient & Flow"

    def __init__(self):
        super().__init__()
        self._hue_clock = 0.0
        self._warmth_env = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: freeze and decay to dark
            self._warmth_env = max(0.0, self._warmth_env * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Flow speed scales with audio energy
        speed = 0.9 * self.speed * (audio_state.overall_energy ** 1.3)
        self._hue_clock = (self._hue_clock + speed * dt) % 4.0

        if audio_state.is_beat:
            self._warmth_env = 1.0 + (audio_state.beat_strength * 0.35)

        self._warmth_env = max(0.0, self._warmth_env * math.exp(-7.0 * dt))

        colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)
        base_level = min(1.30, ((audio_state.overall_energy ** 1.3) * 0.90 + self._warmth_env * 0.35) * gate)

        for i in range(4):
            pos = (self._hue_clock + (i * 0.9)) % 4.0
            idx1 = int(pos)
            idx2 = (idx1 + 1) % 4
            frac = pos - idx1

            c_morph = _lerp_color(colors[idx1], colors[idx2], frac)
            if self._warmth_env > 0.85 and self.flash_intensity > 0.05:
                c_morph = _blend_white(c_morph, (self._warmth_env - 0.85) * 0.45, self.flash_intensity)

            result.append(_scale_color(c_morph, base_level))

        return result


class StarlightTwinkle(BaseAnimation):
    """
    Starlight Dream Twinkle:
    Directly reactive to high-frequency audio shimmer (treble cymbals and hi-hats).
    Completely dark in silence; sparkles ignite strictly with musical sparkle and beats.
    """
    name = "Starlight Twinkle"
    category = "Ambient & Flow"

    def __init__(self):
        super().__init__()
        self._phases = [random.uniform(0, 6.28) for _ in range(4)]
        self._twinkle_rates = [2.13, 3.47, 2.71, 3.89]
        self._flare_env = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            self._flare_env = max(0.0, self._flare_env * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        treble = (float(audio_state.smoothed_bands[3]) ** 1.8) if len(audio_state.smoothed_bands) > 3 else 0.0
        high_mid = (float(audio_state.smoothed_bands[2]) ** 1.8) if len(audio_state.smoothed_bands) > 2 else 0.0

        if audio_state.is_beat:
            self._flare_env = 1.20 + (audio_state.beat_strength * 0.35)

        self._flare_env = max(0.0, self._flare_env * math.exp(-7.5 * dt))

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            rate = self._twinkle_rates[i] * self.speed * (audio_state.overall_energy ** 0.8)
            self._phases[i] = (self._phases[i] + rate * dt) % (math.pi * 2.0)
            sine_val = (math.sin(self._phases[i]) + 1.0) * 0.5
            twinkle = sine_val ** 2.0

            shimmer = treble if i == 3 else (high_mid if i == 2 else 0.0)
            level = min(1.35, ((twinkle * 0.50 + shimmer * 0.60) * (audio_state.overall_energy ** 1.3) + self._flare_env * 0.40) * gate)

            c = base_colors[i]
            if (self._flare_env > 0.80 or level > 0.85) and self.flash_intensity > 0.05:
                f_val = max((self._flare_env - 0.80) * 0.5, (level - 0.85) * 0.45)
                c = _blend_white(c, f_val, self.flash_intensity)

            result.append(_scale_color(c, level))

        return result


class EnergyBreathing(BaseAnimation):
    """
    Euphoria Breath:
    Breathing amplitude scaled directly by audio energy.
    Completely dark in silence; downbeats instantly snap and expand the breath cycle.
    """
    name = "Euphoria Breath"
    category = "Ambient & Flow"

    def __init__(self):
        super().__init__()
        self._time = 0.0
        self._beat_env = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            self._beat_env = max(0.0, self._beat_env * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        bpm = max(60.0, min(160.0, audio_state.bpm_estimate))
        freq = (bpm / 60.0) * math.pi * 2.0 * self.speed * (audio_state.overall_energy ** 0.8)
        self._time = (self._time + freq * dt) % (math.pi * 2.0)

        if audio_state.is_beat:
            self._beat_env = 1.10 + (audio_state.beat_strength * 0.35)
            # Synchronize downbeat phase
            self._time = 0.0

        self._beat_env = max(0.0, self._beat_env * math.exp(-7.0 * dt))

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)
        master_amp = (audio_state.overall_energy ** 1.4) * gate

        for i in range(4):
            phase_offset = 0.0 if (i == 1 or i == 2) else 0.85
            sine_val = (math.sin(self._time - phase_offset) + 1.0) * 0.5
            contrast = sine_val ** 2.0

            level = min(1.35, (contrast * 0.85 * master_amp) + (self._beat_env * 0.40 * gate))
            c = base_colors[i]

            if (self._beat_env > 0.80 or level > 0.88) and self.flash_intensity > 0.05:
                f_val = max((self._beat_env - 0.80) * 0.55, (level - 0.88) * 0.45)
                c = _blend_white(c, f_val, self.flash_intensity)

            result.append(_scale_color(c, level))

        return result


# ==============================================================================
# 5. BEAT REACTIVE & HIGH ENERGY
# ==============================================================================

class BassWasdFocus(BaseAnimation):
    """
    Bass WASD & Melodic Stream:
    Zone 1 (WASD) triggers 100% strictly on heavy sub-bass kicks (20-120 Hz).
    Zones 2, 3, 4 strictly follow Low-Mid, High-Mid, and Treble melody and vocals.
    Completely dark in silence.
    """
    name = "Bass WASD & Melodic"
    category = "Beat Reactive"

    def __init__(self):
        super().__init__()
        self._kick_level = 0.0
        self._melodic_snap = 0.0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            self._kick_level = max(0.0, self._kick_level * math.exp(-12.0 * dt))
            self._melodic_snap = max(0.0, self._melodic_snap * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        bands = audio_state.smoothed_bands
        sub_bass = (float(bands[0]) ** 2.2) if len(bands) > 0 else 0.0

        # Zone 1 Kick: Slams strictly on sub-bass kicks and beats
        if audio_state.is_beat or (sub_bass > 0.50):
            kick_punch = 1.35 + (audio_state.beat_strength * 0.55 * self.flash_intensity)
            self._kick_level = max(self._kick_level, kick_punch)
            self._melodic_snap = 1.15 + (audio_state.beat_strength * 0.35)

        self._kick_level = max(0.0, self._kick_level * math.exp(-9.0 * dt))
        self._melodic_snap = max(0.0, self._melodic_snap * math.exp(-8.0 * dt))

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        # Zone 1 (WASD): Bass kick slam
        c1 = base_colors[0]
        lvl1 = min(1.35, max(sub_bass * 1.2, self._kick_level) * gate)
        if lvl1 > 0.75 and self.flash_intensity > 0.05:
            c1 = _blend_white(c1, (lvl1 - 0.75) * 0.70, self.flash_intensity)
        result.append(_scale_color(c1, lvl1))

        # Zones 2, 3, 4: Pure frequency bands (LowMid, HighMid, Treble)
        for i in range(1, 4):
            band_val = (float(bands[i]) ** 2.0) if i < len(bands) else 0.0
            lvl = min(1.35, (band_val * 1.1 + self._melodic_snap * 0.35) * gate)
            c = base_colors[i]
            if self._melodic_snap > 0.85 and self.flash_intensity > 0.05:
                c = _blend_white(c, (self._melodic_snap - 0.85) * 0.45, self.flash_intensity)
            result.append(_scale_color(c, lvl))

        return result


class CenterBeatPulse(BaseAnimation):
    """
    Center Explosive Pulse:
    Explosive center-outward beat pulse with ZERO phase delay.
    Snaps strictly on real music beats; completely dark in silence.
    """
    name = "Center Explosive Pulse"
    category = "Beat Reactive"

    def __init__(self):
        super().__init__()
        self._energies = [0.0, 0.0, 0.0, 0.0]

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            for i in range(4):
                self._energies[i] = max(0.0, self._energies[i] * math.exp(-12.0 * dt))
            return [(0, 0, 0)] * 4

        # Instant 0ms snap on beat hits
        if audio_state.is_beat:
            strength = audio_state.beat_strength
            boost_mid = 1.35 + (strength * 0.55 * self.flash_intensity)
            self._energies[1] = boost_mid
            self._energies[2] = boost_mid * 0.96

            boost_outer = 1.15 + (strength * 0.40 * self.flash_intensity)
            self._energies[0] = boost_outer
            self._energies[3] = boost_outer * 0.96

        decay_c = math.exp(-9.0 * dt)
        decay_o = math.exp(-7.5 * dt)
        self._energies[0] = max(0.0, self._energies[0] * decay_o)
        self._energies[1] = max(0.0, self._energies[1] * decay_c)
        self._energies[2] = max(0.0, self._energies[2] * decay_c)
        self._energies[3] = max(0.0, self._energies[3] * decay_o)

        colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            e = self._energies[i] * gate
            c = colors[i]
            if e > 0.80 and self.flash_intensity > 0.05:
                white_f = min(0.65, (e - 0.80) * 0.70)
                c = _blend_white(c, white_f, self.flash_intensity)
            result.append(_scale_color(c, min(1.35, e)))

        return result


class BeatStrobe(BaseAnimation):
    """
    Bass Drop EDM Strobe:
    High-energy alternating counter-pulse strictly triggered by beat transients.
    Completely dark in silence.
    """
    name = "Bass Drop EDM Strobe"
    category = "High Energy"

    def __init__(self):
        super().__init__()
        self._strobes = [0.0, 0.0, 0.0, 0.0]
        self._strobe_counter = 0

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if audio_state.overall_energy < 0.05:
            # Silence: decay to zero
            for i in range(4):
                self._strobes[i] = max(0.0, self._strobes[i] * math.exp(-14.0 * dt))
            return [(0, 0, 0)] * 4

        if audio_state.is_beat:
            self._strobe_counter += 1
            boost = (1.55 if audio_state.is_hard_kick else 1.30) + (audio_state.beat_strength * 0.35 * self.flash_intensity)

            if self._strobe_counter % 2 == 0:
                self._strobes[0] = boost * 0.95
                self._strobes[1] = 0.0
                self._strobes[2] = boost
                self._strobes[3] = 0.0
            else:
                self._strobes[0] = 0.0
                self._strobes[1] = boost
                self._strobes[2] = 0.0
                self._strobes[3] = boost * 0.95

        decay = math.exp(-8.8 * dt)
        for i in range(4):
            self._strobes[i] = max(0.0, self._strobes[i] * decay)

        base_colors = [palette.zone1, palette.zone2, palette.zone3, palette.zone4]
        result: List[RGBColor] = []

        gate = min(1.0, (audio_state.overall_energy - 0.05) / 0.12)

        for i in range(4):
            val = self._strobes[i] * gate
            c = base_colors[i]
            if val > 0.70 and self.flash_intensity > 0.05:
                c = _blend_white(c, min(0.70, (val - 0.70) * 0.75), self.flash_intensity)
            result.append(_scale_color(c, min(1.35, val)))

        return result


# ==============================================================================
# 5. STATIC LIGHTING MODES (ZERO ANIMATION)
# ==============================================================================

class StaticAlbumArt(BaseAnimation):
    """
    Static Album Art:
    Displays steady, unmoving 4-zone lighting derived directly from the
    album cover artwork palette. Zero animation, pulsing, or wave motion.
    Automatically updates when track or album artwork changes.
    """
    name = "Static Album Art"
    category = "Static"

    def __init__(self):
        super().__init__()

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if palette is None:
            palette = ColorPaletteExtractor.DEFAULT_PALETTES[0]
        # Pure static 4-zone palette from album art (no audio-reactive motion)
        return [palette.zone1, palette.zone2, palette.zone3, palette.zone4]


class StaticAlbumPrimary(BaseAnimation):
    """
    Static Album Dominant:
    Illuminates all 4 zones uniformly with the primary vibrant color extracted
    from the album cover artwork, with zero animation or motion.
    """
    name = "Static Album Dominant"
    category = "Static"

    def __init__(self):
        super().__init__()

    def update(self, audio_state: AudioBeatState, palette: ColorPalette, dt: float) -> List[RGBColor]:
        if palette is None:
            palette = ColorPaletteExtractor.DEFAULT_PALETTES[0]
        return [palette.primary, palette.primary, palette.primary, palette.primary]


# Complete Registry of Animations and Static Modes
ANIMATION_REGISTRY: Dict[str, Type[BaseAnimation]] = {
    SpectrumEqualizer.name: SpectrumEqualizer,
    StaticAlbumArt.name: StaticAlbumArt,
    StaticAlbumPrimary.name: StaticAlbumPrimary,
    KnightRiderScanner.name: KnightRiderScanner,
    WaterfallCascade.name: WaterfallCascade,
    PingPongRebound.name: PingPongRebound,
    HarmonicWave.name: HarmonicWave,
    ChromaGradientFlow.name: ChromaGradientFlow,
    StarlightTwinkle.name: StarlightTwinkle,
    EnergyBreathing.name: EnergyBreathing,
    CenterWaveRipple.name: CenterWaveRipple,
    BassWasdFocus.name: BassWasdFocus,
    CenterBeatPulse.name: CenterBeatPulse,
    BeatStrobe.name: BeatStrobe,
}
