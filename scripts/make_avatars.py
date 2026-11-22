"""Generate simple square avatar candidates for Venus (512x512 PNG)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
OUT = Path(__file__).resolve().parent.parent / 'assets' / 'avatars'


def font(size):
    for name in ('georgia.ttf', 'times.ttf', 'arialbd.ttf', 'seguisb.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(top, bottom):
    img = Image.new('RGB', (SIZE, SIZE), top)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE):
        draw.line([(0, y), (SIZE, y)], fill=lerp(top, bottom, y / (SIZE - 1)))
    return img


def centered_letter(draw, letter, fnt, y_offset=0, fill='white', stroke=0, stroke_fill=None):
    box = draw.textbbox((0, 0), letter, font=fnt, stroke_width=stroke)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((SIZE - w) / 2 - box[0], (SIZE - h) / 2 - box[1] + y_offset),
              letter, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


def round_mask(img):
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def a_deep_violet():
    img = gradient((58, 32, 92), (24, 13, 42))
    d = ImageDraw.Draw(img)
    d.ellipse((96, 96, SIZE - 96, SIZE - 96), outline=(196, 160, 255), width=3)
    centered_letter(d, 'V', font(300), fill=(245, 238, 255))
    return round_mask(img)


def b_ink_star():
    img = Image.new('RGB', (SIZE, SIZE), (16, 16, 20))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, SIZE - 40, SIZE - 40), outline=(72, 72, 84), width=2)
    centered_letter(d, 'V', font(280), fill=(232, 232, 240))
    for (x, y, r) in ((150, 150, 3), (370, 132, 2), (392, 356, 3), (132, 380, 2), (256, 92, 2)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(150, 140, 200))
    return round_mask(img)


def c_blush_moon():
    img = gradient((255, 214, 226), (206, 166, 220))
    d = ImageDraw.Draw(img)
    d.ellipse((118, 118, SIZE - 118, SIZE - 118), fill=(255, 246, 250))
    centered_letter(d, 'V', font(250), fill=(158, 96, 128))
    d.arc((300, 300, 470, 470), start=200, end=340, fill=(255, 255, 255), width=6)
    return round_mask(img)


def d_flat_mono():
    img = Image.new('RGB', (SIZE, SIZE), (246, 244, 240))
    d = ImageDraw.Draw(img)
    centered_letter(d, 'V', font(320), fill=(30, 30, 34), stroke=0)
    d.line([(150, 372), (362, 372)], fill=(30, 30, 34), width=4)
    return round_mask(img)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, maker in (
        ('a-violet', a_deep_violet),
        ('b-ink', b_ink_star),
        ('c-blush', c_blush_moon),
        ('d-mono', d_flat_mono),
    ):
        path = OUT / f'{name}.png'
        maker().save(path)
        print(path)


if __name__ == '__main__':
    main()
