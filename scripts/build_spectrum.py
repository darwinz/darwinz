#!/usr/bin/env python3
"""Render the full-spectrum band for the profile README.

Each layer is a segment in the Fullspec Studio spectrum colors, with a
rotating list of tools underneath. Edit LAYERS and re-run:

    /usr/bin/python3 scripts/build_spectrum.py                  # static, to assets/spectrum.svg
    python3 scripts/build_spectrum.py --data dist/languages.json --out dist/spectrum.svg

With --data (written by build_languages.py), each segment's brightness shows
that layer's share of my commits over the last 90 days, and the busiest layer
pulses. The languages workflow does this daily.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# (layer, band color from fullspecstudio.com, tools shown in rotation)
LAYERS = [
    ("Systems Design", "#2e3a85", ["Distributed", "Event-driven", "API design", "OpenAPI", "gRPC", "Protobuf"]),
    ("Infra", "#1f6a66", ["AWS", "GCP", "Terraform", "Kubernetes", "Docker", "Vault"]),
    ("DevOps", "#5f7a28", ["GitHub Actions", "Prometheus", "Loki", "Traefik", "Packer", "Linux"]),
    ("Data", "#b3801f", ["Kafka", "PostgreSQL", "MySQL", "Redis", "Elasticsearch", "Spark"]),
    ("AI", "#b25a3e", ["Claude", "Bedrock", "Agents", "RAG", "Evals", "MCP"]),
    ("Backend", "#7e402c", ["Go", "Python", "Node.js", "Elixir", "Ruby", "Rust"]),
    ("Frontend", "#4a1d31", ["TypeScript", "React", "Vue", "Swift", "Dart", "Next.js"]),
]

W, H = 840, 172
PAD = 24
GAP = 4
SLOT = 2.0  # seconds each tool is shown
STAGGER = 0.25  # seconds between neighboring layers, so changes ripple left to right

BG = "#1a1b27"  # matches the tokyonight stat cards
BORDER = "#e4e2e2"
CREAM = "#f5ecd9"
MUTED = "#9aa0b8"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def tint(hex_color: str, amount: float = 0.68) -> str:
    """Mix a band color toward cream so it stays readable on the dark card."""
    a = [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(CREAM[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


MIN_OPACITY = 0.3  # quiet layers dim, but never go dark


def brightness(share: float, top: float) -> float:
    """Square root spreads out the small layers so they don't all look equally dim."""
    return MIN_OPACITY + (1 - MIN_OPACITY) * math.sqrt(share / top) if top else 1.0


