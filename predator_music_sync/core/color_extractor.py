"""
Album Cover Color Palette Extractor and Keyboard 4-Zone Mapper
Extracts 4 distinct vibrant colors from album artwork and maps them to the 4 physical keyboard zones:
  - Zone 1 (Left / WASD): Punchy bass / rhythm color
  - Zone 2 (Center-Left): Primary dominant vibrant color
  - Zone 3 (Center-Right): Distinct vibrant melody / accent color
  - Zone 4 (Right / Numpad): Sparkling treble / high shimmer color
Ensures all 4 zones on the Acer Predator Helios Neo 16 are visibly distinct and responsive.
"""

import os
from typing import List, Tuple, Optional, Dict
from PIL import Image
import numpy as np

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
    Extracts high-quality 4-zone color palettes from images using fast quantization
    and perceptual vibrancy weighting.
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

    def __init__(self, target_sample_size: Tuple[int, int] = (64, 64)):
        self.sample_size = target_sample_size

    @staticmethod
    def _color_vibrancy_score(r: int, g: int, b: int) -> float:
        """
        Perceptual vibrancy score based on saturation and contrast.
        Filters out muddy grays, near-blacks, and washed-out whites.
        """
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        chroma = max_c - min_c
        luminance = 0.299 * r + 0.587 * g + 0.114 * b

        if luminance < 25 or luminance > 245:
            return 0.1 * (chroma / 255.0)

        saturation = chroma / (max_c + 1e-5)
        return saturation * 1.6 + (luminance / 255.0) * 0.4

    def extract_from_image_path(self, image_path: str) -> ColorPalette:
        """Extract optimized 4-zone ColorPalette from an image file."""
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return self.DEFAULT_PALETTES[0]

        try:
            with Image.open(image_path) as img:
                return self.extract_from_image(img)
        except Exception:
            return self.DEFAULT_PALETTES[0]

    def extract_from_image(self, img: Image.Image) -> ColorPalette:
        """Extract optimized 4-zone ColorPalette from a PIL Image object."""
        small_img = img.convert("RGB").resize(self.sample_size, Image.Resampling.BILINEAR)

        # Quantize into 16 clusters to ensure ample candidate colors
        quantized = small_img.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        raw_palette = quantized.getpalette()[:48]

        colors: List[RGBColor] = []
        for i in range(0, len(raw_palette), 3):
            colors.append((raw_palette[i], raw_palette[i+1], raw_palette[i+2]))

        if not colors:
            return self.DEFAULT_PALETTES[0]

        scored = []
        for c in colors:
            score = self._color_vibrancy_score(c[0], c[1], c[2])
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Select up to 4 distinct vibrant colors with Euclidean distance threshold
        chosen: List[RGBColor] = []
        for _, c in scored:
            if all(np.sqrt(sum((a - b) ** 2 for a, b in zip(c, prev))) > 35 for prev in chosen):
                chosen.append(c)
                if len(chosen) == 4:
                    break

        # If image lacks 4 distinct colors, synthesize harmonic triadic/complementary variants
        while len(chosen) < 4:
            base = chosen[0] if chosen else (0, 200, 255)
            shift_idx = len(chosen)
            if shift_idx == 1:
                # Complementary or hue rotated
                variant = (base[1], base[2], base[0])
            elif shift_idx == 2:
                variant = (int(base[0] * 0.6 + base[2] * 0.4), int(base[1] * 0.8), int(base[2] * 0.5 + 100))
            else:
                variant = (min(255, base[0] + 60), min(255, base[1] + 80), max(0, base[2] - 40))
            c_clamped = (min(255, max(0, variant[0])), min(255, max(0, variant[1])), min(255, max(0, variant[2])))
            chosen.append(c_clamped)

        # Map to 4 distinct zones:
        # Zone 2 (Center-Left) = Dominant Primary Vibrant (chosen[0])
        # Zone 3 (Center-Right) = Distinct Vibrant Melody (chosen[1])
        # Zone 1 (Left) = Bass Punch Tone (chosen[2])
        # Zone 4 (Right) = High Shimmer Tone (chosen[3])
        z1 = chosen[2]
        z2 = chosen[0]
        z3 = chosen[1]
        z4 = chosen[3]

        dark = min(colors, key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])

        return ColorPalette(zone1=z1, zone2=z2, zone3=z3, zone4=z4, dark=dark)
