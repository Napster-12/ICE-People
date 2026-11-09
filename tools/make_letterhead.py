"""Draw the letterhead footer images for offer letters and contracts (8 Nov 2026), after the footer of Icebolethu's
current offer letter: three round contact icons (phone, address, web) and the patterned orange band.

They're drawn as SVG and saved as PNG with headless Google Chrome (xhtml2pdf can't draw SVG), into
app/static/documents/. Run from the project root:  python tools/make_letterhead.py
"""
import math
import os
import random
import subprocess
import sys
import tempfile

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "documents")
ORANGE, DEEP = "#F08422", "#F26522"

ICONS = {
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07'
             '-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 '
             '6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9v12h14V9"/><path d="M10 21v-6h4v6"/>',
    "web": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 '
           '10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
}


def icon_svg(paths):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24">'
            f'<circle cx="12" cy="12" r="12" fill="{DEEP}"/>'
            f'<g transform="translate(6 6) scale(0.5)" fill="none" stroke="#fff" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round">{paths}</g></svg>')


def band_svg(width=2400, height=120, seed=7):
    """An orange band with bursts of pale dashes, like the sunburst pattern on the current letterhead."""
    rnd = random.Random(seed)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             f'<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{ORANGE}"/>'
             f'<stop offset="1" stop-color="{DEEP}"/></linearGradient></defs>',
             f'<rect width="{width}" height="{height}" fill="url(#g)"/>']
    for cx in range(90, width, 190):
        cy = height / 2 + rnd.uniform(-10, 10)
        for ring, (radius, count) in enumerate(((14, 10), (30, 16), (50, 22))):
            for k in range(count):
                angle = 2 * math.pi * k / count + rnd.uniform(-0.12, 0.12) + ring * 0.2
                r1 = radius + rnd.uniform(-3, 3)
                r2 = r1 + rnd.uniform(6, 11)
                x1, y1 = cx + r1 * math.cos(angle), cy + r1 * math.sin(angle)
                x2, y2 = cx + r2 * math.cos(angle), cy + r2 * math.sin(angle)
                if 2 < y1 < height - 2 and 2 < y2 < height - 2:
                    parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                                 f'stroke="#FDE3CF" stroke-opacity="{rnd.uniform(.55, .9):.2f}" '
                                 f'stroke-width="{rnd.uniform(2.5, 4.5):.1f}" stroke-linecap="round"/>')
    parts.append("</svg>")
    return "".join(parts)


def shoot(svg, width, height, out, scale=1):
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w") as fh:
            fh.write(f'<!doctype html><html><body style="margin:0;background:transparent">{svg}</body></html>')
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
                        f"--force-device-scale-factor={scale}", f"--window-size={width},{height}",
                        f"--screenshot={out}", f"file://{page}"], check=True, capture_output=True)


def main():
    if not os.path.exists(CHROME):
        sys.exit(f"Google Chrome not found at {CHROME}; set CHROME to its path.")
    os.makedirs(OUT, exist_ok=True)
    for name, paths in ICONS.items():
        shoot(icon_svg(paths), 96, 96, os.path.join(OUT, f"icon-{name}.png"))
    shoot(band_svg(), 2400, 120, os.path.join(OUT, "band.png"))
    print(f"Saved the icons and band in {OUT}")


if __name__ == "__main__":
    main()
