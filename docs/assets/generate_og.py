#!/usr/bin/env python3
"""Generate OG image (1200×630) and screenshot.png (800×600) for GitHub social preview."""
import subprocess
from PIL import Image, ImageDraw, ImageFont

W = 1200
H = 630

# ── colours ──────────────────────────────────────────────
BG       = (15, 23, 42)       # slate-900
PURPLE   = (124, 58, 237)     # violet-600
CYAN     = (6, 182, 212)      # cyan-500
GREEN    = (45, 212, 191)     # teal-400
WHITE    = (248, 250, 252)    # slate-50
GRAY     = (148, 163, 184)    # slate-400
DARK_CARD = (30, 41, 59)      # slate-800

def find_font(size, bold=False):
    """Find a decent monospace or sans font."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    sources = bold_candidates if bold else candidates
    for p in sources:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    # fallback default
    return ImageFont.load_default()

def round_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)

def draw_terminal_window(draw, x, y, w, h):
    """Draw a stylised terminal window."""
    # window frame
    round_rect(draw, (x, y, x+w, y+h), 12, DARK_CARD)
    # title bar dots
    for dx, col in [(4, (239, 68, 68)), (14, (234, 179, 8)), (24, (34, 197, 94))]:
        draw.ellipse([x+dx, y+8, x+dx+8, y+16], fill=col)
    # code lines
    lines = [
        ("$", GRAY, " ./santana.sh", GREEN),
        ("", None, "", None),
        ("  ╭─ Santana v2.0.0 ─────────────────╮", GRAY, None, None),
        ("  │  Agent: DeepSeek V4 Flash        │", WHITE, None, None),
        ("  │  Memory: 3-layer (SQLite + VDB)  │", WHITE, None, None),
        ("  │  Tools: 15 · Fallback chain ✓    │", WHITE, None, None),
        ("  │  Cost: <$10/month LLM            │", GREEN, None, None),
        ("  ╰──────────────────────────────────╯", GRAY, None, None),
        ("", None, "", None),
        ("  ✓ Telegram connected", CYAN, "  |  ✓ Discord connected", CYAN),
        ("  ✓ Self-model initialized", PURPLE, "  |  ✓ Cron active", PURPLE),
        ("", None, "", None),
        ("  🧠 santana@agent → ready.", CYAN, "", None),
    ]
    line_h = 16
    start_y = y + 32
    font = find_font(13)
    for i, parts in enumerate(lines):
        text1, colour1, text2, colour2 = parts
        if not text1 and not text2:
            continue
        if text1:
            draw.text((x+14, start_y + i*line_h), text1, fill=colour1 or GRAY, font=font)
        if text2:
            tw = draw.textlength(text1 or "", font=font)
            draw.text((x+14+tw, start_y + i*line_h), text2, fill=colour2 or GRAY, font=font)

def draw_phone_mockup(draw, x, y, w, h):
    """Draw a minimal phone chat mockup."""
    round_rect(draw, (x, y, x+w, y+h), 18, DARK_CARD)
    # notch
    draw.rounded_rectangle([x+60, y+6, x+w-60, y+18], radius=6, fill=BG)
    # chat bubbles
    bubbles = [
        (x+16, y+32, x+w-40, y+60, PURPLE, "Hey Santana!", True),
        (x+40, y+72, x+w-16, y+100, (55, 65, 81), "I'm here. How can I help?", False),
        (x+16, y+112, x+w-50, y+140, PURPLE, "Search GitHub for AI repos", True),
        (x+40, y+152, x+w-16, y+190, (55, 65, 81), "Found 3 repos matching.\nCloning BadTechResearch/santana...", False),
    ]
    font = find_font(11)
    for bx, by, bx2, by2, col, txt, _ in bubbles:
        round_rect(draw, (bx, by, bx2, by2), 8, col)
        draw.text((bx+8, by+6), txt, fill=WHITE, font=font)

def main():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── gradient accent bar at top ───────────────
    for i in range(4):
        draw.rectangle([0, i, W, i+1], fill=(PURPLE[0]+i*8, PURPLE[1]-i*4, PURPLE[2]+i*12))

    # ── terminal on the left ─────────────────────
    draw_terminal_window(draw, 36, 100, 660, 360)

    # ── phone on the right ──────────────────────
    draw_phone_mockup(draw, 760, 120, 380, 340)

    # ── badge pills at bottom ────────────────────
    badges = [
        (36, 500, "$7/mo VM", GREEN),
        (180, 500, "No Docker ✓", CYAN),
        (330, 500, "AGPL-3.0", PURPLE),
        (460, 500, "DeepSeek V4 Flash", CYAN),
    ]
    font_badge = find_font(14, bold=True)
    for bx, by, text, colour in badges:
        tw = draw.textlength(text, font=font_badge)
        px, py = 10, 5
        bw, bh = tw + px*2, 24 + py
        round_rect(draw, (bx, by, bx+bw, by+bh), 14, colour)
        draw.text((bx+px, by+py), text, fill=BG, font=font_badge)

    # ── title top-left ──────────────────────────
    font_title = find_font(28, bold=True)
    draw.text((36, 36), "Santana", fill=WHITE, font=font_title)
    font_sub = find_font(16)
    draw.text((36, 70), "Autonomous AI Agent", fill=GRAY, font=font_sub)

    # ── watermark ────────────────────────────────
    font_water = find_font(11)
    draw.text((W-240, H-28), "github.com/BadTechResearch/santana", fill=GRAY, font=font_water)

    # ── save OG image ────────────────────────────
    og_path = "/home/hermes-openclaw/santana/docs/assets/og-image.png"
    img.save(og_path, "PNG")
    print(f"✅ OG image saved: {og_path} ({len(img.tobytes())} bytes)")

    # ── also generate a smaller screenshot.png ───
    scr = img.resize((800, 420), Image.LANCZOS)
    scr_path = "/home/hermes-openclaw/santana/docs/assets/screenshot.png"
    scr.save(scr_path, "PNG")
    print(f"✅ Screenshot saved: {scr_path} ({len(scr.tobytes())} bytes)")

    # verify
    for p in [og_path, scr_path]:
        with Image.open(p) as im:
            print(f"   {p}: {im.size} {im.mode}")

if __name__ == "__main__":
    main()