def build(activity: dict | None = None) -> str:
    """activity: the "layers" object from languages.json, or None for the static band."""
    shares = activity["percent"] if activity else {}
    top = max(shares.values(), default=0)
    busiest = max(shares, key=shares.get) if top else None
    n_tools = len(LAYERS[0][2])
    assert all(len(t) == n_tools for _, _, t in LAYERS), "every layer needs the same number of tools"
    cycle = n_tools * SLOT
    show = 100 / n_tools  # percent of the cycle each tool owns
    seg_w = (W - 2 * PAD - GAP * (len(LAYERS) - 1)) / len(LAYERS)
    band_y, band_h = 58, 12

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-labelledby="title desc">',
        "<title id=\"title\">The full spectrum</title>",
        "<desc id=\"desc\">"
        + "; ".join(f"{name}: {', '.join(tools)}" for name, _, tools in LAYERS)
        + "</desc>",
        "<style>",
        f"  .tool {{ opacity: 0; animation: cycle {cycle:g}s linear infinite; }}",
        "  @keyframes cycle {",
        "    0% { opacity: 0; transform: translateY(5px); }",
        f"    {show * 0.18:.2f}% {{ opacity: 1; transform: translateY(0); }}",
        f"    {show * 0.82:.2f}% {{ opacity: 1; transform: translateY(0); }}",
        f"    {show:.2f}% {{ opacity: 0; transform: translateY(-5px); }}",
        "    100% { opacity: 0; }",
        "  }",
        "  .sheen { animation: sweep 9s ease-in-out infinite; }",
        "  @keyframes sweep {",
        f"    0% {{ transform: translateX(-160px); }}",
        f"    55% {{ transform: translateX({W + 40}px); }}",
        f"    100% {{ transform: translateX({W + 40}px); }}",
        "  }",
        "  .busiest { animation: pulse 3.2s ease-in-out infinite; }",
        "  @keyframes pulse {",
        "    0%, 100% { opacity: 1; }",
        "    50% { opacity: 0.35; }",
        "  }",
        "  @media (prefers-reduced-motion: reduce) {",
        "    .tool, .sheen, .busiest { animation: none; }",
        "    .tool.first { opacity: 1; }",
        "  }",
        "</style>",
        "<defs>",
        '  <linearGradient id="shine" x1="0" x2="1" y1="0" y2="0">',
        '    <stop offset="0" stop-color="#fff" stop-opacity="0"/>',
        '    <stop offset="0.5" stop-color="#fff" stop-opacity="0.55"/>',
        '    <stop offset="1" stop-color="#fff" stop-opacity="0"/>',
        "  </linearGradient>",
        '  <clipPath id="band">',
    ]
    for i in range(len(LAYERS)):
        x = PAD + i * (seg_w + GAP)
        out.append(f'    <rect x="{x:.2f}" y="{band_y}" width="{seg_w:.2f}" height="{band_h}" rx="3"/>')
    out += [
        "  </clipPath>",
        "</defs>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="4.5" fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="{PAD}" y="38" fill="{CREAM}" font-family="{SANS}" font-size="12" font-weight="600" '
        'letter-spacing="2.4">THE FULL SPECTRUM</text>',
        f'<text x="{W - PAD}" y="38" text-anchor="end" fill="{MUTED}" font-family="{SANS}" font-size="12" '
        'font-style="italic">infrastructure · interface · intelligence</text>',
    ]

    for i, (name, color, tools) in enumerate(LAYERS):
        x = PAD + i * (seg_w + GAP)
        opacity = brightness(shares.get(name, 0), top) if activity else 1.0
        if name == busiest:
            # a soft glow under the busiest layer that breathes in and out
            out.append(
                f'<rect class="busiest" x="{x - 3:.2f}" y="{band_y - 3}" width="{seg_w + 6:.2f}" '
                f'height="{band_h + 6}" rx="6" fill="{color}" opacity="0.45"/>'
            )
        out.append(
            f'<rect x="{x:.2f}" y="{band_y}" width="{seg_w:.2f}" height="{band_h}" rx="3" fill="{color}" '
            f'fill-opacity="{opacity:.2f}"/>'
        )
        out.append(
            f'<text x="{x:.2f}" y="{band_y + 38}" fill="{CREAM}" font-family="{SANS}" font-size="12" '
            f'font-weight="600">{name}</text>'
        )
        for j, tool in enumerate(tools):
            # Negative delays start every layer mid-cycle, so nothing is blank on first paint.
            delay = j * SLOT + i * STAGGER - cycle
            cls = "tool first" if j == 0 else "tool"
            out.append(
                f'<text class="{cls}" style="animation-delay:{delay:.2f}s" x="{x:.2f}" y="{band_y + 62}" '
                f'fill="{tint(color)}" font-family="{MONO}" font-size="12">{tool}</text>'
            )

    out += [
        f'<g clip-path="url(#band)"><rect class="sheen" x="0" y="{band_y}" width="140" height="{band_h}" '
        'fill="url(#shine)"/></g>',
        f'<text x="{PAD}" y="{H - 20}" fill="{MUTED}" font-family="{SANS}" font-size="11">'
        + (
            f"19 years across the stack · brightness shows my last {activity['window_days']} days of commits"
            if activity
            else "19 years across the stack, one layer at a time"
        )
        + "</text>",
        f'<text x="{W - PAD}" y="{H - 20}" text-anchor="end" fill="{MUTED}" font-family="{SANS}" '
        'font-size="11">fullspecstudio.com</text>',
        "</svg>",
    ]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="languages.json from build_languages.py")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "assets" / "spectrum.svg"))
    args = ap.parse_args()
    activity = json.loads(Path(args.data).read_text())["layers"] if args.data else None
    Path(args.out).write_text(build(activity))
    print(f"wrote {args.out}")
    if activity:
        for name, pct in activity["percent"].items():
            print(f"  {name:<16} {pct:5.1f}%  opacity {brightness(pct, max(activity['percent'].values())):.2f}")
