"""Compile platform icon assets from the supplied original raster, without tracing.

Only crop empty margins, uniformly resample and map the original ink to white.
No paths, generative artwork, thresholded edges or reconstructed details are used.
"""

from pathlib import Path

from PIL import Image, ImageOps

BRAND_ROOT = Path(__file__).resolve().parent.parent / "static" / "branding"
SYMBOL = "copo-com-vida-simbolo-original.png"
BACKGROUND = (16, 46, 40)  # #102e28, approved dark green.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def original_ink(source):
    with Image.open(source) as image:
        grey = image.convert("L")
    # The PDF raster has dark grey ink on white. Preserve intermediate alpha
    # values, normalizing its darkest ink to opaque white rather than redrawing.
    darkest, _ = grey.getextrema()
    if darkest == 255:
        raise ValueError("O original não contém um símbolo visível.")
    alpha = grey.point([round((255 - value) * 255 / (255 - darkest)) for value in range(256)])
    return alpha.crop(alpha.getbbox())


def render_icon(ink, size):
    # Fit entirely inside the central 72% square. For this tall original this
    # also lies inside the circular maskable safe area, including corners.
    extent = round(size * 0.72)
    mask = ImageOps.contain(ink, (extent, extent), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (size, size), BACKGROUND)
    position = ((size - mask.width) // 2, (size - mask.height) // 2)
    image.paste((255, 255, 255), position, mask)
    return image


def build_icons(root=BRAND_ROOT):
    root = Path(root)
    ink = original_ink(root / SYMBOL)
    for size in (192, 512):
        render_icon(ink, size).save(root / f"copo-com-vida-{size}.png", optimize=True)
    images = [render_icon(ink, size) for size in ICON_SIZES]
    images[-1].save(
        root / "copo-com-vida.ico",
        format="ICO",
        sizes=[(size, size) for size in ICON_SIZES],
        append_images=images[:-1],
    )


if __name__ == "__main__":
    build_icons()
