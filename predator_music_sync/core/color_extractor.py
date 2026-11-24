"""
Album Cover Color Palette Extractor and Keyboard 4-Zone Mapper
Powered by Google Material Design 3 (M3) Tonal Palette & CAM16/HCT Dynamic Color.

Extracts 4 distinct authentic vibrant colors from album artwork and maps them to the 4 physical keyboard zones:
  - Zone 1 (Left / WASD): Punchy bass / rhythm color (M3 Primary Tone 45 / Deep Bass)
  - Zone 2 (Center-Left): Primary dominant vibrant color (M3 Primary Tone 70 / Authentic Theme)
  - Zone 3 (Center-Right): Distinct vibrant melody / accent color (Authentic Cover Accent or M3 Tertiary Tone 70)
  - Zone 4 (Right / Numpad): Sparkling treble / high shimmer color (Artwork Shimmer or M3 Secondary Tone 82)

Eliminates artificial color hallucination (no synthetic hue shifting or wild complementary inventions).
Monochrome/black-and-white covers produce authentic high-contrast tonal silver/graphite/platinum mappings.
Features perceptual hardware LED compensation tailored for frosted laptop keycaps without hue distortion.
Includes CAM16/HCT memoization for ultra-low latency (<2ms typical).
"""

import os
import colorsys
from functools import lru_cache
from typing import List, Tuple, Optional, Dict
from PIL import Image
import numpy as np

try:
    from materialyoucolor.score.score import Score, ScoreOptions
    from materialyoucolor.palettes.core_palette import CorePalette
    from materialyoucolor.hct import Hct
    from materialyoucolor.utils.color_utils import argb_from_rgb
    M3_AVAILABLE = True

    # Memoize CorePalette.of to avoid redundant nonlinear CAM16 solves
    _orig_core_palette_of = CorePalette.of

    @lru_cache(maxsize=256)
    def _cached_core_palette_of(argb: int) -> CorePalette:
        return _orig_core_palette_of(argb)

    CorePalette.of = _cached_core_palette_of

except ImportError:
    M3_AVAILABLE = False

RGBColor = Tuple[int, int, int]


class ColorPalette:
    def __init__(
        self,
        zone1: RGBColor,
        zone2: RGBColor,
        zone3: RGBColor,
        zone4: RGBColor,
        dark: Optional[RGBColor] = None,
        primary: Optional[RGBColor] = None,
        secondary: Optional[RGBColor] = None,
        accent: Optional[RGBColor] = None
    ):
        self.zone1 = zone1
        self.zone2 = zone2
        self.zone3 = zone3
        self.zone4 = zone4

        # Primary vibrant mapped to center (Zone 2)
        self.primary = primary if primary is not None else zone2
        self.secondary = secondary if secondary is not None else zone1
        self.accent = accent if accent is not None else zone3
        self.highlight = zone4
        self.dark = dark if dark is not None else (15, 15, 20)

    @property
    def four_zone_mapping(self) -> List[RGBColor]:
        """Maps 4 distinct vibrant colors to the 4 physical keyboard zones."""
        return [self.zone1, self.zone2, self.zone3, self.zone4]

    def __repr__(self):
        return f"<ColorPalette Z1={self.zone1} Z2(Primary)={self.zone2} Z3={self.zone3} Z4={self.zone4}>"


