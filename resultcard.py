"""Battle natijalari uchun chiroyli rasm (PNG) yasaydi. Pillow kerak."""
import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_DIR = os.path.join(os.path.dirname(__file__), "assets")
W, H = 1080, 1350

TXT = {
    "uz": {"title": "BATTLE YAKUNLANDI", "winners": "G'OLIBLAR", "votes": "ovoz", "parts": "Ishtirokchilar", "total": "Jami ovozlar"},
    "ru": {"title": "БАТТЛ ЗАВЕРШЁН", "winners": "ПОБЕДИТЕЛИ", "votes": "гол.", "parts": "Участники", "total": "Всего голосов"},
}


def _font(bold: bool, size: int):
    try:
        return ImageFont.truetype(os.path.join(_DIR, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    except Exception:
        return ImageFont.load_default()


def _clean(s: str, limit: int = 22) -> str:
    s = "".join(ch for ch in str(s) if ord(ch) < 0x2190 and ch.isprintable()).strip() or "—"
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _fit(draw, text, bold, size, max_w):
    while size > 22:
        f = _font(bold, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(bold, size)


def _gradient():
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, bot = (12, 18, 48), (58, 28, 112)
    for y in range(H):
        k = y / (H - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3))
        for x in range(W):
            px[x, y] = c
    return img


def make_card(title: str, winners: list, participants: int, total: int, lang: str = "uz", footer: str = "") -> bytes:
    """winners: [(ism, ovoz_soni), ...] (g'oliblar, tartib bo'yicha)."""
    t = TXT.get(lang, TXT["uz"])
    img = _gradient().convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-220, -260, 560, 520), fill=(109, 141, 255, 70))
    g.ellipse((600, 780, 1320, 1500), fill=(155, 107, 255, 70))
    g.ellipse((700, -200, 1200, 300), fill=(34, 211, 238, 40))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(70)))
    d = ImageDraw.Draw(img)

    # sarlavha
    f = _font(True, 54)
    d.text((W // 2, 110), t["title"], font=f, fill=(255, 255, 255), anchor="mm")
    d.rounded_rectangle((W // 2 - 90, 160, W // 2 + 90, 166), radius=3, fill=(109, 141, 255))
    ttl = _clean(title, 40)
    d.text((W // 2, 225), ttl, font=_fit(d, ttl, True, 46, W - 160), fill=(200, 210, 255), anchor="mm")

    # kubok (oddiy shakllar)
    cx, cy = W // 2, 360
    d.ellipse((cx - 62, cy - 62, cx + 62, cy + 62), fill=(255, 200, 87))
    d.rectangle((cx - 16, cy + 50, cx + 16, cy + 96), fill=(255, 200, 87))
    d.rounded_rectangle((cx - 60, cy + 90, cx + 60, cy + 112), radius=8, fill=(255, 170, 40))
    d.text((cx, cy - 4), "1", font=_font(True, 64), fill=(120, 70, 0), anchor="mm")
    d.text((W // 2, 520), t["winners"], font=_font(True, 30), fill=(150, 165, 220), anchor="mm")

    medals = [(255, 200, 87), (200, 208, 224), (214, 140, 80)]
    y = 570
    shown = winners[:5]
    for i, (name, votes) in enumerate(shown):
        big = i < 3
        h = 118 if big else 84
        box = (70, y, W - 70, y + h)
        d.rounded_rectangle(box, radius=28, fill=(255, 255, 255, 30) if False else (34, 44, 92),
                            outline=(medals[i] if big else (70, 84, 150)), width=3 if big else 2)
        r = 40 if big else 28
        mx, my = 70 + 28 + r, y + h // 2
        d.ellipse((mx - r, my - r, mx + r, my + r), fill=medals[i] if big else (70, 84, 150))
        d.text((mx, my), str(i + 1), font=_font(True, 44 if big else 32), fill=(40, 30, 10) if big else (255, 255, 255), anchor="mm")
        nm = _clean(name, 20)
        d.text((mx + r + 28, my), nm, font=_fit(d, nm, True, 44 if big else 34, 520), fill=(255, 255, 255), anchor="lm")
        vt = f"{votes} {t['votes']}"
        d.text((W - 70 - 34, my), vt, font=_font(True, 40 if big else 30), fill=medals[i] if big else (170, 185, 240), anchor="rm")
        y += h + 16

    # pastki statistika
    fy = H - 150
    d.rounded_rectangle((70, fy, W - 70, fy + 84), radius=24, fill=(20, 26, 64))
    d.text((W // 4 + 20, fy + 42), f"{t['parts']}: {participants}", font=_font(True, 30), fill=(200, 210, 255), anchor="mm")
    d.text((3 * W // 4 - 20, fy + 42), f"{t['total']}: {total}", font=_font(True, 30), fill=(200, 210, 255), anchor="mm")
    if footer:
        d.text((W // 2, H - 36), _clean(footer, 40), font=_font(False, 26), fill=(130, 145, 200), anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
