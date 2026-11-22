"""Generate Venus-themed square avatars (512x512 PNG)."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
OUT = Path(__file__).resolve().parent.parent / 'assets' / 'avatars'


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vgrad(top, bottom):
    img = Image.new('RGB', (SIZE, SIZE), top)
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        d.line([(0, y), (SIZE, y)], fill=lerp(top, bottom, y / (SIZE - 1)))
    return img


def radial(base, glow, inner=40, outer=380):
    img = Image.new('RGB', (SIZE, SIZE), base)
    d = ImageDraw.Draw(img)
    steps = 120
    for i in range(steps, 0, -1):
        t = i / steps
        r = int(inner + (outer - inner) * t)
        color = lerp(glow, base, t)
        d.ellipse((SIZE // 2 - r, SIZE // 2 - r, SIZE // 2 + r, SIZE // 2 + r), fill=color)
    return img


def round_mask(img):
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img.convert('RGB'), (0, 0), mask)
    return out


def capsule(d, x0, y0, x1, y1, width, fill):
    d.line([(x0, y0), (x1, y1)], fill=fill, width=width)
    r = width // 2
    for (x, y) in ((x0, y0), (x1, y1)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def venus_symbol():
    img = vgrad((52, 38, 92), (22, 16, 44))
    glow = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((126, 126, SIZE - 126, SIZE - 126),
                                 outline=(168, 132, 255, 110), width=10)
    img = Image.alpha_composite(img.convert('RGBA'), glow.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(img)
    d.ellipse((138, 138, SIZE - 138, SIZE - 138), outline=(198, 170, 255, 70), width=2)
    cx = SIZE // 2
    d.ellipse((cx - 96, 148, cx + 96, 340), outline=(250, 245, 255), width=17)
    capsule(d, cx, 340, cx, 424, 17, (250, 245, 255))
    capsule(d, cx - 62, 382, cx + 62, 382, 17, (250, 245, 255))
    return round_mask(img)


def venus_shell():
    img = vgrad((255, 233, 219), (231, 176, 158))
    d = ImageDraw.Draw(img)
    cx, base_y = SIZE // 2, 402
    tip_y = 132
    d.ellipse((cx - 168, 96, cx + 168, 432), fill=(255, 248, 242))
    for i in range(11):
        t = i / 10
        angle = math.pi * (0.12 + 0.76 * t)
        x = cx + math.cos(angle) * 300
        y = tip_y + math.sin(angle) * 250
        d.line([(cx, base_y), (x, y)], fill=(238, 210, 198), width=6)
    d.ellipse((cx - 168, 96, cx + 168, 432), fill=None, outline=(216, 168, 152), width=6)
    d.ellipse((cx - 74, 150, cx + 74, 298), fill=(252, 246, 240), outline=(226, 196, 186), width=3)
    d.ellipse((cx - 44, 178, cx - 14, 208), fill=(255, 255, 255))
    return round_mask(img)


def venus_star():
    img = radial((9, 14, 34), (44, 62, 118), inner=30, outer=400)
    d = ImageDraw.Draw(img)
    for (x, y, r) in ((120, 132, 2), (396, 110, 2), (430, 344, 2), (96, 372, 2),
                      (352, 424, 2), (150, 250, 2), (410, 232, 2), (250, 108, 2)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(170, 186, 226))
    cx, cy = 256, 268
    halo = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for r, a in ((120, 40), (88, 60), (60, 90), (38, 140)):
        hd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 240, 210, a))
    img = Image.alpha_composite(img.convert('RGBA'), halo.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=(255, 246, 226))
    d.ellipse((cx - 66, cy - 66, cx + 66, cy + 66), outline=(255, 232, 196, 90), width=2)
    for (dx, dy) in ((92, 0), (-92, 0), (0, 92), (0, -92)):
        d.line([(cx + dx * 0.55, cy + dy * 0.55), (cx + dx, cy + dy)],
               fill=(255, 236, 205, 130), width=3)
    return round_mask(img)


def venus_rose():
    img = vgrad((255, 226, 226), (206, 140, 160))
    layer = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = SIZE // 2
    shades = [(214, 116, 138), (188, 92, 118), (166, 74, 102), (204, 108, 130), (150, 62, 92)]
    for i in range(28):
        r = 210 - i * 7
        angle = i * 0.55
        box = (cx - r, cy - r * 0.86, cx + r, cy + r * 0.86)
        d.arc(box, start=math.degrees(angle), end=math.degrees(angle + 200),
              fill=shades[i % len(shades)], width=13)
    d.ellipse((cx - 26, cy - 24, cx + 26, cy + 28), fill=(136, 54, 82))
    img = Image.alpha_composite(img.convert('RGBA'), layer)
    d2 = ImageDraw.Draw(img)
    d2.ellipse((120, 128, 150, 158), fill=(255, 249, 246, 190))
    return round_mask(img)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, maker in (
        ('venus-symbol', venus_symbol),
        ('venus-shell', venus_shell),
        ('venus-star', venus_star),
        ('venus-rose', venus_rose),
    ):
        path = OUT / f'{name}.png'
        maker().convert('RGB').save(path)
        print(path)


if __name__ == '__main__':
    main()
