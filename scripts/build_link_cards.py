#!/usr/bin/env python3
"""Render the "Find me around the web" link cards into assets/link-*.svg, plus the
clickable bar for "A little more about me" (assets/more-about-me.svg).

Each card is a dark tile (matching the stat cards) with an icon, a name,
and the address. Edit CARDS and re-run:

    /usr/bin/python3 scripts/build_link_cards.py
"""

import base64
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

W, H = 280, 84
ICON = 52
BG = "#1a1b27"
BORDER = "#e4e2e2"
CREAM = "#f5ecd9"
PAPER = "#faf6ec"
MUTED = "#9aa0b8"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Fullspec Studio mark, from fullspecstudio.com/icon.svg (64x64 grid)
FULLSPEC_BARS = [
    (10, 23, 25, "#2e3a85"),
    (16.5, 28, 20, "#1f6a66"),
    (23, 30, 18, "#5f7a28"),
    (29.5, 25, 23, "#b3801f"),
    (36, 16, 32, "#b25a3e"),
    (42.5, 28, 20, "#7e402c"),
    (49, 32, 16, "#4a1d31"),
]

# LinkedIn mark from simple-icons (24x24 grid)
LINKEDIN_PATH = (
    "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414"
    "v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926"
    "-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 "
    "13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 "
    "24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"
)


def icon_avatar(x: float, y: float) -> str:
    data = base64.b64encode((ASSETS / "avatar-jedi.png").read_bytes()).decode()
    return (
        f'<clipPath id="tile"><rect x="{x}" y="{y}" width="{ICON}" height="{ICON}" rx="11"/></clipPath>'
        f'<rect x="{x}" y="{y}" width="{ICON}" height="{ICON}" rx="11" fill="{PAPER}"/>'
        # zoomed in so the face fills the tile; the source image is mostly lightsaber and robe
        f'<image clip-path="url(#tile)" x="{x - ICON * 0.36:.2f}" y="{y - ICON * 0.22:.2f}" '
        f'width="{ICON * 1.6:.2f}" height="{ICON * 1.6:.2f}" '
        f'href="data:image/png;base64,{data}"/>'
    )


def icon_fullspec(x: float, y: float) -> str:
    s = ICON / 64
    bars = "".join(
        f'<rect x="{x + bx * s:.2f}" y="{y + by * s:.2f}" width="{5 * s:.2f}" height="{bh * s:.2f}" '
        f'rx="{s:.2f}" fill="{color}"/>'
        for bx, by, bh, color in FULLSPEC_BARS
    )
    return f'<rect x="{x}" y="{y}" width="{ICON}" height="{ICON}" rx="11" fill="{PAPER}"/>{bars}'


def icon_linkedin(x: float, y: float) -> str:
    s = ICON / 24
    # white underlay so the letters read as white instead of showing the dark card through
    return (
        f'<rect x="{x + 4}" y="{y + 4}" width="{ICON - 8}" height="{ICON - 8}" fill="#fff"/>'
        f'<path transform="translate({x} {y}) scale({s:.4f})" fill="#0a66c2" d="{LINKEDIN_PATH}"/>'
    )


CARDS = [
    ("link-site.svg", "Personal site", "johnsonbrandon.com", icon_avatar),
    ("link-fullspec.svg", "Fullspec Studio", "fullspecstudio.com", icon_fullspec),
    ("link-linkedin.svg", "LinkedIn", "in/brandonbjohnson", icon_linkedin),
]


def build(title: str, address: str, icon) -> str:
    ix, iy = 16, (H - ICON) / 2
    tx = ix + ICON + 16
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="{title}: {address}">',
            f"<title>{title}: {address}</title>",
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="4.5" fill="{BG}" stroke="{BORDER}"/>',
            icon(ix, iy),
            f'<text x="{tx}" y="{H / 2 - 3}" fill="{CREAM}" font-family="{SANS}" font-size="16" '
            f'font-weight="600">{title}</text>',
            f'<text x="{tx}" y="{H / 2 + 17}" fill="{MUTED}" font-family="{MONO}" font-size="12">{address}</text>',
            f'<path d="M{W - 30} {H / 2 + 5}l8-8m-6.5 0h6.5v6.5" fill="none" stroke="{MUTED}" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
            "</svg>",
            "",
        ]
    )


def build_more_bar() -> str:
    """The clickable bar for the "A little more about me" section: a quiet one-line card,
    so it reads as part of the page rather than a call to action. The README puts it in a
    <picture> inside <summary>, because GitHub wraps a bare <img> in a link to the image,
    which would open the SVG instead of expanding the section."""
    bw, bh = 840, 44
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{bw}" height="{bh}" viewBox="0 0 {bw} {bh}" '
            'role="img" aria-label="A little more about me: click to expand">',
            "<title>A little more about me</title>",
            f'<rect x="0.5" y="0.5" width="{bw - 1}" height="{bh - 1}" rx="4.5" fill="{BG}" stroke="{BORDER}"/>',
            f'<text x="20" y="{bh / 2 + 4}" fill="{CREAM}" font-family="{SANS}" font-size="11" '
            'font-weight="600" letter-spacing="2">A LITTLE MORE ABOUT ME</text>',
            f'<text x="{bw - 44}" y="{bh / 2 + 4}" text-anchor="end" fill="{MUTED}" font-family="{SANS}" '
            'font-size="12">fun facts, languages, and links</text>',
            f'<path d="M{bw - 30} {bh / 2 - 3}l5 5 5-5" fill="none" stroke="{MUTED}" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
            "</svg>",
            "",
        ]
    )


if __name__ == "__main__":
    for filename, title, address, icon in CARDS:
        (ASSETS / filename).write_text(build(title, address, icon))
        print(f"wrote assets/{filename}")
    (ASSETS / "more-about-me.svg").write_text(build_more_bar())
    print("wrote assets/more-about-me.svg")
