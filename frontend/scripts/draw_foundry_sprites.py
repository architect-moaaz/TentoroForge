"""Draw the Foundry characters that had names but no face (Nina, Otto, Trey,
Remy) as pixel art in the cast's proportions: standing (idle) and seated at
the desk (working).

    python3 frontend/scripts/draw_foundry_sprites.py frontend/public/sprites/characters
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
    # face
    cv.rect(hx + 1, hy + 5, hx + 14, hy + 14, SKIN, sh=SKIN_SH)
    cv.rect(hx + 2, hy + 15, hx + 13, hy + 15, SKIN_SH)
    # ears
    cv.rect(hx, hy + 8, hx, hy + 10, SKIN)
    cv.rect(hx + 15, hy + 8, hx + 15, hy + 10, SKIN_SH)
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
    # arms and hands
    cv.rect(4, 20, 6, 28, body, sh=body_sh)
    cv.rect(20, 20, 22, 27, body_sh)
    cv.rect(4, 29, 6, 30, SKIN)
    cv.rect(20, 28, 22, 29, SKIN)
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
    cv.rect(14, 19, 19, 21, body, sh=body_sh)
    cv.rect(12, 20, 14, 21, SKIN)
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


CAST = {
    "nina": {"hair": hair_ponytail((44, 38, 62, 255)), "top": (20, 184, 166, 255), "holds": phone,
             "screen": (94, 234, 212, 255)},
    "otto": {"hair": hair_neat((168, 168, 176, 255)), "glasses": True, "top": (241, 241, 246, 255),
             "vest": (124, 58, 237, 255), "holds": magnifier, "screen": (196, 181, 253, 255)},
    "trey": {"hair": cap((220, 38, 38, 255), (250, 250, 250, 255)), "top": (59, 130, 246, 255),
             "coat": (244, 244, 248, 255), "holds": checklist, "screen": (134, 239, 172, 255)},
    "remy": {"hair": beret((30, 58, 138, 255), (120, 72, 40, 255)), "top": (234, 179, 8, 255),
             "scarf": (190, 24, 93, 255), "holds": book, "screen": (253, 230, 138, 255)},
}

for key, p in CAST.items():
    (OUT / "idle").mkdir(parents=True, exist_ok=True)
    (OUT / "working").mkdir(parents=True, exist_ok=True)
    idle(p).save(OUT / "idle" / f"{key}.png")
    working(p).save(OUT / "working" / f"{key}.png")
print("drawn:", ", ".join(CAST))
