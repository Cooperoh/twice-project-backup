"""Heading-aware drone marker icon, shared by all map pages.

Icons are cached by 2-degree heading and rendered size. ImageTk.PhotoImage
objects are kept alive inside _cache to prevent Tkinter garbage-collection.
"""
from PIL import Image, ImageDraw, ImageTk

_STEP = 2  # cache granularity (degrees)
_cache: dict[tuple[int, int], ImageTk.PhotoImage] = {}


def get(heading_deg: float, size: int = 44) -> ImageTk.PhotoImage:
    """Return a navigation-arrow icon rotated to *heading_deg* (0 = north, CW)."""
    angle = quantize(heading_deg)
    size = max(1, int(round(size)))
    key = (angle, size)
    if key not in _cache:
        _cache[key] = _render(angle, size)
    return _cache[key]


def quantize(heading_deg: float) -> int:
    """Return the cache key for *heading_deg* (used to detect icon changes)."""
    return int(round(heading_deg / _STEP)) * _STEP % 360


def _render(angle: int, size: int) -> ImageTk.PhotoImage:
    n = size
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Arrow pointing up (north). Four vertices: tip, bottom-right, notch, bottom-left.
    pts = [
        (n * 0.50, n * 0.04),
        (n * 0.85, n * 0.80),
        (n * 0.50, n * 0.58),
        (n * 0.15, n * 0.80),
    ]
    outline_width = max(1, int(round(size / 44)))
    draw.polygon(pts, fill="#E8232A", outline="#8B0000", width=outline_width)
    # PIL rotate is counter-clockwise; negate to get clockwise (compass) rotation.
    return ImageTk.PhotoImage(img.rotate(-angle, resample=Image.BICUBIC))
