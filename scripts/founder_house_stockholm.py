"""Claude Founder House Stockholm: scene set for the Nyan Gear LED backpack.

Seven scenes for the founder morning (14 Oct 2026), one per agenda moment,
plus evergreen hallway loops. The backpack plays a fellow attendee taking
notes and nudges people to talk about keeping agent session transcripts.
Storyboards: scripts/founder_house_stockholm/README.md

Usage:
  uv run scripts/founder_house_stockholm.py --list        # list scenes
  uv run scripts/founder_house_stockholm.py interview     # send one scene (name or number)
  uv run scripts/founder_house_stockholm.py --preview     # save preview GIFs of all scenes
"""

import asyncio
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bleak import BleakClient, BleakScanner
from PIL import Image

from display import (
    DEVICE_NAME_PREFIX,
    DISPLAY_SIZE,
    NOTIFY_UUID,
    PIXEL_FONT_5x7,
    READY,
    build_image_chunk,
    make_cmd,
    notification_handler,
    send_wait,
)

S = DISPLAY_SIZE  # 64
CHUNK_SIZE = 196
FINALIZE = make_cmd(0x000F, 0x3603, b"\x01\x00\x00")
PREVIEW_DIR = Path(__file__).parent / "founder_house_stockholm"
PREVIEW_SCALE = 4

# ── Extra glyphs (5x7) ───────────────────────────────────────────
FONT = {
    **PIXEL_FONT_5x7,
    "/": [0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000],
    "$": [0b00100, 0b01111, 0b10100, 0b01110, 0b00101, 0b11110, 0b00100],
    "~": [0b00000, 0b00000, 0b01000, 0b10101, 0b00010, 0b00000, 0b00000],
    "Å": [0b00100, 0b00000, 0b01110, 0b10001, 0b11111, 0b10001, 0b10001],
}

# ── Palette ──────────────────────────────────────────────────────
BG = (8, 8, 16)
TERM_BG = (10, 10, 14)
QUIZ_BG = (8, 8, 24)
HEADER_BG = (28, 30, 48)
WHITE = (235, 235, 235)
AMBER = (255, 176, 0)
GREEN = (80, 220, 120)
TERM_GREEN = (90, 200, 110)
RED = (230, 60, 60)
CYAN = (90, 200, 255)
GREY = (110, 110, 130)
SULPHUR = (211, 182, 79)
CLAUDE = (218, 119, 87)
DIM_CLAUDE = (110, 60, 44)
VERMILION = (230, 100, 70)
QUIZ_BLUE = (40, 70, 200)
SILVER = (150, 160, 180)
SE_BLUE = (0, 106, 167)
SE_YELLOW = (254, 204, 2)

# ── Sprites ──────────────────────────────────────────────────────
PENCIL = [
    ".....PP",
    "....YPP",
    "...YYY.",
    "..YYY..",
    ".YYY...",
    "WWY....",
    "T......",
]
PENCIL_COLORS = {"P": (230, 120, 150), "Y": AMBER, "W": (240, 210, 160), "T": GREY}

ARROW_UP = [
    "...G...",
    "..GGG..",
    ".GGGGG.",
    "GGGGGGG",
    "..GGG..",
    "..GGG..",
    "..GGG..",
]

PAGE = [
    "WWWWW..",
    "W...WW.",
    "W.GG.WW",
    "W.....W",
    "W.GGG.W",
    "W.....W",
    "W.GG..W",
    "W.....W",
    "WWWWWWW",
]
PAGE_COLORS = {"W": WHITE, "G": GREY}

SE_FLAG = [
    "BBBBYYBBBBBB",
    "BBBBYYBBBBBB",
    "BBBBYYBBBBBB",
    "YYYYYYYYYYYY",
    "BBBBYYBBBBBB",
    "BBBBYYBBBBBB",
    "BBBBYYBBBBBB",
]
SE_FLAG_COLORS = {"B": SE_BLUE, "Y": SE_YELLOW}

