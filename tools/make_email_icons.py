"""Draw the round social media icons for the email footer (8 Nov 2026): IGSP's glyphs (templates/_social.html) in
white on a deep-orange circle, saved as PNG (email apps such as Gmail don't show SVG) with headless Google Chrome
into app/static/email/. Run from the project root:  python tools/make_email_icons.py
"""
import os
import subprocess
import sys
import tempfile

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "email")
DEEP = "#F26522"

GLYPHS = {
    "facebook": '<path fill="#fff" d="M13.5 21v-7.5h2.5l.4-3h-2.9V8.6c0-.9.3-1.5 1.5-1.5h1.5V4.4c-.3 0-1.2-.1-2.2-.1-2.2 0-3.7 '
                '1.3-3.7 3.8v2.4H8v3h2.6V21h2.9z"/>',
    "linkedin": '<path fill="#fff" d="M6.9 8.8H3.6V20h3.3V8.8zM5.2 3.5a1.9 1.9 0 1 0 0 3.9 1.9 1.9 0 0 0 0-3.9zM20.4 13.6c0-3-.6'
                '-5.1-4.1-5.1-1.7 0-2.8.9-3.2 1.8h-.1V8.8H9.9V20h3.3v-5.5c0-1.5.3-2.9 2.1-2.9s1.8 1.7 1.8 3V20h3.3v-6.4z"/>',
    "instagram": '<g fill="none" stroke="#fff" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/>'
                 '<circle cx="12" cy="12" r="4"/></g><circle cx="17.5" cy="6.5" r="1" fill="#fff"/>',
    "tiktok": '<path fill="#fff" d="M16.6 3h-3.1v12.3a2.7 2.7 0 1 1-2.7-2.7c.3 0 .6 0 .8.1V9.5a5.9 5.9 0 1 0 5 5.8V9.1a7.6 7.6 0 '
              '0 0 4.4 1.4V7.4A4.4 4.4 0 0 1 16.6 3z"/>',
    "youtube": '<path fill="#fff" d="M21.6 7.2a2.5 2.5 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.5 2.5 0 0 0 2.4 7.2 26 26 0 '
               '0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.8 1.8C5.8 19 12 19 12 19s6.2 0 7.8-.4a2.5 2.5 0 0 0 1.8-1.8A26 26 '
               '0 0 0 22 12a26 26 0 0 0-.4-4.8zM10 15V9l5.2 3L10 15z"/>',
}


def icon_svg(glyph):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 32 32">'
            f'<circle cx="16" cy="16" r="16" fill="{DEEP}"/><g transform="translate(6.5 6.5) scale(0.79)">{glyph}</g></svg>')


def main():
    if not os.path.exists(CHROME):
        sys.exit(f"Google Chrome not found at {CHROME}; set CHROME to its path.")
    os.makedirs(OUT, exist_ok=True)
    for name, glyph in GLYPHS.items():
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "page.html")
            with open(page, "w") as fh:
                fh.write(f'<!doctype html><html><body style="margin:0;background:transparent">{icon_svg(glyph)}'
                         f'</body></html>')
            subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                            "--default-background-color=00000000", "--window-size=64,64",
                            f"--screenshot={os.path.join(OUT, f'social-{name}.png')}", f"file://{page}"],
                           check=True, capture_output=True)
    print(f"Saved {len(GLYPHS)} icons in {OUT}")


if __name__ == "__main__":
    main()
