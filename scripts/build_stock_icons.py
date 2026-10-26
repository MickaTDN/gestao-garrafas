"""Compile Stock's green cup directly from the same original PDF raster alpha.

No tracing or redrawing. Main application icons and full logo are never modified.
"""

from pathlib import Path

from PIL import Image, ImageOps

from scripts.build_brand_icons import BRAND_ROOT, SYMBOL, original_ink


def build():
    root = Path(__file__).resolve().parents[1] / "vertente" / "assets"
    ink = original_ink(BRAND_ROOT / SYMBOL)
    for size in (192, 512):
        mask = ImageOps.contain(
            ink, (round(size * 0.72), round(size * 0.72)), Image.Resampling.LANCZOS
        )
        image = Image.new("RGB", (size, size), (246, 243, 238))
        image.paste((16, 46, 40), ((size - mask.width) // 2, (size - mask.height) // 2), mask)
        image.save(root / f"icon-{size}.png", optimize=True)


if __name__ == "__main__":
    build()