UFO = [
    "....CCC....",
    "...CWWWC...",
    ".GGGGGGGGG.",
    "GGGGGGGGGGG",
    ".L.L.L.L.L.",
]

MIC = [
    "..SSS..",
    ".SSSSS.",
    ".SWSWS.",
    ".SSSSS.",
    ".SWSWS.",
    ".SSSSS.",
    "..SSS..",
    "G.....G",
    ".G...G.",
    "..GGG..",
    "...G...",
    "...G...",
    "..GGG..",
    ".GGGGG.",
]
MIC_COLORS = {"S": SILVER, "W": WHITE, "G": GREY}

SPINNER_PLUS = ["...O...", "...O...", "...O...", "OOOOOOO", "...O...", "...O...", "...O..."]
SPINNER_X = ["O.....O", ".O...O.", "..O.O..", "...O...", "..O.O..", ".O...O.", "O.....O"]


# ── Drawing helpers ───────────────────────────────────────────────

def new(bg=BG):
    return Image.new("RGB", (S, S), bg)


def put(img, x, y, color):
    if 0 <= x < S and 0 <= y < S:
        img.putpixel((x, y), color)


def rect(img, x0, y0, x1, y1, color, fill=False):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if fill or y in (y0, y1) or x in (x0, x1):
                put(img, x, y, color)


def draw_glyph(img, ch, x, y, color, scale=1):
    glyph = FONT.get(ch)
    if glyph is None:
        raise ValueError(f"no glyph for {ch!r}")
    for row in range(7):
        for col in range(5):
            if glyph[row] & (1 << (4 - col)):
                for dy in range(scale):
                    for dx in range(scale):
                        put(img, x + col * scale + dx, y + row * scale + dy, color)


def text_width(text, scale=1):
    return len(text) * 5 * scale + max(0, len(text) - 1) * scale


def text(img, s, x, y, color, scale=1):
    """Draw text left-aligned at (x, y); x=None centers it. Fails loudly on overflow."""
    w = text_width(s, scale)
    if x is None:
        x = (S - w) // 2
    if x < 0 or x + w > S:
        raise ValueError(f"text {s!r} overflows 64px at x={x} (width {w})")
    for ch in s:
        if ch != " ":
            draw_glyph(img, ch, x, y, color, scale)
        x += 6 * scale
    return x  # x just past the last char + spacing


def draw_art(img, art, palette, x, y):
    """Draw pixel art with its top-left at (x, y)."""
    for r, row in enumerate(art):
        for c, ch in enumerate(row):
            color = palette.get(ch)
            if color:
                put(img, x + c, y + r, color)


def cursor(img, x, y, color=GREEN):
    rect(img, x, y, x + 4, y + 6, color, fill=True)


def bar_cursor(img, x, y, color=CLAUDE):
    for dy in range(7):
        put(img, x, y + dy, color)


def notes_header(img, label, frame):
    """'Notes' series header: bar, pencil with a blinking tip, amber label."""
    rect(img, 0, 0, S - 1, 8, HEADER_BG, fill=True)
    palette = dict(PENCIL_COLORS)
    if frame % 2:
        palette["T"] = WHITE
    draw_art(img, PENCIL, palette, 1, 1)
    text(img, label, 10, 1, AMBER)


def cta_card(header, tail, tail_color=CYAN):
    """Shared closing card: bobbing arrow, TALK TO / MY HUMAN., scene tail."""
    frames = []
    for f in range(2):
        img = new()
        if header:
            notes_header(img, header, f)
        draw_art(img, ARROW_UP, {"G": GREEN}, 28, 13 + f)
        text(img, "TALK TO", None, 26, WHITE)
        text(img, "MY HUMAN.", None, 36, AMBER)
        text(img, tail, None, 52, tail_color)
        frames.append(img)
    return [(frames[0], 1100), (frames[1], 1100)]


# ── Scene 0: FIKA QUIZ (arrival coffee, any lull) ────────────────

