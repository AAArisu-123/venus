"""Second pass: refined Venus avatars (star, phase, scallop shell)."""

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


def radial(base, glow, inner=20, outer=400):
    img = Image.new('RGB', (SIZE, SIZE), base)
    d = ImageDraw.Draw(img)
    steps = 140
    for i in range(steps, 0, -1):
        t = i / steps
        r = int(inner + (outer - inner) * t)
        d.ellipse((SIZE // 2 - r, SIZE // 2 - r, SIZE // 2 + r, SIZE // 2 + r),
                  fill=lerp(glow, base, t))
    return img


def round_mask(img):
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img.convert('RGB'), (0, 0), mask)
    return out


def star():
    img = radial((10, 16, 38), (46, 66, 124), inner=18, outer=410)
    d = ImageDraw.Draw(img)
    for (x, y, r) in ((124, 138, 2), (392, 122, 2), (428, 350, 2), (104, 368, 2),
                      (348, 430, 2), (146, 256, 2), (412, 236, 2), (258, 96, 2),
                      (196, 408, 1), (330, 190, 1)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(168, 184, 226))
    cx, cy = SIZE // 2, SIZE // 2
    halo = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for r, a in ((132, 26), (96, 42), (66, 70), (42, 110)):
        hd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 236, 198, a))
    img = Image.alpha_composite(img.convert('RGBA'), halo.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=(255, 247, 228))
    d.ellipse((cx - 52, cy - 52, cx + 52, cy + 52), outline=(255, 238, 206, 55), width=2)
    d.line([(cx - 20, cy - 20), (cx - 8, cy - 8)], fill=(255, 252, 240), width=6)
    return round_mask(img)


def phase():
    img = vgrad((26, 20, 48), (12, 10, 26))
    layer = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = SIZE // 2
    r = 150
    halo = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse((cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26), fill=(255, 226, 186, 60))
    img = Image.alpha_composite(img.convert('RGBA'), halo.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(252, 240, 214))
    d.ellipse((cx - r + 66, cy - r - 6, cx + r + 66, cy + r - 6), fill=(24, 18, 44))
    return round_mask(img)


def shell():
    img = vgrad((255, 241, 232), (223, 169, 156))
    layer = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    apex = (SIZE // 2, 424)
    radius = 292
    spread = 0.62
    n = 9
    pts = []
    for i in range(n + 1):
        a = -spread + (2 * spread) * i / n
        pts.append((apex[0] + math.sin(a) * radius, apex[1] - math.cos(a) * radius))
    poly = [apex] + pts
    d.polygon(poly, fill=(255, 250, 244))
    for i, (x, y) in enumerate(pts):
        if 0 < i < len(pts) - 1:
            d.ellipse((x - 20, y - 16, x + 20, y + 16), fill=(255, 250, 244))
    for i in range(n):
        mx = (pts[i][0] + pts[i + 1][0]) / 2
        my = (pts[i][1] + pts[i + 1][1]) / 2
        d.line([apex, (mx, my)], fill=(240, 216, 205), width=5)
    d.line([apex, pts[0]], fill=(228, 196, 186), width=5)
    d.line([apex, pts[-1]], fill=(228, 196, 186), width=5)
    # Pearl resting in the shell, kept inside the fan.
    d.ellipse((SIZE // 2 - 34, 236, SIZE // 2 + 34, 304), fill=(252, 247, 241))
    d.ellipse((SIZE // 2 - 22, 246, SIZE // 2 - 2, 266), fill=(255, 255, 255))
    img = Image.alpha_composite(img.convert('RGBA'), layer)
    d2 = ImageDraw.Draw(img)
    return round_mask(img)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, maker in (('venus-star', star), ('venus-phase', phase), ('venus-shell', shell)):
        path = OUT / f'{name}.png'
        maker().convert('RGB').save(path)
        print(path)


if __name__ == '__main__':
    main()
