"""Generate the dashboard swatch images served at /brizlabs_static/.

Run from the repo root:  python3 scripts/make_swatches.py
Scene tiles show each scene's default app colours as a dot grid; palette
tiles show the palette as vertical stripes, like the app's swatches.
"""

import colorsys
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.brizlabs.rgb import scenes as S  # noqa: E402

OUT = ROOT / "custom_components" / "brizlabs" / "www"
W, H, LABEL_H = 240, 150, 34
BG = "#1c1c1e"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def rgb(c) -> str:
    r, g, b = colorsys.hsv_to_rgb((c.hue % 360) / 360, c.saturation / 1000, max(c.value, 350) / 1000)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def frame(body: str, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            f'<rect width="{W}" height="{H}" rx="14" fill="{BG}"/>{body}'
            f'<text x="{W / 2}" y="{H - 12}" text-anchor="middle" fill="#f2f2f7" '
            f'font-family="-apple-system,Segoe UI,Roboto,sans-serif" font-size="17" '
            f'font-weight="600">{escape(label)}</text></svg>\n')


def scene_svg(name: str, colors) -> str:
    cols, rows, pad = 16, 6, 12
    gw, gh = W - 2 * pad, H - LABEL_H - 2 * pad + 4
    cw, ch = gw / cols, gh / rows
    dots = []
    for y in range(rows):
        for x in range(cols):
            c = colors[(x * len(colors)) // cols]
            dots.append(f'<rect x="{pad + x * cw + 1:.1f}" y="{pad + y * ch + 1:.1f}" '
                        f'width="{cw - 2:.1f}" height="{ch - 2:.1f}" rx="2.5" fill="{rgb(c)}"/>')
    return frame("".join(dots), name)


def palette_svg(name: str, colors) -> str:
    pad = 12
    gw, gh = W - 2 * pad, H - LABEL_H - pad - 4
    sw = gw / len(colors)
    clip = (f'<clipPath id="r"><rect x="{pad}" y="{pad}" width="{gw}" height="{gh}" rx="10"/></clipPath>')
    stripes = "".join(f'<rect x="{pad + i * sw:.1f}" y="{pad}" width="{sw + 0.5:.1f}" height="{gh}" '
                      f'fill="{rgb(c)}"/>' for i, c in enumerate(colors))
    return frame(f'<defs>{clip}</defs><g clip-path="url(#r)">{stripes}</g>', name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    for sid, name in S.SCENE_NAMES.items():
        colors = S.decode_scene(S.default_scene_payload(sid)).colors
        (OUT / f"scene_{slug(name)}.svg").write_text(scene_svg(name, colors))
    for name, colors in S.PRESET_PALETTES:
        (OUT / f"palette_{slug(name)}.svg").write_text(palette_svg(name, colors))
    print(f"wrote {len(list(OUT.glob('*.svg')))} images to {OUT}")


if __name__ == "__main__":
    main()