QUIZ_ANSWERS = ["A: GIT", "B: S3", "C: LAPTOP", "D: NO IDEA"]


def quiz_board(img, shown, lit=None):
    for i, ans in enumerate(QUIZ_ANSWERS[:shown]):
        y = 2 + 15 * i
        if i == lit:
            rect(img, 0, y, S - 1, y + 10, VERMILION, fill=True)
        else:
            rect(img, 0, y, S - 1, y + 10, QUIZ_BLUE)
        text(img, ans, 3, y + 2, WHITE)


def scene_quiz():
    out = []
    for f in range(2):
        img = new(QUIZ_BG)
        text(img, "FIKA QUIZ", None, 3, SULPHUR)
        for x in range(4, 60):
            put(img, x, 13, QUIZ_BLUE)
        text(img, "WHERE ARE", None, 18, WHITE)
        text(img, "YOUR AGENT", None, 28, WHITE)
        x0 = (S - text_width("SESSIONS?")) // 2
        text(img, "SESSIONS?" if f == 0 else "SESSIONS", x0, 38, WHITE)
        out.append((img, 800))
    for n in range(1, 5):
        img = new(QUIZ_BG)
        quiz_board(img, n)
        out.append((img, 1200 if n == 4 else 250))
    img = new(QUIZ_BG)
    text(img, "FINAL", None, 20, SULPHUR)
    text(img, "ANSWER?", None, 30, SULPHUR)
    out.append((img, 900))
    for lit, ms in [(3, 400), (None, 400), (3, 800)]:
        img = new(QUIZ_BG)
        quiz_board(img, 4, lit)
        out.append((img, ms))
    img = new(QUIZ_BG)
    text(img, "LIFELINE:", None, 12, SULPHUR)
    text(img, "FIKA WITH", None, 26, WHITE)
    text(img, "MY HUMAN.", None, 36, WHITE)
    out.append((img, 1400))
    for f in range(2):
        img = new(QUIZ_BG)
        if f == 0:
            draw_art(img, ARROW_UP, {"G": SULPHUR}, 28, 8)
        text(img, "TAP MY", None, 24, WHITE)
        text(img, "SHOULDER.", None, 34, WHITE)
        out.append((img, 500))
    return out


# ── Scene 1: where Claude goes next (keynote) ────────────────────

def scene_next():
    hdr = "#1 NEXT"
    out = []
    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "HEJ!", None, 12, CYAN, scale=2)
        text(img, "THIS BAG", None, 31, WHITE)
        text(img, "TAKES", None, 40, WHITE)
        end = text(img, "NOTES.", None, 49, WHITE)
        if f == 0:
            cursor(img, end, 49)
        out.append((img, 900))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "WHERE IS", None, 16, WHITE)
        text(img, "CLAUDE", None, 27, CLAUDE)
        end = text(img, "GOING?", None, 38, WHITE)
        if f == 0:
            cursor(img, end, 38)
        out.append((img, 700))

    img = new()
    notes_header(img, hdr, 0)
    text(img, "KARPATHY:", None, 11, AMBER)
    text(img, "~5000", None, 21, WHITE, scale=2)
    text(img, "HAVE THE", None, 40, WHITE)
    text(img, "FRONTIER.", None, 50, CLAUDE)
    out.append((img, 2200))

    # More power, at a higher cost: the cost bar outruns the power bar.
    power = [12, 22, 32, 40, 46]
    cost = [10, 24, 40, 56, 62]
    for f in range(5):
        img = new()
        notes_header(img, hdr, f)
        text(img, "NEXT:", 2, 11, AMBER)
        text(img, "YOU TOO.", 2, 20, WHITE)
        text(img, "POWER", 2, 32, GREEN)
        rect(img, 1, 41, 1 + power[f], 44, GREEN, fill=True)
        text(img, "COST", 2, 48, AMBER)
        rect(img, 1, 57, 1 + cost[f], 60, RED if f == 4 else AMBER, fill=True)
        out.append((img, 1400 if f == 4 else 300))

    # Paid-for tokens fall into /dev/null.
    for f, py in enumerate([28, 32, 36, 40, None]):
        img = new()
        notes_header(img, hdr, f)
        text(img, "PAYING FOR", None, 11, WHITE)
        text(img, "POWER?", None, 20, WHITE)
        rect(img, 20, 47, 43, 52, (90, 20, 20))
        rect(img, 21, 48, 42, 52, (0, 0, 0), fill=True)
        if py is not None:
            draw_art(img, PAGE, PAGE_COLORS, 29, py)
        else:
            for x, y in [(27, 44), (32, 42), (37, 45)]:
                put(img, x, y, GREY)
            text(img, "/dev/null", None, 56, RED)
        out.append((img, 1600 if py is None else 180))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "KEEP THE", None, 22, AMBER)
        text(img, "RECEIPTS.", None, 32, GREEN)
        out.append((img, 1000))

    out += cta_card(hdr, "HEJ HEJ!")
    return out


