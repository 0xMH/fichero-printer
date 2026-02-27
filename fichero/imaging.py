"""Image processing for Fichero D11s thermal label printer."""

import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from fichero.printer import PRINTHEAD_PX

log = logging.getLogger(__name__)


def floyd_steinberg_dither(img: Image.Image) -> Image.Image:
    """Floyd-Steinberg error-diffusion dithering to 1-bit.

    Same algorithm as PrinterImageProcessor.ditherFloydSteinberg() in the
    decompiled Fichero APK: distributes quantisation error to neighbouring
    pixels with weights 7/16, 3/16, 5/16, 1/16.
    """
    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape

    for y in range(h):
        for x in range(w):
            old = arr[y, x]
            new = 0.0 if old < 128 else 255.0
            arr[y, x] = new
            err = old - new
            if x + 1 < w:
                arr[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    arr[y + 1, x - 1] += err * 3 / 16
                arr[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    arr[y + 1, x + 1] += err * 1 / 16

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L")


def prepare_image(
    img: Image.Image, max_rows: int = 240, dither: bool = True
) -> Image.Image:
    """Convert any image to 96px wide, 1-bit, black on white.

    When *dither* is True (default), uses Floyd-Steinberg error diffusion
    for better quality on photos and gradients.  Set False for crisp text.
    """
    img = img.convert("L")
    w, h = img.size
    new_h = int(h * (PRINTHEAD_PX / w))
    img = img.resize((PRINTHEAD_PX, new_h), Image.LANCZOS)

    if new_h > max_rows:
        log.warning("Image height %dpx exceeds max %dpx, cropping bottom", new_h, max_rows)
        img = img.crop((0, 0, PRINTHEAD_PX, max_rows))

    img = ImageOps.autocontrast(img, cutoff=1)

    if dither:
        img = floyd_steinberg_dither(img)

    # Pack to 1-bit.  PIL mode "1" tobytes() uses 0-bit=black, 1-bit=white,
    # but the printer wants 1-bit=black.  Mapping dark->1 via point() inverts
    # the PIL convention so the final packed bits match what the printer needs.
    img = img.point(lambda x: 1 if x < 128 else 0, "1")
    return img


def image_to_raster(img: Image.Image) -> bytes:
    """Pack 1-bit image into raw raster bytes, MSB first."""
    if img.mode != "1":
        raise ValueError(f"Expected mode '1', got '{img.mode}'")
    if img.width != PRINTHEAD_PX:
        raise ValueError(f"Expected width {PRINTHEAD_PX}, got {img.width}")
    return img.tobytes()


def text_to_image(text: str, font_size: int = 30, label_height: int = 240) -> Image.Image:
    """Render crisp 1-bit text, rotated 90 degrees for label printing."""
    canvas_w = label_height
    canvas_h = PRINTHEAD_PX
    img = Image.new("L", (canvas_w, canvas_h), 255)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # disable antialiasing - pure 1-bit glyph rendering

    font = ImageFont.load_default(size=font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (canvas_w - tw) // 2 - bbox[0]
    y = (canvas_h - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=0, font=font)

    img = img.rotate(90, expand=True)
    return img
