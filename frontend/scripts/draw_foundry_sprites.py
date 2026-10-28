"""Draw the whole Foundry cast as pixel art: every agent in `agent_personas.json`
gets a face that fits who they are, standing (idle) and seated at the desk
(working), each holding what says their job (Bob a database, Todd gears, Sam a
shield…). The sprite key is the persona's first name.

    python3 frontend/scripts/draw_foundry_sprites.py frontend/public/sprites/characters

Add a person to `CAST` (hair, skin, top, extras, what they hold) and to the
manifest; `frontend/src/__tests__/the-foundry-names-its-agents.test.tsx`
checks every desk has its own face in both poses.
"""
import sys
from pathlib import Path

from PIL import Image

OUT = Path(sys.argv[1])
SCALE = 5
OUTLINE = (38, 32, 44, 255)
SKIN = (246, 196, 152, 255)
SKIN_SH = (222, 160, 118, 255)
EYE = (32, 28, 40, 255)
MOUTH = (196, 104, 92, 255)
PANTS = (44, 52, 86, 255)
PANTS_SH = (32, 38, 66, 255)
SHOE = (78, 52, 40, 255)
WOOD = (214, 160, 92, 255)
WOOD_SH = (168, 116, 60, 255)
WOOD_DK = (120, 80, 42, 255)
SCREEN = (34, 40, 66, 255)
SCREEN_HI = (70, 84, 128, 255)
CHAIR = (52, 58, 82, 255)
CHAIR_SH = (36, 40, 60, 255)
KEYS = (60, 64, 80, 255)


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c[:3]) + (255,)


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[None] * w for _ in range(h)]
        self.no_outline = set()

    def set(self, x, y, c, outline=True):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c
            if not outline:
                self.no_outline.add((x, y))

    def rect(self, x0, y0, x1, y1, c, sh=None, hi=None, outline=True):
        """Filled, inclusive; the right column(s) shaded, the top row lit."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                col = c
                if sh and x >= x1 - (1 if x1 - x0 > 5 else 0):
                    col = sh
                if hi and y == y0 and x0 < x < x1:
                    col = hi
                self.set(x, y, col, outline)

    def ellipse_shadow(self, cx, cy, rx, ry, alpha=60):
        for y in range(cy - ry, cy + ry + 1):
            for x in range(cx - rx, cx + rx + 1):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1 and self.px[y][x] is None:
                    self.px[y][x] = (90, 90, 110, alpha)
                    self.no_outline.add((x, y))

    def outline(self):
        add = []
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x] is not None:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.w and 0 <= ny < self.h and self.px[ny][nx] is not None \
                            and (nx, ny) not in self.no_outline and self.px[ny][nx][3] == 255:
                        add.append((x, y))
                        break
        for x, y in add:
            self.px[y][x] = OUTLINE

    def image(self):
        im = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x] is not None:
                    im.putpixel((x, y), self.px[y][x])
        return im.resize((self.w * SCALE, self.h * SCALE), Image.NEAREST)


# --------------------------------------------------------------------------- #
# The head: shared by both poses, placed at (hx, hy) — 16 wide, 15 tall.
# --------------------------------------------------------------------------- #

def head(cv, hx, hy, p, facing="front"):
    skin, skin_sh = p.get("skin", (SKIN, SKIN_SH))
    # face
    cv.rect(hx + 1, hy + 5, hx + 14, hy + 14, skin, sh=skin_sh)
    cv.rect(hx + 2, hy + 15, hx + 13, hy + 15, skin_sh)
    # ears
    cv.rect(hx, hy + 8, hx, hy + 10, skin)
    cv.rect(hx + 15, hy + 8, hx + 15, hy + 10, skin_sh)
    # eyes and mouth
    ex = (hx + 4, hx + 10) if facing == "front" else (hx + 3, hx + 8)
    for x in ex:
        if p.get("glasses"):
            # Light lenses in a thin frame, small eyes behind them.
            cv.rect(x - 1, hy + 8, x + 2, hy + 12, (214, 232, 246, 255), outline=False)
            cv.rect(x, hy + 9, x, hy + 11, EYE)
        else:
            cv.rect(x, hy + 9, x + 1, hy + 11, EYE)
            cv.set(x, hy + 9, (255, 255, 255, 255))
    mx = hx + 7 if facing == "front" else hx + 5
    cv.rect(mx, hy + 13, mx + 1, hy + 13, MOUTH)
    # cheeks
    cv.set(ex[0] - 1, hy + 12, (240, 160, 150, 255))
    cv.set(ex[1] + 2, hy + 12, (240, 160, 150, 255))
    p["hair"](cv, hx, hy, facing)
    if p.get("beard"):
        b, bsh = p["beard"], shade(p["beard"], 0.78)
        cv.rect(hx + 1, hy + 12, hx + 1, hy + 14, b)
        cv.rect(hx + 14, hy + 12, hx + 14, hy + 14, bsh)
        cv.rect(hx + 2, hy + 14, hx + 13, hy + 15, b, sh=bsh)
        mx = hx + 7 if facing == "front" else hx + 5
        cv.rect(mx - 1, hy + 13, mx + 2, hy + 13, b)                # moustache, mouth beneath
        cv.rect(mx, hy + 14, mx + 1, hy + 14, MOUTH)
    if p.get("headphones"):
        band = p["headphones"]
        cv.rect(hx + 1, hy - 1, hx + 14, hy - 1, band)
        cv.rect(hx - 1, hy, hx - 1, hy + 6, band)
        cv.rect(hx + 16, hy, hx + 16, hy + 6, band)
        cv.rect(hx - 2, hy + 7, hx, hy + 11, shade(band, 0.7))
        cv.rect(hx + 15, hy + 7, hx + 17, hy + 11, shade(band, 0.7))
    if p.get("glasses"):
        frame = (70, 60, 80, 255)
        for x in ex:
            cv.rect(x - 2, hy + 8, x + 3, hy + 8, frame)
            cv.rect(x - 2, hy + 12, x + 3, hy + 12, frame)
            cv.rect(x - 2, hy + 9, x - 2, hy + 11, frame)
            cv.rect(x + 3, hy + 9, x + 3, hy + 11, frame)
        cv.rect(ex[0] + 4, hy + 9, ex[1] - 3, hy + 9, frame)
    # ROUNDED: the corners of the head are taken off, as the cast's are.
    for x, y in ((hx + 1, hy + 14), (hx + 14, hy + 14), (hx + 2, hy + 15), (hx + 13, hy + 15)):
        cv.px[y][x] = None
    for x, y in ((hx + 1, hy + 1), (hx + 14, hy + 1), (hx + 1, hy), (hx + 14, hy), (hx + 2, hy), (hx + 13, hy)):
        if 0 <= y < cv.h and cv.px[y][x] is not None and facing == "front":
            cv.px[y][x] = None


# --------------------------------------------------------------------------- #
# Hair and hats
# --------------------------------------------------------------------------- #

def hair_ponytail(color):
    hi, sh = shade(color, 1.35), shade(color, 0.75)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 1, hx + 14, hy + 6, color, sh=sh, hi=hi)
        cv.rect(hx + 3, hy, hx + 12, hy, color)
        cv.rect(hx, hy + 3, hx, hy + 9, color)              # side locks
        cv.rect(hx + 15, hy + 3, hx + 15, hy + 9, sh)
        cv.rect(hx + 2, hy + 7, hx + 4, hy + 7, color)      # fringe
        cv.rect(hx + 9, hy + 7, hx + 12, hy + 7, color)
        # the ponytail, out to the side
        cv.rect(hx + 16, hy + 4, hx + 18, hy + 6, color, sh=sh)
        cv.rect(hx + 17, hy + 7, hx + 19, hy + 12, color, sh=sh)
        cv.rect(hx + 18, hy + 13, hx + 19, hy + 14, sh)
        cv.set(hx + 16, hy + 5, (236, 72, 153, 255))          # a hair tie
    return draw


def hair_neat(color):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 1, hx + 14, hy + 5, color, sh=sh, hi=hi)
        cv.rect(hx + 3, hy, hx + 12, hy, color)
        cv.rect(hx, hy + 3, hx, hy + 8, color)
        cv.rect(hx + 15, hy + 3, hx + 15, hy + 8, sh)
        cv.rect(hx + 1, hy + 6, hx + 6, hy + 6, color)       # side parting
        cv.set(hx + 7, hy + 3, hi); cv.set(hx + 8, hy + 2, hi)
    return draw


def cap(color, badge):
    hi, sh = shade(color, 1.3), shade(color, 0.7)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy, hx + 14, hy + 5, color, sh=sh, hi=hi)
        cv.rect(hx + 3, hy - 1, hx + 12, hy - 1, color)
        if facing == "front":
            cv.rect(hx - 1, hy + 6, hx + 16, hy + 7, sh)          # brim
        else:
            cv.rect(hx - 3, hy + 6, hx + 8, hy + 7, sh)
        cv.rect(hx + 1, hy + 6, hx + 3, hy + 8, (90, 60, 40, 255))  # hair under the cap
        cv.rect(hx + 12, hy + 6, hx + 14, hy + 8, (90, 60, 40, 255))
        bx = hx + 7 if facing == "front" else hx + 5
        cv.rect(bx, hy + 2, bx + 1, hy + 3, badge)
    return draw


def beret(color, hair_color):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 3, hx + 14, hy + 6, hair_color, sh=shade(hair_color, 0.75))   # hair
        cv.rect(hx, hy + 4, hx, hy + 9, hair_color)
        cv.rect(hx + 15, hy + 4, hx + 15, hy + 9, shade(hair_color, 0.75))
        cv.rect(hx - 1, hy + 1, hx + 13, hy + 3, color, sh=sh, hi=hi)      # beret, tilted
        cv.rect(hx + 1, hy, hx + 11, hy, color)
        cv.set(hx + 6, hy - 1, sh)                                         # the stalk
    return draw


# --------------------------------------------------------------------------- #
# Standing (idle): 26 x 40
# --------------------------------------------------------------------------- #

def idle(p):
    cv = Canvas(28, 41)
    cv.ellipse_shadow(13, 39, 9, 1)
    body, body_sh = p["top"], shade(p["top"], 0.75)
    # legs and shoes
    cv.rect(8, 31, 12, 36, PANTS, sh=PANTS_SH)
    cv.rect(14, 31, 18, 36, PANTS, sh=PANTS_SH)
    cv.rect(7, 37, 12, 38, SHOE)
    cv.rect(14, 37, 19, 38, SHOE)
    # torso
    cv.rect(7, 19, 19, 31, body, sh=body_sh, hi=shade(body, 1.2))
    if p.get("coat"):
        coat = p["coat"]
        cv.rect(7, 19, 9, 32, coat, sh=shade(coat, 0.85))
        cv.rect(17, 19, 19, 32, coat, sh=shade(coat, 0.8))
    if p.get("vest"):
        cv.rect(9, 20, 17, 30, p["vest"], sh=shade(p["vest"], 0.75))
        cv.rect(12, 20, 14, 23, (240, 240, 245, 255))            # collar
    if p.get("scarf"):
        cv.rect(8, 18, 18, 20, p["scarf"], sh=shade(p["scarf"], 0.75))
        cv.rect(15, 21, 16, 25, p["scarf"], sh=shade(p["scarf"], 0.75))
    if p.get("overalls"):
        o = p["overalls"]
        cv.rect(9, 23, 17, 32, o, sh=shade(o, 0.78))
        cv.rect(9, 19, 10, 22, o); cv.rect(16, 19, 17, 22, shade(o, 0.78))     # straps
        cv.set(10, 24, (250, 204, 21, 255)); cv.set(16, 24, (250, 204, 21, 255))
    if p.get("apron"):
        a = p["apron"]
        cv.rect(9, 21, 17, 34, a, sh=shade(a, 0.78), hi=shade(a, 1.15))
        cv.rect(11, 26, 15, 26, shade(a, 0.7))                                   # pocket seam
    if p.get("tie"):
        cv.rect(12, 19, 14, 19, (240, 240, 245, 255))
        cv.rect(13, 20, 13, 27, p["tie"]); cv.rect(12, 21, 14, 23, p["tie"])
    if p.get("hoodie"):
        h = p["hoodie"]
        cv.rect(8, 18, 18, 19, shade(h, 0.8))                                    # hood at the neck
        cv.rect(10, 26, 16, 29, shade(h, 0.85))                                  # pouch
        cv.set(11, 20, (240, 240, 245, 255)); cv.set(15, 20, (240, 240, 245, 255))
    if p.get("badge"):
        cv.rect(15, 21, 17, 23, p["badge"], sh=shade(p["badge"], 0.7))
    # arms and hands
    cv.rect(4, 20, 6, 28, body, sh=body_sh)
    cv.rect(20, 20, 22, 27, body_sh)
    cv.rect(4, 29, 6, 30, p.get("skin", (SKIN, SKIN_SH))[0])
    cv.rect(20, 28, 22, 29, p.get("skin", (SKIN, SKIN_SH))[0])
    p["holds"](cv, "idle")
    head(cv, 5, 3, p)
    cv.outline()
    return cv.image()


# --------------------------------------------------------------------------- #
# Seated at the desk (working): 37 x 35
# --------------------------------------------------------------------------- #

def working(p):
    cv = Canvas(38, 36)
    cv.ellipse_shadow(18, 33, 16, 2)
    body, body_sh = p["top"], shade(p["top"], 0.75)
    # chair back, behind the person
    cv.rect(29, 11, 33, 26, CHAIR, sh=CHAIR_SH, hi=shade(CHAIR, 1.25))
    cv.rect(30, 27, 31, 31, CHAIR_SH)
    cv.rect(27, 31, 34, 32, CHAIR_SH)
    # torso and arms reaching for the keyboard
    cv.rect(18, 15, 28, 24, body, sh=body_sh, hi=shade(body, 1.2))
    if p.get("coat"):
        cv.rect(25, 15, 28, 24, p["coat"], sh=shade(p["coat"], 0.8))
    if p.get("vest"):
        cv.rect(20, 16, 26, 24, p["vest"], sh=shade(p["vest"], 0.75))
    if p.get("scarf"):
        cv.rect(19, 15, 27, 16, p["scarf"], sh=shade(p["scarf"], 0.75))
    if p.get("overalls"):
        cv.rect(21, 18, 26, 24, p["overalls"], sh=shade(p["overalls"], 0.78))
    if p.get("apron"):
        cv.rect(20, 17, 27, 24, p["apron"], sh=shade(p["apron"], 0.78))
    if p.get("tie"):
        cv.rect(23, 16, 23, 22, p["tie"])
    if p.get("badge"):
        cv.rect(25, 17, 26, 18, p["badge"])
    cv.rect(14, 19, 19, 21, body, sh=body_sh)
    cv.rect(12, 20, 14, 21, p.get("skin", (SKIN, SKIN_SH))[0])
    head(cv, 16, 1, p, facing="side")
    # the desk: top, front edge, legs
    cv.rect(1, 22, 30, 24, WOOD, hi=shade(WOOD, 1.12))
    cv.rect(1, 25, 30, 26, WOOD_SH)
    cv.rect(2, 27, 4, 33, WOOD_DK)
    cv.rect(26, 27, 28, 33, WOOD_DK)
    # keyboard
    cv.rect(10, 21, 17, 21, KEYS, outline=False)
    # the monitor, facing the person
    cv.rect(3, 6, 12, 17, SCREEN, hi=SCREEN_HI)
    cv.rect(4, 7, 11, 15, (46, 58, 98, 255))
    for y in (9, 11, 13):                                       # lines on the screen
        cv.rect(5, y, 9, y, p.get("screen", (96, 165, 250, 255)), outline=False)
    cv.rect(7, 18, 8, 21, SCREEN)
    cv.rect(5, 21, 10, 21, SCREEN)
    p["holds"](cv, "working")
    cv.outline()
    return cv.image()


# --------------------------------------------------------------------------- #
# What each one holds
# --------------------------------------------------------------------------- #

def phone(cv, pose):
    if pose == "idle":
        cv.rect(21, 23, 24, 29, (30, 30, 40, 255))
        cv.rect(22, 24, 23, 27, (94, 234, 212, 255))
    else:
        cv.rect(19, 23, 21, 23, (30, 30, 40, 255))              # a phone on the desk
        cv.rect(19, 22, 21, 22, (94, 234, 212, 255))


def magnifier(cv, pose):
    if pose == "idle":
        rim = (180, 140, 60, 255)
        cv.rect(21, 20, 25, 20, rim); cv.rect(21, 24, 25, 24, rim)
        cv.rect(20, 21, 20, 23, rim); cv.rect(26, 21, 26, 23, rim)
        cv.rect(21, 21, 25, 23, (190, 225, 245, 255))
        cv.set(22, 21, (255, 255, 255, 255))
        cv.rect(22, 25, 22, 28, (110, 70, 40, 255))
    else:
        cv.rect(22, 21, 25, 21, (250, 250, 245, 255))           # a page under review
        cv.rect(22, 21, 25, 21, (250, 250, 245, 255))


def checklist(cv, pose):
    if pose == "idle":
        cv.rect(20, 21, 25, 29, (196, 150, 96, 255))             # clipboard
        cv.rect(21, 22, 24, 28, (250, 250, 245, 255))
        for y in (23, 25, 27):
            cv.set(21, y, (34, 197, 94, 255))                     # ticks
            cv.rect(22, y, 24, y, (150, 150, 160, 255))
        cv.rect(22, 20, 23, 20, (120, 120, 130, 255))
    else:
        cv.rect(23, 21, 26, 21, (250, 250, 245, 255))
        cv.set(23, 21, (34, 197, 94, 255))


def book(cv, pose):
    if pose == "idle":
        cv.rect(19, 23, 25, 29, (185, 28, 28, 255), sh=(140, 20, 20, 255))
        cv.rect(20, 24, 24, 24, (250, 204, 21, 255))             # gilt on the cover
        cv.rect(19, 29, 25, 29, (250, 250, 245, 255))             # pages
    else:
        cv.rect(21, 21, 26, 21, (185, 28, 28, 255))               # an open book on the desk
        cv.rect(22, 20, 25, 20, (250, 250, 245, 255))


def hair_long(color, band=None):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 1, hx + 14, hy + 6, color, sh=sh, hi=hi)
        cv.rect(hx + 3, hy, hx + 12, hy, color)
        cv.rect(hx - 1, hy + 3, hx, hy + 17, color)            # falls past the shoulders
        cv.rect(hx + 15, hy + 3, hx + 16, hy + 17, sh)
        cv.rect(hx + 1, hy + 7, hx + 5, hy + 7, color)           # fringe
        cv.rect(hx + 10, hy + 7, hx + 14, hy + 7, color)
        if band:
            cv.rect(hx + 1, hy + 3, hx + 14, hy + 3, band)
    return draw


def hair_bun(color):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        hair_neat(color)(cv, hx, hy, facing)
        bx = hx + 6 if facing == "front" else hx + 9
        cv.rect(bx, hy - 3, bx + 3, hy - 1, color, sh=sh, hi=hi)
    return draw


def hair_curly(color):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx - 1, hy + 1, hx + 16, hy + 6, color, sh=sh, hi=hi)
        cv.rect(hx - 1, hy + 7, hx, hy + 11, color)
        cv.rect(hx + 15, hy + 7, hx + 16, hy + 11, sh)
        for x in range(hx, hx + 16, 3):                          # curls along the top
            cv.rect(x, hy - 1, x + 1, hy, color)
        cv.rect(hx + 2, hy + 7, hx + 4, hy + 7, color); cv.rect(hx + 11, hy + 7, hx + 13, hy + 7, color)
    return draw


def hair_spiky(color):
    hi, sh = shade(color, 1.3), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 2, hx + 14, hy + 6, color, sh=sh, hi=hi)
        cv.rect(hx, hy + 4, hx, hy + 8, color); cv.rect(hx + 15, hy + 4, hx + 15, hy + 8, sh)
        for i, x in enumerate(range(hx + 1, hx + 15, 3)):        # spikes
            cv.rect(x, hy - 1 + (i % 2), x + 1, hy + 1, color)
        cv.rect(hx + 3, hy + 7, hx + 5, hy + 7, color); cv.rect(hx + 9, hy + 7, hx + 10, hy + 7, color)
    return draw


def hair_buzz(color):
    def draw(cv, hx, hy, facing):
        cv.rect(hx + 2, hy + 2, hx + 13, hy + 5, color, sh=shade(color, 0.78))
        cv.rect(hx + 1, hy + 4, hx + 1, hy + 7, color); cv.rect(hx + 14, hy + 4, hx + 14, hy + 7, shade(color, 0.78))
    return draw


def beanie(color, hair_color):
    hi, sh = shade(color, 1.25), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx, hy + 5, hx + 1, hy + 9, hair_color); cv.rect(hx + 14, hy + 5, hx + 15, hy + 9, shade(hair_color, 0.75))
        cv.rect(hx + 1, hy, hx + 14, hy + 4, color, sh=sh, hi=hi)
        cv.rect(hx, hy + 5, hx + 15, hy + 6, shade(color, 1.15))     # the turned-up band
        cv.rect(hx + 3, hy - 1, hx + 12, hy - 1, color)
        cv.rect(hx + 7, hy - 3, hx + 8, hy - 2, (245, 245, 245, 255))  # the bobble
    return draw


def hard_hat(color, hair_color):
    hi, sh = shade(color, 1.25), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx + 1, hy + 6, hx + 2, hy + 8, hair_color); cv.rect(hx + 13, hy + 6, hx + 14, hy + 8, hair_color)
        cv.rect(hx + 1, hy, hx + 14, hy + 4, color, sh=sh, hi=hi)
        cv.rect(hx + 3, hy - 1, hx + 12, hy - 1, color)
        cv.rect(hx - 1, hy + 5, hx + 16, hy + 5, sh)                   # the rim
        cv.rect(hx + 7, hy - 1, hx + 8, hy + 4, hi)                     # the ridge
    return draw


def headscarf(color):
    hi, sh = shade(color, 1.25), shade(color, 0.72)

    def draw(cv, hx, hy, facing):
        cv.rect(hx, hy, hx + 15, hy + 6, color, sh=sh, hi=hi)
        cv.rect(hx - 1, hy + 4, hx, hy + 17, color)
        cv.rect(hx + 15, hy + 4, hx + 16, hy + 17, sh)
        cv.rect(hx + 2, hy - 1, hx + 13, hy - 1, color)
        cv.rect(hx + 1, hy + 15, hx + 14, hy + 16, color, sh=sh)       # wrapped under the chin
    return draw


def item(pattern: list[str], colors: dict[str, tuple], *, at=(19, 21), desk: list[str] | None = None,
         desk_at=(19, 20)):
    """Something to hold, drawn from a small pattern of letters (a space is
    nothing): in the hand when standing, and — when `desk` is given — a small
    version of it on the desk when working."""
    def stamp(cv, rows, ox, oy):
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch != " ":
                    cv.set(ox + dx, oy + dy, colors[ch])

    def holds(cv, pose):
        if pose == "idle":
            stamp(cv, pattern, *at)
        elif desk:
            stamp(cv, desk, *desk_at)
    return holds


W_ = (250, 250, 245, 255)
K_ = (40, 40, 52, 255)
G_ = (150, 150, 162, 255)

# What each one carries.
BLUEPRINT = item(["  bbbbb", " bBBBBBb", "bBwBwBBb", "bBBBBBBb", " bbbbbb"],
                 {"b": (30, 64, 175, 255), "B": (59, 130, 246, 255), "w": W_}, at=(18, 24),
                 desk=["bBBBBb"], desk_at=(19, 21))
NOTEPAD = item(["yyyyyy", "ywwwwy", "yGGGGy", "ywwwwy", "yGGGGy", "ywwwwy", "yyyyyy"],
               {"y": (250, 204, 21, 255), "w": W_, "G": G_}, at=(20, 22), desk=["ywwy"])
GLOBE = item([" bbbb ", "bgbbgb", "bbggbb", "bgbbbb", " bbbb ", "  kk  ", " kkkk "],
             {"b": (59, 130, 246, 255), "g": (34, 197, 94, 255), "k": (120, 80, 42, 255)}, at=(20, 21))
STICKIES = item(["yy pp", "yy pp", "  gg ", "  gg "],
                {"y": (250, 204, 21, 255), "p": (244, 114, 182, 255), "g": (74, 222, 128, 255)},
                at=(20, 23), desk=["yypp"])
MAP = item(["wwwwwww", "wBwwwRw", "wkkkkkw", "wwwGwww", "wwkkwww", "wwwwwww"],
           {"w": W_, "B": (59, 130, 246, 255), "R": (239, 68, 68, 255), "G": (34, 197, 94, 255), "k": G_},
           at=(19, 22), desk=["wBkkRw"])
PLUG = item(["  k  ", " kkk ", "kGGGk", "kGGGk", " kkk ", "  o  ", "  o  ", " oo  "],
            {"k": K_, "G": (148, 163, 184, 255), "o": (234, 88, 12, 255)}, at=(20, 21))
PALETTE = item([" wwww ", "wRwYww", "wwBwGw", "wwwwww", " ww  "],
               {"w": (232, 196, 140, 255), "R": (239, 68, 68, 255), "Y": (250, 204, 21, 255),
                "B": (59, 130, 246, 255), "G": (34, 197, 94, 255)}, at=(19, 23), desk=["RYBG"])
PENCIL_SHEET = item(["wwwww y", "wGGGw y", "wwwww y", "wGGGw y", "wwwww k"],
                    {"w": W_, "G": G_, "y": (250, 204, 21, 255), "k": K_}, at=(19, 22), desk=["wGGw"])
SHAPES = item(["RR pp", "RR pp", "oo ", "oo bb", "   bb", "gg   ", "gg   "],
              {"R": (242, 78, 30, 255), "p": (162, 89, 255, 255), "o": (255, 114, 98, 255),
               "b": (26, 188, 254, 255), "g": (10, 207, 131, 255)}, at=(20, 21), desk=["Rpbg"])
FRAME = item(["kk  kk", "k    k", "      ", "k    k", "kk  kk"], {"k": (250, 204, 21, 255)}, at=(20, 22))
DATABASE = item([" bbbb ", "bBBBBb", "bbbbbb", "bBBBBb", "bbbbbb", "bBBBBb", " bbbb "],
                {"b": (37, 99, 235, 255), "B": (96, 165, 250, 255)}, at=(20, 22), desk=["bBBb"])
TABLET_BRACES = item(["kkkkkk", "kwwwwk", "kbwwbk", "bwwwwb", "kbwwbk", "kwwwwk", "kkkkkk"],
                     {"k": K_, "w": (219, 234, 254, 255), "b": (79, 70, 229, 255)}, at=(20, 22))
SERVER = item(["kkkkkk", "kGgGGk", "kkkkkk", "kGGgGk", "kkkkkk", "kGgGGk", "kkkkkk"],
              {"k": (71, 85, 105, 255), "G": (148, 163, 184, 255), "g": (34, 197, 94, 255)}, at=(20, 22))
CHART = item(["wwwwww", "wwwwRw", "wwBwRw", "wGBwRw", "wGBwRw", "wwwwww"],
             {"w": W_, "R": (239, 68, 68, 255), "B": (59, 130, 246, 255), "G": (34, 197, 94, 255)},
             at=(20, 22), desk=["wGBRw"])
RULER = item(["yyyyyyy", "ykykyky", "yyyyyyy"], {"y": (250, 204, 21, 255), "k": K_}, at=(19, 26),
             desk=["ykyky"])
LAPTOP = item([" kkkkk", " kbbbk", " kbcbk", " kbbbk", "GGGGGGG"],
              {"k": K_, "b": (30, 41, 59, 255), "c": (97, 218, 251, 255), "G": G_}, at=(19, 23))
CODE_CARD = item(["wwwwwww", "w k  kw", "wk  k w", "w k k w", "wwwwwww"],
                 {"w": (217, 249, 157, 255), "k": (21, 128, 61, 255)}, at=(19, 22), desk=["wkkw"])
GEARS = item([" g g  ", "ggggg ", " gGg  ", "ggggg ", " g g s", "   sss", "    s "],
             {"g": (148, 163, 184, 255), "G": (71, 85, 105, 255), "s": (251, 146, 60, 255)}, at=(20, 22))
SCALES = item(["   y   ", "yyyyyyy", "y  y  y", "yy y yy", "   y   ", "  yyy  "],
              {"y": (217, 119, 6, 255)}, at=(19, 22))
SHIELD = item(["yyyyy", "yBBBy", "yBwBy", "yBBBy", " yBy ", "  y  "],
              {"y": (250, 204, 21, 255), "B": (30, 64, 175, 255), "w": W_}, at=(20, 22))
STAMP = item([" kk ", " kk ", "RRRR", "RRRR"], {"k": (120, 80, 42, 255), "R": (220, 38, 38, 255)}, at=(21, 24),
             desk=["RR"])
FILE_BOX = item(["bbbbbb", "bwwwwb", "bbbbbb", "bbkkbb", "bbbbbb"],
                {"b": (180, 132, 76, 255), "w": W_, "k": (120, 80, 42, 255)}, at=(20, 23))
CAMERA = item(["  kk  ", "kkkkkk", "kGbbGk", "kGbbGk", "kkkkkk"],
              {"k": K_, "G": G_, "b": (96, 165, 250, 255)}, at=(20, 23))
BUG_NET = item([" wwww", "w    w", "w    w", " wwww ", "  k   ", "  k   ", "  k   "],
               {"w": W_, "k": (120, 80, 42, 255)}, at=(20, 18))
WRENCH = item(["g g", "ggg", " g ", " g ", " g ", " g "], {"g": (148, 163, 184, 255)}, at=(21, 22))
ROCKET = item(["  w  ", " wRw ", " www ", " wbw ", "wwwww", "R o R", "  o  "],
              {"w": W_, "R": (220, 38, 38, 255), "b": (59, 130, 246, 255), "o": (251, 146, 60, 255)},
              at=(20, 20))
PUZZLE = item([" gg  ", "gggg ", "ggggp", " pppp", "  pp "],
              {"g": (34, 197, 94, 255), "p": (168, 85, 247, 255)}, at=(20, 24), desk=["ggpp"])

SKINS = {
    "light": ((246, 214, 182, 255), (222, 182, 146, 255)),
    "fair": ((246, 196, 152, 255), (222, 160, 118, 255)),
    "medium": ((222, 168, 124, 255), (194, 136, 96, 255)),
    "tan": ((196, 138, 94, 255), (166, 108, 70, 255)),
    "deep": ((140, 92, 64, 255), (112, 70, 46, 255)),
}

BLACK, DARK_BROWN, BROWN, AUBURN = (36, 32, 44, 255), (70, 44, 30, 255), (120, 72, 40, 255), (150, 62, 34, 255)
BLOND, GINGER, GREY, PLATINUM = (226, 190, 102, 255), (204, 102, 44, 255), (168, 168, 176, 255), (226, 226, 232, 255)

CAST = {
    "nina": {"hair": hair_ponytail((44, 38, 62, 255)), "top": (20, 184, 166, 255), "holds": phone,
             "screen": (94, 234, 212, 255)},
    "otto": {"hair": hair_neat((168, 168, 176, 255)), "glasses": True, "top": (241, 241, 246, 255),
             "vest": (124, 58, 237, 255), "holds": magnifier, "screen": (196, 181, 253, 255)},
    "trey": {"hair": cap((220, 38, 38, 255), (250, 250, 250, 255)), "top": (59, 130, 246, 255),
             "coat": (244, 244, 248, 255), "holds": checklist, "screen": (134, 239, 172, 255)},
    "remy": {"hair": beret((30, 58, 138, 255), (120, 72, 40, 255)), "top": (234, 179, 8, 255),
             "scarf": (190, 24, 93, 255), "holds": book, "screen": (253, 230, 138, 255)},
    # The rest of the team, each dressed for what they do.
    "smith": {"hair": hair_neat(DARK_BROWN), "beard": DARK_BROWN, "skin": SKINS["tan"], "top": (71, 85, 105, 255),
              "apron": (146, 92, 52, 255), "holds": BLUEPRINT},
    "rita": {"hair": hair_long(AUBURN), "skin": SKINS["light"], "top": (251, 113, 133, 255), "holds": NOTEPAD},
    "dana": {"hair": hair_curly(BLACK), "skin": SKINS["deep"], "top": (101, 163, 13, 255), "holds": GLOBE},
    "priya": {"hair": hair_bun(BLACK), "skin": SKINS["tan"], "top": (249, 115, 22, 255), "holds": STICKIES},
    "arjun": {"hair": hair_neat(BLACK), "skin": SKINS["tan"], "glasses": True, "top": (29, 78, 216, 255),
              "tie": (220, 38, 38, 255), "holds": MAP},
    "ivan": {"hair": hair_spiky(BLOND), "skin": SKINS["light"], "headphones": (51, 65, 85, 255),
             "top": (14, 116, 144, 255), "holds": PLUG},
    "iris": {"hair": hair_long(BROWN, band=(236, 72, 153, 255)), "skin": SKINS["medium"], "top": (236, 72, 153, 255),
             "holds": PALETTE},
    "paige": {"hair": hair_bun(GINGER), "skin": SKINS["light"], "top": (56, 189, 248, 255), "holds": PENCIL_SHEET},
    "felix": {"hair": beanie((234, 88, 12, 255), BROWN), "skin": SKINS["fair"], "top": (31, 41, 55, 255),
              "holds": SHAPES},
    "uma": {"hair": hair_long(BLACK), "skin": SKINS["deep"], "glasses": True, "top": (5, 150, 105, 255),
            "holds": FRAME},
    "bob": {"hair": hair_buzz(BROWN), "beard": BROWN, "skin": SKINS["fair"], "top": (22, 163, 74, 255),
            "overalls": (30, 64, 120, 255), "holds": DATABASE},
    "ada": {"hair": hair_long(AUBURN), "skin": SKINS["light"], "glasses": True, "top": (67, 56, 202, 255),
            "holds": TABLET_BRACES},
    "kai": {"hair": hair_spiky(BLACK), "skin": SKINS["tan"], "headphones": (220, 38, 38, 255),
            "top": (22, 101, 52, 255), "hoodie": (22, 101, 52, 255), "holds": SERVER},
    "ana": {"hair": hair_curly(DARK_BROWN), "skin": SKINS["medium"], "top": (217, 119, 6, 255), "holds": CHART},
    "theo": {"hair": hair_neat(BROWN), "skin": SKINS["light"], "top": (8, 145, 178, 255), "holds": RULER},
    "leo": {"hair": hair_spiky(GINGER), "skin": SKINS["fair"], "top": (37, 99, 235, 255),
            "hoodie": (37, 99, 235, 255), "holds": LAPTOP},
    "fern": {"hair": headscarf((22, 163, 74, 255)), "skin": SKINS["medium"], "top": (132, 204, 22, 255),
             "holds": CODE_CARD},
    "todd": {"hair": cap((37, 99, 235, 255), (250, 204, 21, 255)), "skin": SKINS["fair"], "top": (226, 232, 240, 255),
             "overalls": (71, 85, 105, 255), "holds": GEARS},
    "ruth": {"hair": hair_bun(GREY), "skin": SKINS["light"], "glasses": True, "top": (159, 18, 57, 255),
             "holds": SCALES},
    "sam": {"hair": hair_buzz(BLACK), "skin": SKINS["deep"], "top": (17, 24, 39, 255), "badge": (250, 204, 21, 255),
            "holds": SHIELD},
    "vera": {"hair": hair_long(BLOND), "skin": SKINS["light"], "top": (16, 185, 129, 255), "holds": STAMP},
    "mo": {"hair": hair_neat(GREY), "beard": GREY, "skin": SKINS["medium"], "top": (146, 64, 14, 255),
           "holds": FILE_BOX},
    "penny": {"hair": hair_curly(GINGER), "skin": SKINS["light"], "top": (225, 29, 72, 255), "holds": CAMERA},
    "tess": {"hair": hair_ponytail(BLOND), "skin": SKINS["medium"], "top": (250, 204, 21, 255), "holds": BUG_NET},
    "bruno": {"hair": hard_hat((250, 204, 21, 255), DARK_BROWN), "skin": SKINS["tan"], "top": (234, 88, 12, 255),
              "holds": WRENCH},
    "dex": {"hair": hair_spiky(PLATINUM), "skin": SKINS["deep"], "top": (2, 132, 199, 255), "holds": ROCKET},
    "abe": {"hair": beanie((100, 116, 139, 255), DARK_BROWN), "beard": DARK_BROWN, "skin": SKINS["fair"],
            "top": (120, 53, 15, 255), "holds": PUZZLE},
}

for key, p in CAST.items():
    (OUT / "idle").mkdir(parents=True, exist_ok=True)
    (OUT / "working").mkdir(parents=True, exist_ok=True)
    idle(p).save(OUT / "idle" / f"{key}.png")
    working(p).save(OUT / "working" / f"{key}.png")
print("drawn:", ", ".join(CAST))