# ── Scene 2: grep 200k (How we use Claude inside Anthropic) ──────

def scene_grep():
    out = []
    cmd, arg = "$ grep -c", "transcript"
    typed = [(cmd[:3], ""), (cmd, ""), (cmd, arg)]
    for line1, line2 in typed:
        img = new(TERM_BG)
        end = text(img, line1, 1, 4, TERM_GREEN)
        if line2:
            end = text(img, line2, 1, 13, WHITE)
            bar_cursor(img, min(end, S - 1), 22)
        else:
            bar_cursor(img, end, 4)
        out.append((img, 180))

    ticks = ["000042", "001337", "008192", "031415", "065536", "131072", "199999", "200000"]
    for i, t in enumerate(ticks):
        img = new(TERM_BG)
        text(img, cmd, 1, 4, TERM_GREEN)
        text(img, arg, 1, 13, WHITE)
        text(img, t, None, 28, SULPHUR)
        for x in range(2, 2 + int(59 * (i + 1) / len(ticks))):
            put(img, x, 38, DIM_CLAUDE)
        out.append((img, 900 if i == len(ticks) - 1 else 180))

    img = new(TERM_BG)
    text(img, "ANTHROPIC", None, 4, GREY)
    text(img, "200K", None, 14, CLAUDE, scale=2)
    text(img, "OF ITS OWN", None, 34, WHITE)
    text(img, "SESSIONS,", None, 43, WHITE)
    text(img, "ANALYZED.", None, 52, GREY)
    out.append((img, 1800))

    img = new(TERM_BG)
    text(img, "ITS EVALS", None, 4, GREY)
    text(img, "GUIDE:", None, 12, GREY)
    text(img, "READ THE", None, 26, WHITE)
    w = text_width("READ THE")
    for x in range((S - w) // 2, (S + w) // 2):
        put(img, x, 34, CLAUDE)
    text(img, "TRAN-", None, 37, CLAUDE)
    text(img, "SCRIPTS!", None, 46, CLAUDE)
    out.append((img, 2000))

    for f in range(2):
        img = new(TERM_BG)
        text(img, cmd, 1, 4, TERM_GREEN)
        end = text(img, "yours", 1, 13, WHITE)
        if f == 0:
            bar_cursor(img, end, 13)
        text(img, "0?", None, 26, VERMILION, scale=2)
        text(img, "ASK ME.", None, 48, WHITE)
        out.append((img, 900))
    return out


# ── Scene 3: 339 is not lagom (founder panels) ───────────────────

def scene_lagom():
    hdr = "#3 LAGOM"
    out = []
    counts = [1, 42, 117, 230, 301, 339]
    for f, n in enumerate(counts):
        img = new()
        notes_header(img, hdr, f)
        text(img, "AGENT LOG:", 2, 11, AMBER)
        shift = 4 if f % 2 else 0  # half-line scroll so the log visibly moves
        for k in range(5):
            y = 21 + 8 * k - shift
            if 21 <= y <= 45:
                text(img, "$ SAME CMD", 2, y, WHITE if y >= 41 else GREY)
        text(img, "RUN", 2, 55, GREY)
        label = f"#{n}"
        text(img, label, S - 2 - text_width(label), 55, AMBER)
        out.append((img, 940 if f == len(counts) - 1 else 180))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "TASK:", 2, 13, WHITE)
        text(img, "PASSED.", 2, 23, GREEN)
        text(img, "COST:", 2, 37, WHITE)
        text(img, "ABOUT 9X.", 2, 47, AMBER)
        out.append((img, 1000))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "339 IS", None, 16, WHITE)
        x = text(img, "NOT ", 2, 26, WHITE)
        text(img, "LAGOM.", x, 26, CYAN)
        draw_art(img, SE_FLAG, SE_FLAG_COLORS, 26, 40 + f)
        out.append((img, 900))

    out += cta_card(hdr, "NO LOOPS.", GREY)
    return out


