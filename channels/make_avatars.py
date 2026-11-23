"""Generate 20 distinct original GTA-themed channel avatars (800x800).

Original artwork: synthwave sunset + silhouettes + text. No Rockstar logos
or official art, so nothing here can be claimed by Take-Two.
    python3 channels/make_avatars.py
"""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).with_name("avatars")
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-BlackItalic.otf"
S = 800

CHANNELS = [  # (id, channel name, avatar label)
    ("gta-daily-clips", "GTA Daily Clips", "DAILY CLIPS"),
    ("gta-funny-moments", "GTA Funny Moments", "FUNNY"),
    ("gta-news-drop", "GTA News Drop", "NEWS"),
    ("gta-leaks-rumors", "GTA Leaks & Rumors", "LEAKS"),
    ("gta-streamer-reacts", "GTA Streamer Reacts", "REACTS"),
    ("gta-car-spotter", "GTA Car Spotter", "CARS"),
    ("gta-map-explorer", "GTA Map Explorer", "MAP"),
    ("gta-easter-eggs", "GTA Easter Eggs", "SECRETS"),
    ("gta-fails", "GTA Fails", "FAILS"),
    ("gta-chases", "GTA Chases", "CHASES"),
    ("gta-vice-nights", "GTA Vice Nights", "VICE NIGHTS"),
    ("gta-stunts", "GTA Stunts", "STUNTS"),
    ("gta-online-hub", "GTA Online Hub", "ONLINE"),
    ("gta-story-recap", "GTA Story Recap", "STORY"),
    ("gta-glitches", "GTA Glitches", "GLITCH"),
    ("gta-theories", "GTA Theories", "THEORIES"),
    ("gta-shorts-daily", "GTA Shorts Daily", "SHORTS"),
    ("gta-graphics-lab", "GTA Graphics Lab", "GRAPHICS"),
    ("gta-radio-vibes", "GTA Radio Vibes", "RADIO"),
    ("gta-crime-wave", "GTA Crime Wave", "CRIME WAVE"),
]

PALETTES = [  # sky top, sky bottom, sun top, sun bottom, accent
    ("#1a0533", "#ff5e9c", "#ffe259", "#ff2d75", "#00f0ff"),
    ("#02111f", "#ff7b00", "#fff3b0", "#ff4800", "#ffde59"),
    ("#0b0c2a", "#00c2ff", "#ffffff", "#00e1ff", "#ff3df2"),
    ("#120021", "#8a2be2", "#ff9de2", "#c13cff", "#39ff14"),
    ("#2b0010", "#ff3b3b", "#ffd166", "#ff006e", "#ffffff"),
    ("#001a14", "#00d18f", "#f6ff8a", "#00ffa3", "#ff4fd8"),
    ("#0a0f3d", "#ff8fab", "#fff1a8", "#ff6fa1", "#7df9ff"),
    ("#140b00", "#ffb000", "#fffbe0", "#ff8a00", "#00e5ff"),
    ("#1b0027", "#ff00a8", "#ffe600", "#ff4dc4", "#00ffd5"),
    ("#00121c", "#0077ff", "#9ff3ff", "#004dff", "#ff2e2e"),
]
FOREGROUNDS = ["palms", "skyline", "waves", "palms_skyline", "mountains"]


