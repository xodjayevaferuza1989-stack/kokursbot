"""Emoji yordamchilari: faqat oddiy Unicode emojilar ishlatiladi.
Premium/custom emoji ID'lari ataylab o'chirilgan.
"""
import json
import os
import sqlite3

from dbpath import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

# (kalit, nomi, guruh, oddiy emoji) — TARTIB muhim: panelda "tartib bo'yicha joylash" shu ketma-ketlikda
_META = [
    ("battle", "Battle yaratish", "Asosiy menyu", "⚔️"),
    ("contest", "Konkurs yaratish", "Asosiy menyu", "🏆"),
    ("my_battles", "Mening battlelarim", "Asosiy menyu", "📋"),
    ("my_contests", "Mening konkurslarim", "Asosiy menyu", "🗂"),
    ("profile", "Profil", "Asosiy menyu", "👤"),
    ("lang", "Til", "Asosiy menyu", "🌐"),
    ("support", "Yordam", "Asosiy menyu", "💬"),
    ("guide", "Qo'llanma", "Asosiy menyu", "📖"),
    ("menu", "Menyu", "Asosiy menyu", "📋"),
    ("quiz", "Savol (viktorina)", "Bonus menyu", "❓"),
    ("daily", "Kunlik bonus", "Bonus menyu", "🎁"),
    ("shop", "Magazin", "Bonus menyu", "🛒"),
    ("promo", "Promokod", "Bonus menyu", "🎟"),
    ("share", "Ulashish", "Bonus menyu", "🔗"),
    ("home", "Uy (bosh menyu)", "Bonus menyu", "🏠"),
    ("coin", "Coin (ball)", "Bonus menyu", "🪙"),
    ("gift", "Sovg'a", "Bonus menyu", "🎁"),
    ("bend", "Battle tugatish", "Battle va konkurs tugmalari", "🏁"),
    ("bjoin", "Qatnashish", "Battle va konkurs tugmalari", "🙋"),
    ("boost", "Boost", "Battle va konkurs tugmalari", "🚀"),
    ("boostchk", "Boost tekshirilmoqda", "Battle va konkurs tugmalari", "🔎"),
    ("bres", "Natijalar (statistika)", "Battle va konkurs tugmalari", "📊"),
    ("bvot", "Ovoz berganlar", "Battle va konkurs tugmalari", "🗳"),
    ("cancel", "Rad etildi", "Battle va konkurs tugmalari", "❌"),
    ("cend", "Konkurs tugatish", "Battle va konkurs tugmalari", "🏁"),
    ("check", "Tasdiqlandi (tekshirish)", "Battle va konkurs tugmalari", "✅"),
    ("device", "Qurilmani tasdiqlash", "Battle va konkurs tugmalari", "📱"),
    ("w_party", "Xush kelibsiz: bayram", "Xabar belgilari", "🎉"),
    ("w_pin", "Xush kelibsiz: eslatma", "Xabar belgilari", "📌"),
    ("w_mega", "Kanallar", "Xabar belgilari", "📣"),
    ("w_gold", "1-o'rin", "Xabar belgilari", "🥇"),
    ("w_silver", "2-o'rin", "Xabar belgilari", "🥈"),
    ("w_bronze", "3-o'rin", "Xabar belgilari", "🥉"),
    ("w_ok", "Tasdiqlandi", "Xabar belgilari", "✅"),
    ("w_people", "Foydalanuvchilar", "Xabar belgilari", "👥"),
    ("w_warn", "Ogohlantirish", "Xabar belgilari", "⚠️"),
    ("w_down", "Pastga", "Xabar belgilari", "👇"),
    ("w_back", "Orqaga", "Xabar belgilari", "👈"),
    ('web', 'Web panel', 'Admin panel tugmalari', '🖥'),
    ('a_stats', 'Statistika', 'Admin panel tugmalari', '📊'),
    ('a_bc', 'Xabar yuborish', 'Admin panel tugmalari', '📢'),
    ('a_req', 'Majburiy kanallar', 'Admin panel tugmalari', '🔒'),
    ('a_chans', 'Ulangan kanallar', 'Admin panel tugmalari', '📋'),
    ('a_promo', "Promokod qo'shish", 'Admin panel tugmalari', '🎟'),
    ('a_promos', "Promokodlar ro'yxati", 'Admin panel tugmalari', '🎫'),
    ('a_quiz', "Savol qo'shish", 'Admin panel tugmalari', '🧠'),
    ('a_shop', "Mahsulot qo'shish", 'Admin panel tugmalari', '🛒'),
    ('a_shoplist', "Mahsulotlar ro'yxati", 'Admin panel tugmalari', '🛍'),
    ('a_points', 'Ball berish/ayirish', 'Admin panel tugmalari', '🪙'),
    ('a_ban', 'Bloklash', 'Admin panel tugmalari', '⛔'),
    ('a_unban', 'Blokdan chiqarish', 'Admin panel tugmalari', '✅'),
    ('a_exit', 'Admin paneldan chiqish', 'Admin panel tugmalari', '⬅️'),
    ('flag_uz', "Til: O'zbekcha", 'Boshqa tugmalar', '🇺🇿'),
    ('flag_ru', 'Til: Русский', 'Boshqa tugmalar', '🇷🇺'),
    ('flag_en', 'Til: English', 'Boshqa tugmalar', '🇬🇧'),
    ('bc_users', 'Xabar: foydalanuvchilarga', 'Boshqa tugmalar', '👥'),
    ('bc_chans', 'Xabar: kanallarga', 'Boshqa tugmalar', '📣'),
    ('bc_both', 'Xabar: ikkalasiga', 'Boshqa tugmalar', '📨'),
    ('add', "Qo'shish", 'Boshqa tugmalar', '➕'),
    ('del', "O'chirish", 'Boshqa tugmalar', '🗑'),
    ('stop', "To'xtatish", 'Boshqa tugmalar', '🛑'),
    ('next', 'Davom etish', 'Boshqa tugmalar', '▶️'),
    ('nosub', 'Obunasiz davom etish', 'Boshqa tugmalar', '🚫'),
    ('time', 'Vaqt bilan', 'Boshqa tugmalar', '🕒'),
    ('count', 'Ishtirokchilar soni bilan', 'Boshqa tugmalar', '👥'),
    ('save', 'Saqlash', 'Boshqa tugmalar', '💾'),
    ('swap', 'Usulni almashtirish', 'Boshqa tugmalar', '🔄'),
    ('votes', 'Ovoz soni bilan', 'Boshqa tugmalar', '🎯'),
]
ORDER = [m[0] for m in _META]
FALLBACK = {m[0]: m[3] for m in _META}


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS emoji_ids(key TEXT PRIMARY KEY, id TEXT)")
    return c


# Premium emoji ID'lari ishlatilmaydi. Eski JSON/env/DB qiymatlari e'tiborga olinmaydi.
IDS = {}


def save_ids(mapping: dict) -> None:
    """Premium emoji sozlamalari o'chirilgan; oddiy emoji fallback'lari ishlatiladi."""
    return None


def items() -> list:
    return [{"n": i, "key": k, "label": lbl, "group": grp, "fallback": fb, "id": IDS.get(k, "")}
            for i, (k, lbl, grp, fb) in enumerate(_META, 1)]


def pid(key: str):
    """Premium emoji o'chirilgan — hech qachon custom emoji ID qaytarmaydi."""
    return None


def label(key: str, text: str) -> str:
    """Tugma matniga oddiy Unicode emoji qo'shadi."""
    return f"{FALLBACK.get(key, '')} {text}".strip()


def tg(key: str) -> str:
    """Xabar matni uchun oddiy Unicode emoji."""
    return FALLBACK.get(key, "•")