# ── Scene 4: the truth is in the transcript (office hours) ───────

def scene_repro():
    hdr = "#4 FRÅGOR"
    out = []

    def bubble1(img, color, dots=False):
        rect(img, 0, 10, 62, 30, color)
        for x, y in [(4, 31), (5, 31), (4, 32)]:
            put(img, x, y, color)
        if dots:
            for x in (25, 31, 37):
                put(img, x, 20, color)
        else:
            text(img, "STEPS TO", 2, 13, WHITE)
            text(img, "REPRODUCE?", 2, 22, WHITE)

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        bubble1(img, CYAN, dots=True)
        out.append((img, 300))
    img = new()
    notes_header(img, hdr, 0)
    bubble1(img, CYAN)
    out.append((img, 1500))

    img = new()
    notes_header(img, hdr, 1)
    bubble1(img, GREY)
    rect(img, 5, 34, 63, 63, WHITE)
    for x in (27, 33, 39):
        put(img, x, 48, WHITE)
    out.append((img, 300))
    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        bubble1(img, GREY)
        rect(img, 5, 34, 63, 63, WHITE)
        text(img, "IT WORKED", 8, 37, WHITE)
        text(img, "ON MY", 8, 45, WHITE)
        text(img, "AGENT.", 8, 53, AMBER)
        out.append((img, 1050))

    # X-Files nod: the truth is out there, in the transcript.
    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "THE TRUTH", None, 13, WHITE)
        text(img, "IS IN THE", None, 23, WHITE)
        text(img, "TRANSCRIPT", None, 33, GREEN)
        lights = {"C": CYAN, "W": WHITE, "G": GREY, "L": AMBER if f == 0 else SULPHUR}
        draw_art(img, UFO, lights, 26 + f, 47)
        if f == 0:
            for y in range(52, 64):
                half = (y - 52) // 3
                for x in range(31 - half, 32 + half + (1 if f else 0)):
                    put(img, x, y, (40, 70, 50))
        out.append((img, 1100))

    out += cta_card(hdr, "HE GREPS.")
    return out


# ── Scene 5: fika 1:1, proceed? (networking) ─────────────────────

OPTIONS = ["1. YES", "2. ALWAYS", "3. NO"]


def prompt_box(img, border="full"):
    if border == "half":
        for x in range(S):
            put(img, x, 0, CLAUDE)
        for y in range(S):
            put(img, 0, y, CLAUDE)
    else:
        rect(img, 0, 0, S - 1, S - 1, CLAUDE)
    text(img, "FIKA 1:1", 3, 5, SULPHUR)
    text(img, "PROCEED?", 3, 14, WHITE)