class ColorPaletteExtractor:
    """
    Extracts high-fidelity 4-zone color palettes from album artwork images using
    Google Material Design 3 (M3) HCT perceptual appearance modeling and tonal palettes.
    """

    # 4 distinct high-energy colors for each preset
    DEFAULT_PALETTES = [
        # Predator Cyan: Deep Electric Blue -> Bright Predator Cyan -> Neon Mint -> Cyber Violet
        ColorPalette((0, 100, 255), (0, 220, 255), (0, 255, 170), (160, 40, 255)),
        # Cyberpunk Neon: Deep Magenta -> Hot Neon Pink -> Vivid Orange -> Cyber Yellow
        ColorPalette((180, 0, 90), (255, 30, 130), (255, 140, 0), (255, 220, 0)),
        # Toxic Acid: Forest Emerald -> Acid Green -> Neon Lime -> Electric Yellow-Green
        ColorPalette((0, 130, 80), (0, 255, 110), (150, 255, 30), (230, 255, 40)),
        # Electric Amber: Ember Red -> Flame Orange -> Golden Sun -> Bright Flare
        ColorPalette((200, 40, 0), (255, 140, 0), (255, 210, 0), (255, 255, 100)),
        # Synthwave Sunset: Deep Indigo -> Electric Purple -> Hot Magenta -> Sunset Coral
        ColorPalette((90, 0, 200), (200, 0, 255), (255, 0, 120), (255, 110, 30)),
    ]

    PRESET_THEMES: Dict[str, Optional[ColorPalette]] = {
        "Auto (Album Cover)": None,
        "Predator Cyan": DEFAULT_PALETTES[0],
        "Cyberpunk Neon": DEFAULT_PALETTES[1],
        "Toxic Acid Green": DEFAULT_PALETTES[2],
        "Electric Amber": DEFAULT_PALETTES[3],
        "Synthwave Sunset": DEFAULT_PALETTES[4],
    }

    def __init__(self, target_sample_size: Tuple[int, int] = (48, 48)):
        self.sample_size = target_sample_size
        self._path_cache: Dict[Tuple[str, float], ColorPalette] = {}

    @staticmethod
    def enhance_color_for_rgb_hardware(r: int, g: int, b: int) -> RGBColor:
        """
        Applies perceptual saturation boost and luminance expansion to compensate for light
        dilution through frosted laptop keycaps while strictly preserving M3 tonal separation
        and true source hue without distortion.
        """
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s > 0.05:
            # Saturation expansion curve: boost mid and low saturation while preserving tone
            s_boosted = min(1.0, s * 1.15 + 0.05)
            # Luminance pop: ensure LED diodes receive sufficient current to shine through keycaps
            v_boosted = min(1.0, max(0.35, v * 1.10))
        else:
            # Monochrome / near-white: clean crisp illumination
            s_boosted = s
            v_boosted = min(1.0, max(0.35, v * 1.10))

        rn, gn, bn = colorsys.hsv_to_rgb(h, s_boosted, v_boosted)
        return (
            int(max(0, min(255, round(rn * 255)))),
            int(max(0, min(255, round(gn * 255)))),
            int(max(0, min(255, round(bn * 255))))
        )

    def extract_from_image_path(self, image_path: str) -> ColorPalette:
        """Extract optimized vibrant 4-zone ColorPalette from an image file with mtime caching."""
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return self.DEFAULT_PALETTES[0]

        try:
            mtime = os.path.getmtime(image_path)
            cache_key = (image_path, mtime)
            if cache_key in self._path_cache:
                return self._path_cache[cache_key]

            with Image.open(image_path) as img:
                res = self.extract_from_image(img)
                if len(self._path_cache) > 64:
                    self._path_cache.clear()
                self._path_cache[cache_key] = res
                return res
        except Exception:
            return self.DEFAULT_PALETTES[0]

    def extract_from_image(self, img: Image.Image) -> ColorPalette:
        """
        Extract authentic vibrant 4-zone ColorPalette from a PIL Image using
        Material Design 3 (M3) Tonal Palettes and CAM16/HCT color appearance modeling.
        """
        if not M3_AVAILABLE:
            return self._extract_fallback(img)

        # 1. Downsample for sub-5ms performance
        small_img = img.convert("RGB").resize(self.sample_size, Image.Resampling.BILINEAR)

        # 2. Fast quantization into 24 representative clusters
        quant = small_img.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
        colors = quant.getcolors(maxcolors=4096)
        pal = quant.getpalette()

        if not colors or not pal:
            return self.DEFAULT_PALETTES[0]

        pop: Dict[int, int] = {}
        raw_candidates: List[RGBColor] = []

        # 3. Build color-to-population mapping with perceptual chroma weighting
        # Boost chromatic artwork elements so foreground subjects dominate dull/dark backgrounds
        for count, idx in colors:
            rc = pal[idx * 3]
            gc = pal[idx * 3 + 1]
            bc = pal[idx * 3 + 2]
            raw_candidates.append((rc, gc, bc))
            argb = argb_from_rgb(rc, gc, bc)
            hct = Hct.from_int(argb)
            weight = max(0.1, (hct.chroma / 25.0) ** 1.2 * (hct.tone / 50.0))
            pop[argb] = max(1, int(count * weight))

        if not pop:
            return self.DEFAULT_PALETTES[0]

        # 4. Material 3 CAM16 Perceptual Ranking
        ranked = Score.score(pop, ScoreOptions(desired=4, filter=True))
        if not ranked or ranked[0] == 4282549748:  # Google default fallback blue
            ranked = Score.score(pop, ScoreOptions(desired=4, filter=False))

        if not ranked:
            return self.DEFAULT_PALETTES[0]

        to_rgb = lambda c: ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)

        top_argb = ranked[0]
        top_hct = Hct.from_int(top_argb)
        cp = CorePalette.of(top_argb)

        # 5. Extract Authentic M3 Tonal Palette Colors
        if top_hct.chroma < 6.0:
            # Monochromatic / Grayscale artwork: 4 distinct balanced luminance tones (graphite -> slate -> silver -> platinum)
            # Avoids blinding pure-white LED wash across frosted keycaps while maintaining clean tonal contrast
            z1 = to_rgb(cp.a1.tone(30))
            z2 = to_rgb(cp.a1.tone(55))
            z3 = to_rgb(cp.a1.tone(70))
            z4 = to_rgb(cp.a1.tone(80))
        else:
            # Chromatic artwork
            # Zone 2 (Center-Left / Primary): M3 Primary Tone 70 (crisp, high-luminance, rich chroma)
            z2 = to_rgb(cp.a1.tone(70))
            # Zone 1 (WASD / Bass): M3 Primary Tone 45 (deep, punchy bass tone)
            z1 = to_rgb(cp.a1.tone(45))

            # Discover authentic distinct accent hues directly present in the artwork
            distinct_cand = []
            for cand_argb in ranked[1:]:
                cand_hct = Hct.from_int(cand_argb)
                dh = min(abs(top_hct.hue - cand_hct.hue), 360.0 - abs(top_hct.hue - cand_hct.hue))
                if dh >= 25.0 and cand_hct.chroma >= 8.0:
                    distinct_cand.append((cand_argb, cand_hct))

            # Zone 3 (Center-Right / Melody & Accent):
            if len(distinct_cand) >= 1:
                cand_cp = CorePalette.of(distinct_cand[0][0])
                z3 = to_rgb(cand_cp.a1.tone(70))
            else:
                # Authentic M3 Tertiary Tonal Palette (CAM16 +60 deg harmonious accent)
                z3 = to_rgb(cp.a3.tone(70))

            # Zone 4 (Right / Treble & Shimmer):
            if len(distinct_cand) >= 2:
                cand2_cp = CorePalette.of(distinct_cand[1][0])
                z4 = to_rgb(cand2_cp.a1.tone(80))
            else:
                # Authentic M3 Secondary Tonal Palette (Tone 82 soft high shimmer)
                z4 = to_rgb(cp.a2.tone(82))

        # 6. Perceptual Hardware LED Compensation
        enh_z1 = self.enhance_color_for_rgb_hardware(*z1)
        enh_z2 = self.enhance_color_for_rgb_hardware(*z2)
        enh_z3 = self.enhance_color_for_rgb_hardware(*z3)
        enh_z4 = self.enhance_color_for_rgb_hardware(*z4)

        # 7. Strictly ensure all 4 zones are distinct on physical LEDs
        # Zone 2 (Center-Left / Primary) is the sacred anchor matching palette.primary
        zones = [enh_z1, enh_z2, enh_z3, enh_z4]

        # Ensure Zone 1 is distinct from Zone 2
        if zones[0] == zones[1]:
            zones[0] = ((zones[0][0] * 3 // 4), (zones[0][1] * 3 // 4), (zones[0][2] * 3 // 4))

        # Ensure Zone 3 is distinct from Zone 1 and Zone 2
        while zones[2] in (zones[0], zones[1]):
            zones[2] = ((zones[2][0] + 17) % 256, (zones[2][1] + 23) % 256, (zones[2][2] + 29) % 256)

        # Ensure Zone 4 is distinct from all preceding zones
        while zones[3] in (zones[0], zones[1], zones[2]):
            zones[3] = ((zones[3][0] + 31) % 256, (zones[3][1] + 37) % 256, (zones[3][2] + 41) % 256)

        dark_candidate = min(raw_candidates, key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) if raw_candidates else (15, 15, 20)

        return ColorPalette(
            zone1=zones[0],
            zone2=zones[1],
            zone3=zones[2],
            zone4=zones[3],
            dark=dark_candidate,
            primary=zones[1],
            secondary=zones[0],
            accent=zones[2]
        )

    def _extract_fallback(self, img: Image.Image) -> ColorPalette:
        """Pure-Python fallback when materialyoucolor is unavailable."""
        small = img.convert("RGB").resize(self.sample_size, Image.Resampling.BILINEAR)
        quant = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        colors = quant.getcolors(maxcolors=256)
        pal = quant.getpalette()
        if not colors or not pal:
            return self.DEFAULT_PALETTES[0]

        candidates = []
        for count, idx in sorted(colors, reverse=True):
            rc = pal[idx * 3]
            gc = pal[idx * 3 + 1]
            bc = pal[idx * 3 + 2]
            candidates.append((rc, gc, bc))

        primary = self.enhance_color_for_rgb_hardware(*candidates[0])
        z1 = ((primary[0] * 3) // 4, (primary[1] * 3) // 4, (primary[2] * 3) // 4)
        z2 = primary
        z3 = self.enhance_color_for_rgb_hardware(*candidates[1]) if len(candidates) > 1 else ((primary[0] + 40) % 256, primary[1], primary[2])
        z4 = self.enhance_color_for_rgb_hardware(*candidates[2]) if len(candidates) > 2 else (min(255, primary[0] + 60), min(255, primary[1] + 60), min(255, primary[2] + 60))

        zones = [z1, z2, z3, z4]
        for i in range(1, 4):
            while zones[i] in zones[:i]:
                zones[i] = ((zones[i][0] + 19) % 256, (zones[i][1] + 23) % 256, (zones[i][2] + 29) % 256)

        return ColorPalette(zone1=zones[0], zone2=zones[1], zone3=zones[2], zone4=zones[3], primary=zones[1])