def hexc(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def shift(c, amount):
    """Rotate hue so channels 11-20 get their own palettes."""
    import colorsys
    h, l, s_ = colorsys.rgb_to_hls(*(v / 255 for v in c))
    return tuple(int(v * 255) for v in colorsys.hls_to_rgb((h + amount) % 1, l, s_))
def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(top, bot, size):
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        d.line([(0, y), (size[0], y)], fill=lerp(top, bot, y / size[1]))
    return img


def palm(d, x, base, h, lean, col, rnd):
    pts = []
    for i in range(21):
        t = i / 20
        pts.append((x + lean * t * t * h, base - h * t))
    for i in range(20):
        w = 14 * (1 - i / 20) + 5
        d.line([pts[i], pts[i + 1]], fill=col, width=int(w))
    cx, cy = pts[-1]
    for k in range(8):
        ang = math.radians(-180 + k * 26 + rnd.uniform(-8, 8))
        L = h * rnd.uniform(0.35, 0.5)
        frond = []
        for j in range(12):
            t = j / 11
            frond.append((cx + math.cos(ang) * L * t, cy + math.sin(ang) * L * t + 90 * t * t))
        for j in range(11):
            d.line([frond[j], frond[j + 1]], fill=col, width=int(16 * (1 - j / 11)) + 3)


def skyline(d, horizon, col, rnd):
    x = 0
    while x < S:
        w = rnd.randint(30, 80); h = rnd.randint(60, 260)
        d.rectangle([x, horizon - h, x + w, horizon + 5], fill=col)
        if rnd.random() < 0.3:
            d.rectangle([x + w // 2 - 3, horizon - h - 40, x + w // 2 + 3, horizon - h], fill=col)
        x += w + rnd.randint(-5, 6)


def make(idx, label):
    rnd = random.Random(idx * 7919)
    sky_t, sky_b, sun_t, sun_b, acc = map(hexc, PALETTES[idx % len(PALETTES)])
    if idx >= len(PALETTES):
        sky_t, sky_b, sun_t, sun_b, acc = (shift(c, 0.33) for c in (sky_t, sky_b, sun_t, sun_b, acc))
    fg = FOREGROUNDS[(idx // 2 + idx) % len(FOREGROUNDS)]
    img = gradient(sky_t, sky_b, (S, S))
    d = ImageDraw.Draw(img)

    # stars
    for _ in range(60):
        x, y = rnd.randint(0, S), rnd.randint(0, 320)
        d.point((x, y), fill=(255, 255, 255))

    # striped sun
    horizon = 560
    r = rnd.randint(150, 200)
    cx = S // 2 + rnd.randint(-120, 120)
    sun = gradient(sun_t, sun_b, (2 * r, 2 * r))
    mask = Image.new("L", (2 * r, 2 * r), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    for k in range(6):
        y = int(r * 1.05 + k * (r * 0.16))
        md.rectangle([0, y, 2 * r, y + 4 + k * 3], fill=0)
    glow = Image.new("RGB", (S, S), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - r - 40, horizon - r - 60, cx + r + 40, horizon + r - 20], fill=sun_b)
    img = Image.blend(img, Image.composite(glow.filter(ImageFilter.GaussianBlur(60)), img, Image.new("L", (S, S), 110)), 1)
    img.paste(sun, (cx - r, horizon - 40 - r), mask)
    d = ImageDraw.Draw(img)

    sil = lerp(sky_t, (0, 0, 0), 0.6)
    if fg in ("skyline", "palms_skyline"):
        skyline(d, horizon, lerp(sky_t, sky_b, 0.25), rnd)
    if fg == "mountains":
        pts = [(0, horizon)] + [(x, horizon - rnd.randint(40, 200)) for x in range(0, S + 100, 100)] + [(S, horizon)]
        d.polygon(pts, fill=lerp(sky_t, sky_b, 0.2))

    # neon grid floor / water
    d.rectangle([0, horizon, S, S], fill=sil)
    for k in range(12):
        y = horizon + int((k / 11) ** 2 * (S - horizon))
        d.line([(0, y), (S, y)], fill=acc if fg != "waves" else sun_b, width=2)
    if fg != "waves":
        for k in range(-10, 11):
            d.line([(S // 2 + k * 18, horizon), (S // 2 + k * 160, S)], fill=acc, width=2)

    if fg in ("palms", "palms_skyline", "waves"):
        palm(d, rnd.randint(150, 200), S - 60, rnd.randint(300, 360), rnd.randint(30, 60), sil, rnd)
        palm(d, rnd.randint(600, 650), S - 60, rnd.randint(260, 330), -rnd.randint(30, 60), sil, rnd)

    # text: big GTA + label, kept inside the circle YouTube crops to
    def text(t, size, y, fill, stroke):
        f = ImageFont.truetype(FONT, size)
        while d.textlength(t, font=f) > 560:
            size -= 4; f = ImageFont.truetype(FONT, size)
        w = d.textlength(t, font=f)
        d.text(((S - w) / 2 + 6, y + 6), t, font=f, fill=(0, 0, 0))
        d.text(((S - w) / 2, y), t, font=f, fill=fill, stroke_width=stroke, stroke_fill=(10, 10, 10))
    text("GTA", 230, 150, (255, 255, 255), 8)
    text(label, 92, 405, acc, 6)

    # subtle vignette
    vig = Image.new("L", (S, S), 0)
    ImageDraw.Draw(vig).ellipse([-200, -200, S + 200, S + 200], fill=255)
    img = Image.composite(img, Image.new("RGB", (S, S), (0, 0, 0)), vig.filter(ImageFilter.GaussianBlur(120)))
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for i, (cid, name, label) in enumerate(CHANNELS):
        make(i, label).save(OUT / f"{i + 1:02d}_{cid}.png", optimize=True)
    # contact sheet
    sheet = Image.new("RGB", (5 * 200, 4 * 200), "black")
    for i, p in enumerate(sorted(OUT.glob("[0-9]*.png"))):
        im = Image.open(p).resize((200, 200))
        m = Image.new("L", (200, 200), 0); ImageDraw.Draw(m).ellipse([0, 0, 199, 199], fill=255)
        sheet.paste(im, ((i % 5) * 200, (i // 5) * 200), m)
    sheet.save(OUT.parent / "avatars_preview.png")
    print("done")