def triangle(img, x, y, color):
    for c, h in enumerate([5, 3, 1]):
        for dy in range(h):
            put(img, x + c, y + (5 - h) // 2 + dy, color)


def prompt_options(img, sel, sel_color=None, flash=False):
    for i, opt in enumerate(OPTIONS):
        y = 27 + 9 * i
        if flash and i == sel:
            rect(img, 1, y - 1, S - 2, y + 7, WHITE, fill=True)
            text(img, opt, 8, y, TERM_BG)
            continue
        text(img, opt, 8, y, sel_color if (i == sel and sel_color) else GREY)
    triangle(img, 3, 27 + 9 * sel + 1, CLAUDE)


def scene_proceed():
    out = []
    img = new(TERM_BG)
    text(img, "CURATED", 2, 10, WHITE)
    text(img, "ROOM.", 2, 19, WHITE)
    text(img, "TIME TO", 2, 33, SULPHUR)
    text(img, "WORK IT:", 2, 42, SULPHUR)
    out.append((img, 1300))

    for border in ("half", "full"):
        img = new(TERM_BG)
        prompt_box(img, border)
        prompt_options(img, 0)
        out.append((img, 500))
    for sel_color, flash in [(None, False), (CLAUDE, False), (None, True)]:
        img = new(TERM_BG)
        prompt_box(img)
        prompt_options(img, 1, sel_color, flash)
        out.append((img, 280))

    img = new(TERM_BG)
    rect(img, 0, 0, S - 1, S - 1, TERM_GREEN)
    text(img, "1:1", None, 20, TERM_GREEN, scale=2)
    text(img, "APPROVED", None, 44, (60, 140, 75))
    out.append((img, 700))

    for spin in (SPINNER_PLUS, SPINNER_X):
        img = new(TERM_BG)
        draw_art(img, spin, {"O": CLAUDE}, 1, 28)
        text(img, "FIKAING..", 10, 28, SULPHUR)
        out.append((img, 300))

    for f in range(2):
        img = new(TERM_BG)
        text(img, "TACK SÅ", None, 8, SULPHUR)
        text(img, "MYCKET!", None, 18, SULPHUR)
        text(img, "TAP MY", None, 36, WHITE)
        text(img, "SHOULDER.", None, 46, WHITE)
        if f:
            draw_art(img, ARROW_UP, {"G": GREEN}, 53, 34)
        out.append((img, 900))
    return out


# ── Scene 6: MINGEL interview with my human (evergreen) ─────────

def scene_interview():
    hdr = "#5 MINGEL"
    out = []
    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "INTERVIEW", None, 12, AMBER)
        text(img, "WITH MY", None, 22, WHITE)
        text(img, "HUMAN.", None, 31, WHITE)
        draw_art(img, MIC, MIC_COLORS, 28, 43 + f)
        out.append((img, 900))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "Q: BEFORE?", 2, 11, AMBER)
        text(img, "10 YEARS", 2, 23, WHITE)
        text(img, "GREPPING", 2, 32, WHITE)
        text(img, "LOGS TILL", 2, 41, WHITE)
        text(img, "NASDAQ IPO", 2, 50, WHITE)
        out.append((img, 1400))

    for f in range(6):
        img = new()
        notes_header(img, hdr, f)
        text(img, "Q: NOW?", 2, 11, AMBER)
        text(img, "MINING", 2, 24, WHITE)
        x = 2
        for i, ch in enumerate("SILVER"):
            draw_glyph(img, ch, x, 33, (255, 255, 255) if i == f else SILVER)
            x += 6
        text(img, " OUT", x, 33, WHITE)
        text(img, "OF AGENT", 2, 42, WHITE)
        text(img, "SESSIONS.", 2, 51, WHITE)
        out.append((img, 450))

    for f in range(2):
        img = new()
        notes_header(img, hdr, f)
        text(img, "Q: CAN I", 2, 11, AMBER)
        text(img, "ASK HIM?", 2, 20, AMBER)
        x = text(img, "JA!", 2, 34, CYAN)
        text(img, " TAP", x, 34, WHITE)
        text(img, "HIS", 2, 43, WHITE)
        text(img, "SHOULDER.", 2, 52, WHITE)
        draw_art(img, ARROW_UP, {"G": GREEN}, 55, 34 + f)
        out.append((img, 1400))
    return out


