"""
Generates the Predator Music Sync multi-resolution Windows icon asset.
Corsair electric yellow (#FFD100) and pure stealth black (#0A0A0A) aesthetic.
Mipmaps: 16x16, 24x24, 32x32, 48x48, 64x64, 128x128, 256x256.
"""

import os
from PIL import Image, ImageDraw

def render_predator_emblem(size: int = 1024) -> Image.Image:
    # High-resolution canvas for anti-aliasing downsampling
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Coordinates in 0.0 - 1.0 normalized space
    def p(x, y):
        return (int(x * size), int(y * size))

    CORSAIR_YELLOW = (255, 209, 0, 255)
    CORSAIR_YELLOW_MUTED = (220, 180, 0, 255)
    STEALTH_BLACK = (10, 10, 10, 255)
    DARK_PANEL = (18, 18, 18, 255)
    HAIRLINE_BORDER = (45, 45, 45, 255)

    # 1. Outer rounded shield plate
    pad = 0.04
    radius = int(size * 0.18)
    draw.rounded_rectangle(
        [p(pad, pad), p(1.0 - pad, 1.0 - pad)],
        radius=radius,
        fill=STEALTH_BLACK,
        outline=CORSAIR_YELLOW,
        width=int(size * 0.028)
    )

    # Inner subtle hairline accent
    inner_pad = 0.075
    draw.rounded_rectangle(
        [p(inner_pad, inner_pad), p(1.0 - inner_pad, 1.0 - inner_pad)],
        radius=int(radius * 0.8),
        fill=DARK_PANEL,
        outline=HAIRLINE_BORDER,
        width=int(size * 0.012)
    )

    # 2. Geometric Predator Emblem (Symmetrical aggressive dual-fangs + crown)
    # Left Main Horn/Fang
    left_fang = [
        p(0.22, 0.26),  # top outer tip
        p(0.35, 0.26),  # top inner notch
        p(0.38, 0.46),  # mid inner
        p(0.33, 0.74),  # bottom fang tip
        p(0.24, 0.60),  # outer mid
        p(0.24, 0.38),  # outer upper
    ]
    draw.polygon(left_fang, fill=CORSAIR_YELLOW)

    # Right Main Horn/Fang (Mirror)
    right_fang = [
        p(0.78, 0.26),
        p(0.65, 0.26),
        p(0.62, 0.46),
        p(0.67, 0.74),
        p(0.76, 0.60),
        p(0.76, 0.38),
    ]
    draw.polygon(right_fang, fill=CORSAIR_YELLOW)

    # Center Crown / Blade
    center_crown = [
        p(0.50, 0.20),  # Top peak
        p(0.58, 0.34),  # Right shoulder
        p(0.55, 0.58),  # Right waist
        p(0.50, 0.70),  # Bottom point
        p(0.45, 0.58),  # Left waist
        p(0.42, 0.34),  # Left shoulder
    ]
    draw.polygon(center_crown, fill=CORSAIR_YELLOW)

    # Center Blade Inner Cutout (Pure black slit for predator helmet look)
    center_slit = [
        p(0.50, 0.30),
        p(0.53, 0.44),
        p(0.50, 0.60),
        p(0.47, 0.44),
    ]
    draw.polygon(center_slit, fill=STEALTH_BLACK)

    # Lower Chevrons / Fangs (Aggressive jaw teeth)
    left_jaw = [
        p(0.40, 0.62),
        p(0.45, 0.64),
        p(0.40, 0.80),
        p(0.36, 0.78),
    ]
    draw.polygon(left_jaw, fill=CORSAIR_YELLOW_MUTED)

    right_jaw = [
        p(0.60, 0.62),
        p(0.55, 0.64),
        p(0.60, 0.80),
        p(0.64, 0.78),
    ]
    draw.polygon(right_jaw, fill=CORSAIR_YELLOW_MUTED)

    return img

def generate_icons(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    base_img = render_predator_emblem(1024)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    
    for s in sizes:
        resized = base_img.resize((s, s), Image.Resampling.LANCZOS)
        images.append(resized)
        # Also export PNG mipmaps if needed
        resized.save(os.path.join(output_dir, f"icon_{s}x{s}.png"))

    # Save high-res PNG
    base_img.resize((256, 256), Image.Resampling.LANCZOS).save(
        os.path.join(output_dir, "predator_icon.png")
    )

    # Save standard Windows .ico with all required mipmaps
    ico_path = os.path.join(output_dir, "predator_icon.ico")
    # In Pillow, to save multi-resolution ICO, save the largest image and pass others in append_images
    largest = images[-1]  # 256x256
    largest.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes]
    )
    print(f"Generated multi-resolution ICO at: {ico_path} with sizes: {sizes}")
    print(f"Generated 256x256 PNG at: {os.path.join(output_dir, 'predator_icon.png')}")

if __name__ == "__main__":
    generate_icons("assets")