# ── Scene registry ────────────────────────────────────────────────

SCENES = [
    ("fika-quiz", "arrival coffee, any lull", scene_quiz),
    ("next", "keynote: Anthropic on where Claude goes next", scene_next),
    ("grep", "How we use Claude inside Anthropic (upload after it starts)", scene_grep),
    ("lagom", "founder panels", scene_lagom),
    ("truth", "office hours with Applied AI", scene_repro),
    ("proceed", "networking", scene_proceed),
    ("interview", "evergreen: walking, between slots, after 13:00", scene_interview),
]


def make_animated_gif(frames, durations, scale=1):
    quantized = [f.convert("RGB").quantize(colors=32).convert("RGB") for f in frames]
    if scale > 1:
        quantized = [f.resize((S * scale, S * scale), Image.NEAREST) for f in quantized]
    buf = BytesIO()
    quantized[0].save(
        buf, format="GIF", save_all=True,
        append_images=quantized[1:], duration=durations, loop=0,
    )
    return buf.getvalue()


def render(fn):
    beats = fn()
    frames = [img for img, _ in beats]
    durations = [ms for _, ms in beats]
    return frames, durations


def pick_scene(arg):
    for i, (name, when, fn) in enumerate(SCENES):
        if arg in (name, str(i)):
            return i, name, fn
    names = ", ".join(f"{i}:{n}" for i, (n, _, _) in enumerate(SCENES))
    sys.exit(f"Unknown scene {arg!r}. Choose one of: {names}")


async def send(gif_data, num_chunks, label):
    print("Scanning for backpack...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: (adv.local_name or "").startswith(DEVICE_NAME_PREFIX),
        timeout=10,
    )
    if not device:
        sys.exit("Backpack not found!")
    print(f"Found: {device.name}")

    async with BleakClient(device) as client:
        await client.start_notify(NOTIFY_UUID, notification_handler)
        await send_wait(client, READY)
        errors = 0
        for idx in range(num_chunks):
            chunk = gif_data[idx * CHUNK_SIZE : (idx + 1) * CHUNK_SIZE]
            status = await send_wait(client, build_image_chunk(idx, chunk, num_chunks))
            if status != 0:
                errors += 1
                print(f"  chunk {idx}/{num_chunks} -> ERR status={status}")
            await asyncio.sleep(0.3)
        await send_wait(client, FINALIZE)
        await client.stop_notify(NOTIFY_UUID)

    if errors:
        sys.exit(f"FAILED: {errors}/{num_chunks} chunks errored; {label} may not display.")
    print(f"Done! {label} is on display.")


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--list" in sys.argv:
        for i, (name, when, _) in enumerate(SCENES):
            print(f"{i}  {name:<10} {when}")
        return

    if "--preview" in sys.argv:
        PREVIEW_DIR.mkdir(exist_ok=True)
        for i, (name, _, fn) in enumerate(SCENES):
            frames, durations = render(fn)
            gif = make_animated_gif(frames, durations)
            chunks = (len(gif) + CHUNK_SIZE - 1) // CHUNK_SIZE
            out = PREVIEW_DIR / f"{i}_{name}.gif"
            out.write_bytes(make_animated_gif(frames, durations, scale=PREVIEW_SCALE))
            print(f"{i} {name}: {len(frames)} frames, {sum(durations) / 1000:.1f}s loop, "
                  f"{len(gif)} bytes, {chunks} chunks -> {out.name}")
        return

    if len(args) != 1:
        sys.exit("Pass one scene name or number (see --list), or --preview.")
    i, name, fn = pick_scene(args[0])
    frames, durations = render(fn)
    gif = make_animated_gif(frames, durations)
    chunks = (len(gif) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"Scene {i} {name}: {len(frames)} frames, {len(gif)} bytes, {chunks} chunks")
    if chunks > 255:
        sys.exit(f"ERROR: {chunks} chunks exceeds protocol limit.")
    await send(gif, chunks, name)


asyncio.run(main())
