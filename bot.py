import asyncio
import csv
import difflib
import html
import io
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import antimulti
from aiohttp import web
from contextvars import ContextVar
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from i18n import ru, ru_markup
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")   # tokenni kodga yozmang, muhit o'zgaruvchisi orqali bering
ADMIN_ID = int(os.getenv("ADMIN_ID", "8587976365"))
DB = os.getenv("DB_PATH", "bot.db")
BOT_USERNAME = ""
TZ = timezone(timedelta(hours=5))   # O'zbekiston vaqti
BOOST_BONUS = 1.3                   # boost bergan odamning yutish vazni (+30%)

# ----------------------------------------------------------------------------
# PREMIUM EMOJI:  kalit: (oddiy emoji, premium emoji ID)
# ----------------------------------------------------------------------------
EMOJI = {
    "battle":     ("🥊", "5424886390288584851"),   # Battle yaratish
    "konkurs":    ("🎁", "5426951582363191911"),   # KONKURS yaratish
    "my_battles": ("📋", "5427261064821639441"),   # Mening battlelarim
    "my_konkurs": ("🗂", "5427396291866953172"),   # Mening konkurslarim
    "profile":    ("👤", "5427110706606545103"),   # Profil
    "profile_title": ("👤", "5228920776467433249"),   # Mening profilim (sarlavha)
    "lang":       ("🌐", "5427362851251584525"),   # Til
    "support":    ("📩", "5229047709930917861"),   # Murojaat
    "guide":      ("📖", "5229037316110043544"),   # Qo'llanma
    "vote":       ("🗳", "5229141847024091270"),   # Ovoz berish
    "voted":      ("✅", "5231329046234676176"),   # Ovoz berdingiz
    "join":       ("✅", "5229030873659097247"),   # Qatnashish
    "joined_ok":  ("🎉", "5228844738366423775"),   # Qatnashdingiz
    "channel":    ("📢", "5231052755283493479"),   # Kanalga o'tish
    "boost":      ("🚀", ""),   # Boost berish
    "done":       ("✅", "5231212777175005525"),   # Tayyor
    "cancel":     ("❌", "5229070834034819777"),   # Bekor qilish
    "id":         ("🆔", "5334890573281114250"),   # profil: ID
    "name":       ("📛", "5445221832074483553"),   # profil: Ism
    "username":   ("🔗", "5424769253645523001"),   # profil: Username
    "language":   ("🌐", "5426938658806595911"),   # profil: Til
    "date":       ("📅", "5427063182793415662"),   # profil: Ro'yxatdan o'tgan
    "created":    ("🧑‍💻", "5424684930552599261"),   # Yaratgan battlelar
    "joined":     ("🎯", "5424628730905532030"),   # Qatnashgan
    "given":      ("🗳", "5426951582363191911"),   # Bergan ovozlar
    "received":   ("📥", "5426845140188694069"),   # Olgan ovozlar
    "points":     ("🏆", "5424698004433049713"),   # Ballar
    "home":       ("🏠", "5231319820644922550"),   # Bosh menyu
    "winner":     ("🏆", "5231434431847218707"),   # G'olib
    "finish":     ("🏁", ""),   # Yakunlandi
    "auto":       ("⚡", ""),   # Avto konkurs
    "admin":      ("⚙️", ""),   # Admin panel
}


def e(key: str) -> str:
    """Matn ichida ishlatiladigan emoji (HTML)."""
    fb, eid = EMOJI[key]
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>' if eid else fb


def label(key: str, text: str) -> str:
    fb, eid = EMOJI[key]
    return text if eid else f"{fb} {text}"


# Reply tugmalar matni (handlerlar aynan shu matn bilan solishtiradi)
BTN = {
    "battle":     label("battle", "Battle yaratish"),
    "konkurs":    label("konkurs", "KONKURS yaratish"),
    "my_battles": label("my_battles", "Mening battlelarim"),
    "my_konkurs": label("my_konkurs", "Mening konkurslarim"),
    "profile":    label("profile", "Profil"),
    "lang":       label("lang", "Til"),
    "support":    label("support", "Murojaat"),
    "guide":      label("guide", "Qo'llanma"),
    "auto":       label("auto", "Avto konkurs"),
    "admin":      label("admin", "Admin panel"),
    "done":       label("done", "Tayyor"),
    "cancel":     label("cancel", "Bekor qilish"),
}
SKIP_CH = "O'tkazib yuborish"
MANUAL = "Qo'lda yakunlayman"
NO_MIN = "Yo'q"

# ----------------------------------------------------------------------------
# TIL (uz / ru): chiqayotgan matnlar foydalanuvchi tiliga qarab o'giriladi
# ----------------------------------------------------------------------------
LANG: dict[int, str] = {}                       # faqat 'ru' tanlaganlar saqlanadi
_lang_ctx: ContextVar[str] = ContextVar("lang", default="uz")


async def load_langs():
    LANG.clear()
    for r in await db_all("SELECT id FROM users WHERE lang='ru'"):
        LANG[r["id"]] = "ru"


def is_btn(key: str):
    """Reply-tugma har ikkala tilda ham mos keladi."""
    labels = {BTN[key], ru(BTN[key])}

    def _f(m: Message) -> bool:
        return bool(m.text) and m.text in labels
    return _f


def is_txt(text: str | None, uz: str) -> bool:
    return bool(text) and text in (uz, ru(uz))


class I18nOut(BaseRequestMiddleware):
    """Telegram'ga ketayotgan so'rovdagi matn va tugmalarni qabul qiluvchi tiliga o'giradi."""

    async def __call__(self, make_request, bot, method):
        cid = getattr(method, "chat_id", None)
        lang = None
        if isinstance(cid, int) and cid > 0:
            lang = LANG.get(cid)
        elif cid is None and type(method).__name__ == "AnswerCallbackQuery":
            lang = _lang_ctx.get()
        if lang == "ru":
            for f in ("text", "caption"):
                v = getattr(method, f, None)
                if isinstance(v, str):
                    setattr(method, f, ru(v))
            rm = getattr(method, "reply_markup", None)
            if rm is not None:
                try:
                    method.reply_markup = ru_markup(rm)
                except Exception:
                    logging.exception("i18n markup")
        return await make_request(bot, method)


class LangCtx(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        _lang_ctx.set(LANG.get(u.id, "uz") if u else "uz")
        return await handler(event, data)


def kb_button(key: str, text: str, style: str | None = None) -> KeyboardButton:
    """Reply tugma. Premium ID bo'lsa ikonka sifatida qo'shiladi."""
    _, eid = EMOJI[key]
    extra = {}
    if style:
        extra["style"] = style  # success / primary / danger
    if eid:
        extra["icon_custom_emoji_id"] = eid
    return KeyboardButton(text=label(key, text), **extra)


def ik_button(key: str, text: str, style: str | None = None, **kw) -> InlineKeyboardButton:
    _, eid = EMOJI[key]
    extra = {}
    if style:
        extra["style"] = style
    if eid:
        extra["icon_custom_emoji_id"] = eid
    return InlineKeyboardButton(text=label(key, text), **extra, **kw)


def menu_kb(uid: int | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [kb_button("battle", "Battle yaratish", "success"),
         kb_button("konkurs", "KONKURS yaratish", "success")],
        [kb_button("auto", "Avto konkurs", "success")],
        [kb_button("my_battles", "Mening battlelarim", "primary"),
         kb_button("my_konkurs", "Mening konkurslarim", "primary")],
        [kb_button("profile", "Profil", "primary"),
         kb_button("lang", "Til", "primary")],
        [kb_button("support", "Murojaat", "danger"),
         kb_button("guide", "Qo'llanma", "danger")],
    ]
    if uid is not None and is_staff(uid):
        rows.append([kb_button("admin", "Admin panel", "primary")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/cancel", style="danger")]],
        resize_keyboard=True,
    )


def content_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[kb_button("done", "Tayyor", "success")],
                  [kb_button("cancel", "Bekor qilish", "danger")]],
        resize_keyboard=True,
    )


def skip_kb(text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text)],
                  [kb_button("cancel", "Bekor qilish", "danger")]],
        resize_keyboard=True,
    )


# ----------------------------------------------------------------------------
# Baza
# ----------------------------------------------------------------------------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                lang TEXT DEFAULT 'uz',
                joined_at TEXT DEFAULT (strftime('%d.%m.%Y','now'))
            );
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,                     -- battle / konkurs
                owner_id INTEGER,
                title TEXT,
                text TEXT DEFAULT '',
                channel TEXT,
                status TEXT DEFAULT 'draft',   -- draft / active / finished
                winners INTEGER DEFAULT 1,
                min_votes TEXT DEFAULT '',     -- battle: "99,50,25"
                ends_at INTEGER,
                channel_msg_id INTEGER,        -- kanaldagi post (tugmalar shu postda)
                dirty INTEGER DEFAULT 0,       -- tugmalarni yangilash kerakmi
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admins(   -- ega tayinlagan qo'shimcha adminlar
                user_id INTEGER PRIMARY KEY,
                perms TEXT,
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admin_log(   -- admin harakatlari jurnali
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER DEFAULT (strftime('%s','now')),
                actor_id INTEGER,
                action TEXT,
                target TEXT,
                details TEXT
            );
            CREATE TABLE IF NOT EXISTS req_channels(   -- majburiy obuna kanallari
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT UNIQUE,
                title TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS event_media(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                file_id TEXT,
                mtype TEXT                     -- photo / video / animation
            );
            CREATE TABLE IF NOT EXISTS participants(   -- battle ishtirokchilari
                event_id INTEGER,
                user_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS actions(
                event_id INTEGER,
                user_id INTEGER,
                option_id INTEGER,             -- battle: ovoz berilgan ishtirokchi user_id
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id, user_id)
            );
            """
        )
        # eski bazadan o'tish uchun (xato bersa e'tibor bermaymiz)
        for sql in ("ALTER TABLE events ADD COLUMN winners INTEGER DEFAULT 1",
                    "ALTER TABLE events ADD COLUMN ends_at INTEGER",
                    "ALTER TABLE events ADD COLUMN min_votes TEXT DEFAULT ''",
                    "ALTER TABLE events ADD COLUMN channel_msg_id INTEGER",
                    "ALTER TABLE events ADD COLUMN dirty INTEGER DEFAULT 0",
                    "ALTER TABLE actions ADD COLUMN option_id INTEGER",
                    "ALTER TABLE users ADD COLUMN tg_lang TEXT",
                    "ALTER TABLE events ADD COLUMN auto INTEGER DEFAULT 0",
                    "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0"):
            try:
                await db.execute(sql)
            except Exception:
                pass
        await db.executescript(antimulti.SCHEMA)
        await db.commit()


async def db_exec(sql, args=()):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid


async def db_run(sql, args=()):
    """O'zgargan qatorlar sonini qaytaradi."""
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.rowcount


async def db_one(sql, args=()):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return await cur.fetchone()


async def db_all(sql, args=()):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return await cur.fetchall()


async def count_actions(event_id: int) -> int:
    row = await db_one("SELECT COUNT(*) c FROM actions WHERE event_id=?", (event_id,))
    return row["c"]


async def count_participants(event_id: int) -> int:
    row = await db_one("SELECT COUNT(*) c FROM participants WHERE event_id=?", (event_id,))
    return row["c"]


async def event_count(ev) -> int:
    """Battleda ishtirokchilar soni, konkursda qatnashchilar soni."""
    return await (count_participants(ev["id"]) if ev["kind"] == "battle" else count_actions(ev["id"]))


async def participants_rows(event_id: int, limit: int = 100):
    """Ishtirokchilar ovozlar bo'yicha kamayish tartibida."""
    return await db_all(
        """SELECT p.user_id, u.username, u.full_name,
                  (SELECT COUNT(*) FROM actions a
                    WHERE a.event_id=p.event_id AND a.option_id=p.user_id) AS c
           FROM participants p LEFT JOIN users u ON u.id=p.user_id
           WHERE p.event_id=?
           ORDER BY c DESC, p.created_at ASC LIMIT ?""",
        (event_id, limit),
    )


# ----------------------------------------------------------------------------
# Yordamchi funksiyalar
# ----------------------------------------------------------------------------
router = Router()


class Create(StatesGroup):
    title = State()
    content = State()
    channel = State()
    winners = State()
    minvotes = State()
    ends = State()


class Support(StatesGroup):
    msg = State()


def share_link(event_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=join_{event_id}"


def rank_url(ev) -> str | None:
    base = (antimulti.WEBAPP_URL or "").rstrip("/")
    return f"{base}/rank?e={ev['id']}" if base.startswith("https://") else None


def fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def parse_time(s: str):
    try:
        dt = datetime.strptime(s.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
    except ValueError:
        return None
    return int(dt.timestamp())


def mention(uid: int, name: str | None) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name or str(uid))}</a>'


def boost_url(channel: str) -> str:
    return f"https://t.me/boost/{channel.lstrip('@')}"


def post_link(ev) -> str | None:
    if ev["channel"] and ev["channel_msg_id"]:
        return f"https://t.me/{ev['channel'].lstrip('@')}/{ev['channel_msg_id']}"
    return None


def get_mins(ev) -> list[int]:
    return [int(x) for x in (ev["min_votes"] or "").split(",") if x.isdigit()]


def person(r) -> str:
    """Ishtirokchi nomi: @username yoki ism."""
    if r["username"]:
        return f"@{r['username']}"
    return r["full_name"] or str(r["user_id"])


def post_caption(ev) -> str:
    if ev["auto"]:
        cap = AUTO_TEXT
        if (ev["winners"] or 1) > 1:
            cap += f"\n\n{e('winner')} G'oliblar soni: <b>{ev['winners']}</b>"
    else:
        cap = f"<b>{html.escape(ev['title'])}</b>"
        if ev["text"]:
            cap += f"\n\n{html.escape(ev['text'])}"
        if ev["kind"] == "battle":
            cap += (f"\n\n{e('winner')} Eng ko'p ovoz to'plagan "
                    f"<b>{ev['winners'] or 1}</b> ta ishtirokchi g'olib bo'ladi.")
            mins = get_mins(ev)
            if mins:
                cap += "\n" + "\n".join(f"{i}-o'rin: min {v} ovoz" for i, v in enumerate(mins, 1))
        else:
            cap += f"\n\n{e('winner')} G'oliblar soni: <b>{ev['winners'] or 1}</b>"
            if ev["channel"]:
                cap += f"\n{e('boost')} Kanalga boost bergan ishtirokchining yutish imkoni 30% ga oshadi."
    if ev["ends_at"]:
        cap += f"\n\n⏰ <b>{fmt_time(ev['ends_at'])}</b> da stop"
    if ev["status"] == "finished":
        cap += f"\n\n{e('finish')} <b>Yakunlangan</b>"
    return cap


async def event_kb(ev) -> InlineKeyboardMarkup:
    """Botning ichida ko'rsatiladigan tugmalar (ishtirokchi bo'lish / qatnashish)."""
    rows = []
    n = await event_count(ev)
    if ev["status"] == "active":
        if ev["kind"] == "battle":
            rows.append([ik_button("join", f"Qatnashish ({n})", "success",
                                   callback_data=f"join:{ev['id']}")])
        else:
            rows.append([ik_button("join", f"Qatnashish ({n})", "success",
                                   callback_data=f"act:{ev['id']}")])
    if ev["kind"] == "battle" and rank_url(ev):
        rows.append([InlineKeyboardButton(text="📊 Jonli reyting", url=rank_url(ev))])
    link = post_link(ev) or (f"https://t.me/{ev['channel'].lstrip('@')}" if ev["channel"] else None)
    if link:
        txt = "Ovoz berish uchun postga o'tish" if ev["kind"] == "battle" else "Kanalga o'tish"
        rows.append([ik_button("channel", txt, "primary", url=link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def channel_kb(ev) -> InlineKeyboardMarkup | None:
    """Kanaldagi post tagidagi tugmalar."""
    if ev["kind"] == "battle":
        rows = []
        for r in await participants_rows(ev["id"], 99):
            rows.append([InlineKeyboardButton(
                text=f"{person(r)} ({r['c']})",
                callback_data=f"vote:{ev['id']}:{r['user_id']}")])
        if ev["status"] == "active":
            rows.append([ik_button("join", "Qatnashish", "success", url=share_link(ev["id"]))])
        if rows and rank_url(ev):
            rows.append([InlineKeyboardButton(text="📊 Jonli reyting", url=rank_url(ev))])
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    if ev["status"] != "active":
        return None
    n = await count_actions(ev["id"])
    return InlineKeyboardMarkup(inline_keyboard=[[
        ik_button("join", f"QATNASHISH ({n})", "success", url=share_link(ev["id"]))]])


async def refresh_channel_post(bot: Bot, ev):
    """Kanaldagi post tugmalarini (ovozlar, qatnashchilar soni) yangilaydi."""
    if not ev["channel"] or not ev["channel_msg_id"]:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=ev["channel"], message_id=ev["channel_msg_id"],
            reply_markup=await channel_kb(ev))
    except Exception as ex:  # "message is not modified" va h.k.
        logging.debug("refresh: %s", ex)


async def send_post(bot: Bot, chat_id, ev, kb):
    """Postni yuboradi (matn, 1 ta media yoki albom). Tugmali xabarni qaytaradi."""
    media = await db_all("SELECT * FROM event_media WHERE event_id=? ORDER BY id", (ev["id"],))
    cap = post_caption(ev)

    if not media:
        return await bot.send_message(chat_id, cap, reply_markup=kb)

    long_caption = len(cap) > 1000
    if long_caption:
        await bot.send_message(chat_id, cap)
    c = None if long_caption else cap

    if len(media) == 1:
        m = media[0]
        send = {"photo": bot.send_photo, "video": bot.send_video,
                "animation": bot.send_animation}[m["mtype"]]
        return await send(chat_id, **{m["mtype"]: m["file_id"]}, caption=c, reply_markup=kb)

    group = []
    for i, m in enumerate(media):
        cls = InputMediaPhoto if m["mtype"] == "photo" else InputMediaVideo
        group.append(cls(media=m["file_id"], caption=c if i == 0 else None))
    await bot.send_media_group(chat_id, group)
    return await bot.send_message(chat_id, "👇", reply_markup=kb)


async def upsert_user(m: Message):
    u = m.from_user
    await db_exec(
        """INSERT INTO users(id, username, full_name) VALUES(?,?,?)
           ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
        (u.id, u.username, u.full_name),
    )


async def ensure_user(c: CallbackQuery):
    await db_exec(
        """INSERT INTO users(id, username, full_name, tg_lang) VALUES(?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name,
                                         tg_lang=excluded.tg_lang""",
        (c.from_user.id, c.from_user.username, c.from_user.full_name, c.from_user.language_code),
    )


async def is_subscribed(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return True  # tekshirib bo'lmasa, foydalanuvchini to'smaymiz


async def has_boost(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        b = await bot.get_user_chat_boosts(channel, user_id)
        return bool(b.boosts)
    except Exception:
        return False


CH_RE = re.compile(r"^(?:https?://)?(?:t\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,31})$")


def normalize_channel(raw: str) -> str | None:
    mt = CH_RE.match((raw or "").strip())
    return f"@{mt.group(1)}" if mt else None


def chk_uid(uid: int) -> int | None:
    """Bot egasi uchun kanal adminligi tekshirilmaydi."""
    return None if uid == ADMIN_ID else uid


def fail_text(reason: str) -> str:
    return f"❌ <b>Ulanmadi</b>\nSabab: <b>{html.escape(reason)}</b>"


async def check_channel(bot: Bot, raw: str, user_id: int | None = None):
    """Kanalni ulash mumkinmi? -> (ok, @kanal, nomi, sabab).
    Sabab: user topilmadi / admin emas / ..."""
    ch = normalize_channel(raw)
    if not ch:
        return False, None, None, "user topilmadi"
    try:
        chat = await bot.get_chat(ch)
    except Exception:
        return False, None, None, "user topilmadi"
    if chat.type not in ("channel", "supergroup"):
        return False, None, None, "bu kanal emas"
    if not chat.username:
        return False, None, None, "kanal ochiq (public) emas"
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception:
        return False, None, None, "admin emas"
    if me.status not in ("administrator", "creator"):
        return False, None, None, "admin emas"
    if chat.type == "channel" and me.status == "administrator" \
            and getattr(me, "can_post_messages", None) is False:
        return False, None, None, "botda xabar yuborish huquqi yo'q"
    if user_id:
        try:
            um = await bot.get_chat_member(chat.id, user_id)
            if um.status not in ("administrator", "creator"):
                return False, None, None, "siz kanal admini emassiz"
        except Exception:
            return False, None, None, "siz kanal admini emassiz"
    return True, f"@{chat.username}", chat.title or chat.username, ""


# ----------------------------------------------------------------------------
# /start, bekor qilish
# ----------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, state: FSMContext, bot: Bot):
    await state.clear()
    await upsert_user(m)
    arg = command.args or ""
    if arg == "verify":
        if not await send_verify(bot, m.from_user.id):
            await m.answer("Xatolik, keyinroq urinib ko'ring.")
        return
    if arg.startswith("join_") and arg[5:].isdigit():
        ev = await db_one("SELECT * FROM events WHERE id=? AND status!='draft'", (int(arg[5:]),))
        if ev:
            await send_post(bot, m.chat.id, ev, await event_kb(ev))
            return
    await m.answer(f"{e('home')} <b>Bosh menyu</b>", reply_markup=menu_kb(m.from_user.id))


@router.message(Command("cancel"))
@router.message(is_btn("cancel"))
async def cancel(m: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("event_id"):
        eid = data["event_id"]
        await db_exec("DELETE FROM event_media WHERE event_id=?", (eid,))
        await db_exec("DELETE FROM events WHERE id=? AND status='draft'", (eid,))
    await state.clear()
    await m.answer(f"{e('home')} Bosh menyu", reply_markup=menu_kb(m.from_user.id))


# ----------------------------------------------------------------------------
# Majburiy obuna kanallari (admin paneldan qo'shiladi)
# ----------------------------------------------------------------------------
_sub_cache: dict[tuple[int, str], float] = {}
SUB_TTL = 60
SUB_TEXT = "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng «Tekshirish» ni bosing."


async def req_channels():
    return await db_all("SELECT * FROM req_channels ORDER BY id")


async def missing_channels(bot: Bot, user_id: int) -> list:
    out, now = [], time.time()
    for ch in await req_channels():
        if _sub_cache.get((user_id, ch["channel"]), 0) > now:
            continue
        if await is_subscribed(bot, ch["channel"], user_id):
            _sub_cache[(user_id, ch["channel"])] = now + SUB_TTL
        else:
            out.append(ch)
    return out


def sub_kb(chs, arg: str = "") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title'] or c['channel']}",
                                  url=f"https://t.me/{c['channel'].lstrip('@')}")] for c in chs]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data=f"subchk:{arg}"[:64])])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class SubGate(BaseMiddleware):
    """Majburiy kanallarga obuna bo'lmagan foydalanuvchini to'xtatadi (admin istisno)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or user.is_bot or is_staff(user.id):
            return await handler(event, data)
        if user.id in BANNED:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Siz bloklangansiz.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ Siz bloklangansiz.")
            return None
        if isinstance(event, CallbackQuery) and (event.data or "").startswith("subchk:"):
            return await handler(event, data)
        bot: Bot = data["bot"]
        missing = await missing_channels(bot, user.id)
        if not missing:
            return await handler(event, data)
        if isinstance(event, Message):
            await upsert_user(event)
            arg = ""
            if event.text and event.text.startswith("/start "):
                arg = event.text.split(maxsplit=1)[1].strip()[:40]
            await event.answer(SUB_TEXT, reply_markup=sub_kb(missing, arg))
        elif isinstance(event, CallbackQuery):
            await event.answer("Avval majburiy kanallarga obuna bo'ling.", show_alert=True)
            try:
                await bot.send_message(user.id, SUB_TEXT, reply_markup=sub_kb(missing))
            except Exception:
                pass
        return None


router.message.outer_middleware(SubGate())
router.callback_query.outer_middleware(SubGate())


@router.callback_query(F.data.startswith("subchk:"))
async def sub_check(c: CallbackQuery, bot: Bot):
    arg = c.data[7:]
    missing = await missing_channels(bot, c.from_user.id)
    if missing:
        await c.answer("Hali hamma kanalga obuna bo'lmagansiz.", show_alert=True)
        try:
            await c.message.edit_reply_markup(reply_markup=sub_kb(missing, arg))
        except Exception:
            pass
        return
    await c.answer("Rahmat! ✅")
    await ensure_user(c)
    try:
        await c.message.delete()
    except Exception:
        pass
    if arg.startswith("join_") and arg[5:].isdigit():
        ev = await db_one("SELECT * FROM events WHERE id=? AND status!='draft'", (int(arg[5:]),))
        if ev:
            await send_post(bot, c.from_user.id, ev, await event_kb(ev))
            return
    await bot.send_message(c.from_user.id, f"{e('home')} <b>Bosh menyu</b>",
                           reply_markup=menu_kb(c.from_user.id))


# ----------------------------------------------------------------------------
# AVTO KONKURS: "#konkurs" yozilsa tayyor battle posti chiqadi
# ----------------------------------------------------------------------------
AUTO_TEXT = (
    "🏁 🏆 <b>BATTLE BOSHLANADI</b> ✅ 🥳\n\n"
    "❗❗❗ <b>ENG KO'P OVOZ YIG'GAN ODAM G'OLIB BO'LADI</b> ✅\n\n"
    "AGAR KANALDAN CHIQIB KETSANGIZ, BERGAN OVOZINGIZ BEKOR QILINADI 🛑❗\n\n"
    "🎁 BATTLEGA QO'YILGAN YUTUQLAR: <b>HOZIRCHA SIR</b> 🤫"
)
AUTO_RE = re.compile(r"^#konkurs(?:\s+(\d{1,3}))?$", re.I)


class Auto(StatesGroup):
    channel = State()


def _is_auto(m: Message) -> bool:
    return bool(m.text and AUTO_RE.match(m.text.strip()))


def _auto_winners(text: str) -> int:
    mt = AUTO_RE.match(text.strip())
    n = int(mt.group(1)) if mt and mt.group(1) else 1
    return max(1, min(n, 100))


async def new_auto_battle(owner_id: int, winners: int = 1) -> int:
    return await db_exec(
        "INSERT INTO events(kind, owner_id, title, text, winners, auto, status) "
        "VALUES('battle', ?, 'BATTLE', '', ?, 1, 'draft')", (owner_id, winners))


async def publish_auto(bot: Bot, eid: int, channel: str):
    """Battleni kanalga chiqaradi va faollashtiradi."""
    await db_exec("UPDATE events SET channel=?, status='active' WHERE id=?", (channel, eid))
    try:
        ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
        msg = await send_post(bot, channel, ev, await channel_kb(ev))
    except Exception:
        await db_exec("UPDATE events SET channel=NULL, status='draft' WHERE id=?", (eid,))
        raise
    await db_exec("UPDATE events SET channel_msg_id=? WHERE id=?", (msg.message_id, eid))
    return await db_one("SELECT * FROM events WHERE id=?", (eid,))


async def start_auto(m: Message, state: FSMContext, winners: int = 1):
    await state.clear()
    await upsert_user(m)
    eid = await new_auto_battle(m.from_user.id, winners)
    ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
    await m.answer(f"{e('battle')} <b>Battle yaratildi</b> ✅\n\nPost shunday ko'rinadi:",
                   reply_markup=menu_kb(m.from_user.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        ik_button("channel", "Kanal qo'shish", "success", callback_data=f"autoch:{eid}")]])
    await m.answer(post_caption(ev), reply_markup=kb)


@router.message(is_btn("auto"))
async def auto_btn(m: Message, state: FSMContext):
    await start_auto(m, state)


@router.message(_is_auto)
async def auto_hashtag(m: Message, state: FSMContext):
    await start_auto(m, state, _auto_winners(m.text))


@router.callback_query(F.data.startswith("autoch:"))
async def auto_add_channel(c: CallbackQuery, state: FSMContext):
    eid = int(c.data.split(":")[1])
    ev = await db_one("SELECT * FROM events WHERE id=? AND owner_id=? AND status='draft'",
                      (eid, c.from_user.id))
    if not ev:
        await c.answer("Bu battle allaqachon ishga tushgan yoki topilmadi.", show_alert=True)
        return
    await state.set_state(Auto.channel)
    await state.update_data(event_id=eid)
    await c.message.answer(
        f"{e('channel')} Kanalingizni yuboring (masalan <code>@kanal</code>).\n"
        "Bot kanalda admin bo'lishi kerak.", reply_markup=cancel_kb())
    await c.answer()


@router.message(Auto.channel, F.text)
async def auto_channel(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    eid = data["event_id"]
    ok, channel, _, reason = await check_channel(bot, m.text, chk_uid(m.from_user.id))
    if not ok:
        await m.answer(fail_text(reason) + "\n\nBoshqa kanal yuboring yoki bekor qiling.")
        return
    try:
        await publish_auto(bot, eid, channel)
    except Exception:
        logging.exception("auto battle post")
        await m.answer(fail_text("kanalga post yuborib bo'lmadi"))
        return
    await state.clear()
    await m.answer(
        f"{e('done')} <b>Ulandi:</b> {channel}\n"
        f"{e('channel')} Battle posti kanalga yuborildi.\n\n"
        f"Ishtirokchilar uchun havola:\n<code>{share_link(eid)}</code>\n\n"
        "Battleni «Mening battlelarim» bo'limidan yakunlaysiz.",
        reply_markup=menu_kb(m.from_user.id))


@router.channel_post(F.text)
async def channel_trigger(m: Message, bot: Bot):
    """Kanalda (bot admin bo'lsa) "#konkurs" yozilsa, battle avtomatik chiqadi."""
    if not _is_auto(m) or not m.chat.username:
        return
    try:
        admins = await bot.get_chat_administrators(m.chat.id)
    except Exception:
        return
    owner = next((a.user for a in admins if a.status == "creator"), None)
    if not owner or owner.is_bot:
        return
    await db_exec(
        """INSERT INTO users(id, username, full_name) VALUES(?,?,?)
           ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
        (owner.id, owner.username, owner.full_name))
    eid = await new_auto_battle(owner.id, _auto_winners(m.text))
    try:
        await publish_auto(bot, eid, f"@{m.chat.username}")
    except Exception:
        logging.exception("channel #konkurs")
        return
    try:
        await m.delete()
    except Exception:
        pass
    try:
        await bot.send_message(
            owner.id,
            f"{e('battle')} <b>Battle @{m.chat.username} kanalida boshlandi!</b>\n\n"
            f"Ishtirokchilar uchun havola:\n<code>{share_link(eid)}</code>")
    except Exception:
        pass


@router.chat_member()
async def member_left(u: ChatMemberUpdated, bot: Bot):
    """Kanaldan chiqqan odamning faol battledagi ovozi bekor qilinadi."""
    if u.new_chat_member.status not in ("left", "kicked") or not u.chat.username:
        return
    ch = f"@{u.chat.username}"
    uid = u.new_chat_member.user.id
    _sub_cache.pop((uid, ch), None)
    for ev in await db_all("SELECT id FROM events WHERE kind='battle' AND status='active' "
                           "AND lower(channel)=lower(?)", (ch,)):
        n = await db_run("DELETE FROM actions WHERE event_id=? AND user_id=?", (ev["id"], uid))
        if n:
            await db_run("UPDATE events SET dirty=1 WHERE id=?", (ev["id"],))
            try:
                await bot.send_message(
                    uid, f"🛑 Siz {ch} kanalidan chiqib ketdingiz, shuning uchun bergan ovozingiz bekor qilindi.")
            except Exception:
                pass


# ----------------------------------------------------------------------------
# Battle / Konkurs yaratish
# ----------------------------------------------------------------------------
async def start_create(m: Message, state: FSMContext, kind: str):
    await state.clear()
    await state.set_state(Create.title)
    await state.update_data(kind=kind)
    if kind == "battle":
        txt = (f"{e('battle')} <b>Battle yaratish</b>\n\n"
               "📝 Battle nomini kiriting\n\nMisol:\n• Yozgi batl")
    else:
        txt = (f"{e('konkurs')} <b>Konkurs yaratish</b>\n\n"
               "📝 Konkurs nomini kiriting\n\nMisol:\n• iPhone yutib oling")
    await m.answer(txt, reply_markup=cancel_kb())


@router.message(is_btn("battle"))
async def create_battle(m: Message, state: FSMContext):
    await start_create(m, state, "battle")


@router.message(is_btn("konkurs"))
async def create_konkurs(m: Message, state: FSMContext):
    await start_create(m, state, "konkurs")


@router.message(Create.title, F.text)
async def got_title(m: Message, state: FSMContext):
    data = await state.get_data()
    eid = await db_exec(
        "INSERT INTO events(kind, owner_id, title) VALUES(?,?,?)",
        (data["kind"], m.from_user.id, m.text[:200]),
    )
    await state.update_data(event_id=eid)
    await state.set_state(Create.content)
    if data["kind"] == "battle":
        txt = ("Battle posti uchun matn yuboring (shartlar, sovrinlar, o'rinlar). "
               "Xohlasangiz 1 tadan 10 tagacha rasm/video yoki bitta GIF ham biriktiring.\n"
               "<i>Albom bo'lsa, ko'rinishi kerak bo'lgan tartibda yuboring.</i>\n\n"
               "Tugatgach «Tayyor» tugmasini bosing.")
    else:
        txt = ("Konkurs posti uchun matn yuboring (shartlar, sovrinlar). Xohlasangiz "
               "1 tadan 10 tagacha rasm/video yoki bitta GIF ham biriktiring.\n"
               "<i>Agar fayllar bittadan ko'p bo'lsa, post karusel (albom) bo'ladi.</i>\n\n"
               "Tugatgach «Tayyor» tugmasini bosing.")
    await m.answer(txt, reply_markup=content_kb())


@router.message(Create.content, is_btn("done"))
async def content_done(m: Message, state: FSMContext):
    data = await state.get_data()
    ev = await db_one("SELECT * FROM events WHERE id=?", (data["event_id"],))
    n = (await db_one("SELECT COUNT(*) c FROM event_media WHERE event_id=?", (ev["id"],)))["c"]
    if not ev["text"] and n == 0:
        await m.answer("Avval matn yoki media yuboring.")
        return
    await state.set_state(Create.channel)
    if ev["kind"] == "battle":
        await m.answer(
            f"{e('channel')} Kanalni yuboring (masalan <code>@kanal</code>).\n"
            "Post shu kanalga chiqadi va ovoz berish ham shu yerda bo'ladi. "
            "Bot kanalda admin bo'lishi kerak.",
            reply_markup=cancel_kb(),
        )
    else:
        await m.answer(
            f"{e('channel')} Kanalni yuboring (masalan <code>@kanal</code>).\n"
            "Post shu kanalga chiqadi, ishtirokchilar kanalga obuna bo'lishi shart bo'ladi, "
            "boost ham shu kanal uchun hisoblanadi. Bot kanalda admin bo'lishi kerak.",
            reply_markup=skip_kb(SKIP_CH),
        )


@router.message(Create.content)
async def content_collect(m: Message, state: FSMContext):
    data = await state.get_data()
    eid = data["event_id"]
    count = (await db_one("SELECT COUNT(*) c FROM event_media WHERE event_id=?", (eid,)))["c"]

    if m.photo:
        mtype, fid = "photo", m.photo[-1].file_id
    elif m.video:
        mtype, fid = "video", m.video.file_id
    elif m.animation:
        mtype, fid = "animation", m.animation.file_id
    else:
        mtype = fid = None

    text = m.text or m.caption
    if text:
        await db_exec("UPDATE events SET text=? WHERE id=?", (text[:3000], eid))

    if mtype:
        if count >= 10:
            await m.answer("Maksimum 10 ta fayl.")
            return
        if mtype == "animation" and count > 0:
            await m.answer("GIF bilan boshqa media qo'shib bo'lmaydi.")
            return
        await db_exec("INSERT INTO event_media(event_id, file_id, mtype) VALUES(?,?,?)",
                      (eid, fid, mtype))
    elif not text:
        await m.answer("Faqat matn, rasm, video yoki GIF yuboring.")
        return

    if not m.media_group_id:  # albomda har bir fayl uchun javob bermaymiz
        await m.answer(f"{e('done')} Qabul qilindi. Yana yuborishingiz yoki «Tayyor» ni bosishingiz mumkin.")


@router.message(Create.channel, F.text)
async def got_channel(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    eid = data["event_id"]
    channel = None
    if is_txt(m.text, SKIP_CH):
        if data["kind"] == "battle":
            await m.answer("Battle uchun kanal shart. Kanalni yuboring.")
            return
    else:
        ok, channel, _, reason = await check_channel(bot, m.text, chk_uid(m.from_user.id))
        if not ok:
            await m.answer(fail_text(reason) + "\n\nQayta yuboring yoki bekor qiling.")
            return
    await db_exec("UPDATE events SET channel=? WHERE id=?", (channel, eid))
    await state.set_state(Create.winners)
    if data["kind"] == "battle":
        txt = "🏆 Nechta o'rin g'olib bo'lsin? (eng ko'p ovoz to'plagan top-N, masalan <code>5</code>)"
    else:
        txt = "🏆 Nechta g'olib bo'lsin? (raqam yuboring, masalan <code>3</code>)"
    await m.answer(txt, reply_markup=cancel_kb())


@router.message(Create.winners, F.text)
async def got_winners(m: Message, state: FSMContext):
    if not m.text.isdigit() or not (1 <= int(m.text) <= 100):
        await m.answer("1 dan 100 gacha raqam yuboring.")
        return
    data = await state.get_data()
    await db_exec("UPDATE events SET winners=? WHERE id=?", (int(m.text), data["event_id"]))
    if data["kind"] == "battle":
        await state.set_state(Create.minvotes)
        await m.answer(
            "Har bir o'rin uchun minimal ovozni vergul bilan yuboring.\n"
            "Misol: <code>99,50,25</code> (1-o'rin min 99, 2-o'rin min 50, 3-o'rin min 25)\n"
            "Kerak bo'lmasa «Yo'q» ni bosing.",
            reply_markup=skip_kb(NO_MIN),
        )
    else:
        await ask_ends(m, state)


@router.message(Create.minvotes, F.text)
async def got_minvotes(m: Message, state: FSMContext):
    t = m.text.strip()
    mins = ""
    if not is_txt(t, NO_MIN):
        parts = [p for p in t.replace(" ", "").split(",") if p]
        if not parts or not all(p.isdigit() for p in parts):
            await m.answer("Format: <code>99,50,25</code> yoki «Yo'q».")
            return
        mins = ",".join(parts)
    data = await state.get_data()
    await db_exec("UPDATE events SET min_votes=? WHERE id=?", (mins, data["event_id"]))
    await ask_ends(m, state)


async def ask_ends(m: Message, state: FSMContext):
    await state.set_state(Create.ends)
    now = datetime.now(TZ) + timedelta(days=1)
    await m.answer(
        "⏰ Tugash vaqtini yuboring (O'zbekiston vaqti):\n"
        f"<code>{now.strftime('%d.%m.%Y %H:%M')}</code>\n\n"
        "Yoki «Qo'lda yakunlayman» ni bosing.",
        reply_markup=skip_kb(MANUAL),
    )


@router.message(Create.ends, F.text)
async def got_ends(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    eid = data["event_id"]
    ends_at = None
    if not is_txt(m.text, MANUAL):
        ends_at = parse_time(m.text)
        if not ends_at or ends_at <= time.time() + 60:
            await m.answer("Format: <code>25.11.2026 20:00</code> (kelajakdagi vaqt bo'lsin).")
            return
    await db_exec("UPDATE events SET ends_at=?, status='active' WHERE id=?", (ends_at, eid))
    await state.clear()
    ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))

    posted = ""
    if ev["channel"]:
        try:
            msg = await send_post(bot, ev["channel"], ev, await channel_kb(ev))
            await db_exec("UPDATE events SET channel_msg_id=? WHERE id=?", (msg.message_id, eid))
            ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
            posted = f"\n{e('channel')} Post {ev['channel']} kanaliga yuborildi."
        except Exception:
            posted = "\n⚠️ Kanalga yuborib bo'lmadi (bot adminligini tekshiring)."
    who = "Ishtirokchilar uchun havola" if ev["kind"] == "battle" else "Qatnashish havolasi"
    await m.answer(
        f"{e('done')} <b>Tayyor!</b>{posted}\n\n{who}:\n<code>{share_link(eid)}</code>",
        reply_markup=menu_kb(m.from_user.id),
    )
    await send_post(bot, m.chat.id, ev, await event_kb(ev))


# ----------------------------------------------------------------------------
# Qatnashish (battle ishtirokchisi / konkurs), ovoz berish (kanalda)
# ----------------------------------------------------------------------------
def verify_kb(uid: int | None = None) -> InlineKeyboardMarkup:
    url = antimulti.WEBAPP_URL
    if uid and LANG.get(uid) == "ru":
        url += ("&" if "?" in url else "?") + "l=ru"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qurilmani tasdiqlash", web_app=WebAppInfo(url=url))]])


async def send_verify(bot: Bot, user_id: int) -> bool:
    try:
        await bot.send_message(
            user_id,
            "Ovoz berish / qatnashish uchun avval qurilmangizni tasdiqlang.\n"
            "Pastdagi tugmani bosing, keyin kanalga qaytib, tugmani qayta bosing.",
            reply_markup=verify_kb(user_id))
        return True
    except Exception:
        return False


async def require_device(c: CallbackQuery, bot: Bot) -> bool:
    """Mini App orqali qurilma tekshiruvidan o'tmagan bo'lsa, to'xtatadi."""
    if not antimulti.WEBAPP_URL:          # Mini App sozlanmagan bo'lsa, tekshiruv o'chiq
        return True
    if await antimulti.is_verified(c.from_user.id):
        return True
    if await send_verify(bot, c.from_user.id):
        await c.answer("Botga o'ting va qurilmani tasdiqlang, so'ng qayta bosing.", show_alert=True)
    else:
        await c.answer(url=f"https://t.me/{BOT_USERNAME}?start=verify")
    return False


async def check_common(c: CallbackQuery, bot: Bot, ev, already: str) -> bool:
    if not ev or ev["status"] != "active":
        await c.answer("Bu tadbir yakunlangan.", show_alert=True)
        return False
    if ev["channel"] and not await is_subscribed(bot, ev["channel"], c.from_user.id):
        await c.answer(f"Avval {ev['channel']} kanaliga obuna bo'ling, so'ng qayta bosing.",
                       show_alert=True)
        return False
    if already:
        await c.answer(already, show_alert=True)
        return False
    if not await require_device(c, bot):
        return False
    return True


@router.callback_query(F.data.startswith("vote:"))
async def vote(c: CallbackQuery, bot: Bot):
    """Kanaldagi ishtirokchi tugmasi bosilganda."""
    _, eid, cand = c.data.split(":")
    eid, cand = int(eid), int(cand)
    ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
    await ensure_user(c)
    already = None
    if await db_one("SELECT 1 FROM actions WHERE event_id=? AND user_id=?", (eid, c.from_user.id)):
        already = "Siz allaqachon ovoz bergansiz."
    if ev and cand == c.from_user.id:
        already = "O'zingizga ovoz bera olmaysiz."
    if not await check_common(c, bot, ev, already):
        return
    if not await db_one("SELECT 1 FROM participants WHERE event_id=? AND user_id=?", (eid, cand)):
        await c.answer("Ishtirokchi topilmadi.", show_alert=True)
        return
    await db_exec("INSERT INTO actions(event_id, user_id, option_id) VALUES(?,?,?)",
                  (eid, c.from_user.id, cand))
    await db_exec("UPDATE events SET dirty=1 WHERE id=?", (eid,))
    await c.answer("Ovozingiz qabul qilindi ✅")


@router.callback_query(F.data.startswith("join:"))
async def join_battle(c: CallbackQuery, bot: Bot):
    """Botdagi 'Qatnashish' tugmasi: battle ishtirokchisi bo'lish."""
    eid = int(c.data.split(":")[1])
    ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
    await ensure_user(c)
    already = None
    if await db_one("SELECT 1 FROM participants WHERE event_id=? AND user_id=?", (eid, c.from_user.id)):
        already = "Siz allaqachon qatnashyapsiz."
    if not await check_common(c, bot, ev, already):
        return
    if not c.from_user.username:
        await c.answer("Qatnashish uchun Telegram sozlamalarida username o'rnating, keyin qayta bosing.",
                       show_alert=True)
        return
    await db_exec("INSERT INTO participants(event_id, user_id) VALUES(?,?)", (eid, c.from_user.id))
    await db_exec("UPDATE events SET dirty=1 WHERE id=?", (eid,))
    await c.answer("Siz battlega qo'shildingiz ✅")
    link = post_link(ev)
    txt = f"{e('joined_ok')} Siz «{html.escape(ev['title'])}» battlega qo'shildingiz!"
    if link:
        txt += f"\n\nOvoz to'plash uchun shu postni do'stlaringizga yuboring:\n{link}"
    try:
        await bot.send_message(c.from_user.id, txt)
    except Exception:
        pass
    try:
        await c.message.edit_reply_markup(reply_markup=await event_kb(ev))
    except Exception:
        pass


async def send_boost_offer(bot: Bot, user_id: int, ev):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ik_button("boost", "Kanalga boost berish", "success", url=boost_url(ev["channel"]))],
        [InlineKeyboardButton(text="Boost berdim, tekshirish", callback_data=f"boostchk:{ev['id']}")],
    ])
    try:
        await bot.send_message(
            user_id,
            f"{e('joined_ok')} Siz konkursga qatnashdingiz!\n\n"
            f"{e('boost')} Sizda Telegram Premium bor-ku! "
            f"<b>{html.escape(ev['channel'])}</b> kanaliga boost bering, "
            "shunda yutish imkoniyatingiz <b>30% ga</b> oshadi.",
            reply_markup=kb,
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("act:"))
async def act(c: CallbackQuery, bot: Bot):
    """Konkursga qatnashish."""
    ev = await db_one("SELECT * FROM events WHERE id=?", (int(c.data.split(":")[1]),))
    await ensure_user(c)
    already = None
    if ev and await db_one("SELECT 1 FROM actions WHERE event_id=? AND user_id=?", (ev["id"], c.from_user.id)):
        already = "Siz allaqachon qatnashgansiz."
    if not await check_common(c, bot, ev, already):
        return
    await db_exec("INSERT INTO actions(event_id, user_id) VALUES(?,?)", (ev["id"], c.from_user.id))
    await db_exec("UPDATE events SET dirty=1 WHERE id=?", (ev["id"],))
    await c.answer("Siz qatnashdingiz ✅")
    try:
        await c.message.edit_reply_markup(reply_markup=await event_kb(ev))
    except Exception:
        pass
    if ev["channel"] and c.from_user.is_premium:
        await send_boost_offer(bot, c.from_user.id, ev)
    try:
        await check_multi(bot, ev, c.from_user.id)
    except Exception:
        logging.exception("multi-akkaunt tekshiruvi xatosi")


@router.callback_query(F.data.startswith("boostchk:"))
async def boost_check(c: CallbackQuery, bot: Bot):
    ev = await db_one("SELECT * FROM events WHERE id=?", (int(c.data.split(":")[1]),))
    if not ev or not ev["channel"]:
        await c.answer("Topilmadi.", show_alert=True)
        return
    if await has_boost(bot, ev["channel"], c.from_user.id):
        await c.answer("Boost topildi! Yutish imkoniyatingiz 30% ga oshdi ✅", show_alert=True)
    else:
        await c.answer("Boost topilmadi. Avval kanalga boost bering, keyin qayta tekshiring.",
                       show_alert=True)


# ----------------------------------------------------------------------------
# Multi-akkaunt aniqlash (TAXMINIY: Telegram qurilmani bermaydi)
# Belgilar: akkaunt ID yaqinligi (bir vaqtda ochilgan), qatnashish vaqti,
# ism/username o'xshashligi, til kodi.
# ----------------------------------------------------------------------------
MULTI_MIN_GROUP = 3          # nechta akkaunt bo'lsa xabar yuboriladi (3 va undan ko'p)
MULTI_LINK_SCORE = 5         # ikki akkaunt bog'langan deb hisoblanishi uchun ball
MULTI_ID_NEAR = 200_000      # ID farqi shundan kam bo'lsa ~ bir necha soat ichida ochilgan
MULTI_ID_FAR = 3_000_000     # shundan katta farq bo'lsa umuman bog'lanmaydi (~1 kundan ortiq)
MULTI_CHAIN_GAP = 90         # ketma-ket qatnashishlar orasidagi eng katta vaqt (soniya)
MULTI_CHAIN_MAX = 6          # zanjirda shundan ko'p odam bo'lsa, oddiy olomon deb hisoblanadi


def _base(s: str | None) -> str:
    """Ism/username'dan raqam, emoji, bo'shliqlarni olib tashlaydi."""
    return re.sub(r"[^a-zа-яёўқғҳ']+", "", (s or "").lower())


def _ts(s: str) -> float:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _similar(a: str, b: str) -> bool:
    return bool(a) and bool(b) and len(a) >= 3 and len(b) >= 3 and \
        difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def pair_score(a: dict, b: dict) -> int:
    di = abs(a["id"] - b["id"])
    if di > MULTI_ID_FAR:
        return 0
    score = 3 if di <= MULTI_ID_NEAR else 1
    dt = abs(a["ts"] - b["ts"])
    score += 2 if dt <= 120 else (1 if dt <= 600 else 0)
    if _similar(a["name"], b["name"]) or _similar(a["uname"], b["uname"]):
        score += 2
    if a["lang"] and a["lang"] == b["lang"]:
        score += 1
    return score


def chain_groups(rows: list[dict]) -> list[list[dict]]:
    """Ketma-ket, qisqa vaqt oralig'ida qatnashgan 3..MULTI_CHAIN_MAX ta akkauntni topadi.
    Bitta qurilmada akkauntlarni almashtirib kirgan odamni ID/ismidan qat'i nazar ushlaydi."""
    rows = sorted((r for r in rows if r["ts"]), key=lambda r: r["ts"])
    out, cur = [], []
    for r in rows:
        if cur and r["ts"] - cur[-1]["ts"] > MULTI_CHAIN_GAP:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return [g for g in out if MULTI_MIN_GROUP <= len(g) <= MULTI_CHAIN_MAX]


async def _multi_rows(event_id: int) -> list[dict]:
    rows = await db_all(
        """SELECT a.user_id, a.created_at, u.username, u.full_name, u.tg_lang
           FROM actions a LEFT JOIN users u ON u.id=a.user_id
           WHERE a.event_id=? ORDER BY a.created_at DESC LIMIT 5000""", (event_id,))
    return [{"id": r["user_id"], "ts": _ts(r["created_at"]), "username": r["username"],
             "full_name": r["full_name"], "name": _base(r["full_name"]),
             "uname": _base(r["username"]), "lang": r["tg_lang"]} for r in rows]


def acc_line(r: dict) -> str:
    """Username bo'lsa @username, bo'lmasa profilga o'tadigan havola."""
    if r["username"]:
        who = f'@{html.escape(r["username"])}'
    else:
        who = mention(r["id"], r["full_name"])
    return f'{who} — <code>{r["id"]}</code>'


def multi_text(ev, group: list[dict]) -> str:
    lines = "\n".join(f"{i}. {acc_line(r)}" for i, r in enumerate(group, 1))
    return (f"⚠️ <b>Konkursda multi-akkaunt aniqlandi</b>\n"
            f"Konkurs: <b>{html.escape(ev['title'])}</b>\n"
            f"Bitta qurilmadan bo'lishi mumkin bo'lgan akkauntlar: <b>{len(group)}</b> ta\n\n"
            f"{lines}\n\n<i>Bu taxminiy natija, qo'lda tekshirib ko'ring.</i>")


async def check_multi(bot: Bot, ev, uid: int):
    """Yangi qatnashchi boshqalar bilan guruh hosil qilsa, adminga xabar beradi."""
    rows = await _multi_rows(ev["id"])
    me = next((r for r in rows if r["id"] == uid), None)
    if not me:
        return
    group = next((g for g in chain_groups(rows) if any(r["id"] == uid for r in g)), None)
    if group is None:
        linked = [r for r in rows if r["id"] != uid and pair_score(me, r) >= MULTI_LINK_SCORE]
        group = [me] + linked
    if len(group) < MULTI_MIN_GROUP:
        return
    text = multi_text(ev, group)
    for chat in {ADMIN_ID, ev["owner_id"]} - {0, None}:
        try:
            await bot.send_message(chat, text, disable_web_page_preview=True)
        except Exception:
            pass


def find_groups(rows: list[dict]) -> list[list[dict]]:
    """Barcha qatnashchilar ichidan guruhlarni topadi (ID bo'yicha qo'shnilarni solishtiradi)."""
    rows = sorted(rows, key=lambda r: r["id"])
    parent = list(range(len(rows)))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(rows)):
        j = i + 1
        while j < len(rows) and rows[j]["id"] - rows[i]["id"] <= MULTI_ID_FAR:
            if pair_score(rows[i], rows[j]) >= MULTI_LINK_SCORE:
                parent[root(i)] = root(j)
            j += 1
    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(root(i), []).append(r)
    result = [g for g in groups.values() if len(g) >= MULTI_MIN_GROUP]
    seen = [{r["id"] for r in g} for g in result]
    for g in chain_groups(rows):
        ids = {r["id"] for r in g}
        if not any(ids <= s for s in seen):
            result.append(g)
            seen.append(ids)
    return result


@router.message(Command("multi"))
async def cmd_multi(m: Message, command: CommandObject):
    """/multi 12  -> 12-battle/konkursdagi shubhali akkauntlar guruhlari."""
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await m.answer("Ishlatish: <code>/multi 12</code>  (12 o'rniga konkurs raqami)")
        return
    ev = await db_one("SELECT * FROM events WHERE id=?", (int(arg),))
    if not ev or m.from_user.id not in (ADMIN_ID, ev["owner_id"]):
        await m.answer("Topilmadi.")
        return
    groups = find_groups(await _multi_rows(ev["id"]))
    if not groups:
        await m.answer("Shubhali akkauntlar guruhi topilmadi ✅")
        return
    for g in groups:
        await m.answer(multi_text(ev, g), disable_web_page_preview=True)


# ----------------------------------------------------------------------------
# Yakunlash (qo'lda yoki vaqt tugaganda)
# ----------------------------------------------------------------------------
async def finalize(bot: Bot, eid: int):
    changed = await db_run("UPDATE events SET status='finished' WHERE id=? AND status='active'", (eid,))
    if not changed:
        return
    ev = await db_one("SELECT * FROM events WHERE id=?", (eid,))
    if ev["kind"] == "battle":
        await finish_battle(bot, ev)
    else:
        await finish_konkurs(bot, ev)
    await refresh_channel_post(bot, ev)   # tugmalar yakuniy holatga keladi


async def purge_left_voters(bot: Bot, ev) -> int:
    """Kanaldan chiqib ketganlarning ovozini bekor qiladi."""
    if not ev["channel"]:
        return 0
    voters = await db_all("SELECT DISTINCT user_id FROM actions WHERE event_id=?", (ev["id"],))
    removed = 0
    for v in voters:
        left = False
        try:
            mem = await bot.get_chat_member(ev["channel"], v["user_id"])
            left = mem.status in ("left", "kicked")
        except TelegramRetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 1)
        except Exception:
            pass
        if left:
            removed += await db_run("DELETE FROM actions WHERE event_id=? AND user_id=?",
                                    (ev["id"], v["user_id"]))
        await asyncio.sleep(0.05)
    return removed


async def send_result(bot: Bot, chat_id, text: str, card: bytes | None):
    """Natijani rasm bilan yuboradi (rasm yasalmasa - oddiy matn)."""
    if card:
        try:
            if len(text) <= 1000:
                await bot.send_photo(chat_id, BufferedInputFile(card, filename="natija.png"), caption=text)
                return
            await bot.send_photo(chat_id, BufferedInputFile(card, filename="natija.png"))
        except Exception:
            logging.exception("natija rasmi yuborilmadi")
    await bot.send_message(chat_id, text)


async def finish_battle(bot: Bot, ev):
    removed = await purge_left_voters(bot, ev)
    rows = await participants_rows(ev["id"], 1000)
    total = await count_actions(ev["id"])
    head = f"{e('finish')} <b>{html.escape(ev['title'])}</b> yakunlandi\n\n"
    if not rows:
        text = head + "Hech kim qatnashmadi."
        if ev["channel"]:
            try:
                await bot.send_message(ev["channel"], text)
            except Exception:
                pass
        await bot.send_message(ev["owner_id"], text)
        return

    mins = get_mins(ev)
    lines = []
    for i, r in enumerate(rows[: ev["winners"] or 1], 1):
        need = mins[i - 1] if i - 1 < len(mins) else 0
        line = f"{i}. {html.escape(person(r))} - <b>{r['c']}</b> ovoz"
        if need:
            line += f" (min {need}) " + ("✅" if r["c"] >= need else "❌ minimal ovoz yetmadi")
        lines.append(line)
    text = (head + f"Ishtirokchilar: <b>{len(rows)}</b>\nJami ovozlar: <b>{total}</b>\n")
    if removed:
        text += f"🛑 Kanaldan chiqib ketgani uchun bekor qilingan ovozlar: <b>{removed}</b>\n"
    text += f"\n{e('winner')} <b>Natijalar:</b>\n" + "\n".join(lines)
    card_ch = card_own = None
    try:
        from resultcard import make_card
        own_lang = LANG.get(ev["owner_id"], "uz")
        wl = [(person(r), r["c"]) for r in rows[: ev["winners"] or 1]]
        ttl = (ev["channel"] or "BATTLE") if ev["auto"] else ev["title"]
        foot = f"@{BOT_USERNAME}" if BOT_USERNAME else ""
        card_ch = await asyncio.to_thread(make_card, ttl, wl, len(rows), total, "uz", foot)
        card_own = card_ch if own_lang == "uz" else await asyncio.to_thread(
            make_card, ttl, wl, len(rows), total, own_lang, foot)
    except Exception:
        logging.exception("natija rasmi")
    if ev["channel"]:
        try:
            await send_result(bot, ev["channel"], text, card_ch)
        except Exception:
            pass
    await send_result(bot, ev["owner_id"], text, card_own)

    # Battle egasiga: kim kimga ovoz bergani
    votes = await db_all(
        """SELECT a.user_id, a.option_id, u.full_name, u.username,
                  cu.username AS cu_username, cu.full_name AS cu_name
           FROM actions a
           LEFT JOIN users u  ON u.id=a.user_id
           LEFT JOIN users cu ON cu.id=a.option_id
           WHERE a.event_id=? ORDER BY a.created_at""",
        (ev["id"],),
    )
    if votes:
        plain = []
        for i, v in enumerate(votes, 1):
            voter = v["full_name"] or str(v["user_id"])
            if v["username"]:
                voter += f" @{v['username']}"
            cand = f"@{v['cu_username']}" if v["cu_username"] else (v["cu_name"] or str(v["option_id"]))
            plain.append(f"{i}. {voter} (ID {v['user_id']}) -> {cand}")
        body = "\n".join(plain)
        if len(body) < 3500:
            await bot.send_message(ev["owner_id"],
                                   "🗳 <b>Kim kimga ovoz berdi:</b>\n\n" + html.escape(body))
        else:
            await bot.send_document(
                ev["owner_id"],
                BufferedInputFile(body.encode("utf-8"), filename=f"battle_{ev['id']}_ovozlar.txt"),
                caption="🗳 Kim kimga ovoz berdi",
            )


async def finish_konkurs(bot: Bot, ev):
    rows = await db_all(
        """SELECT a.user_id, u.full_name FROM actions a
           LEFT JOIN users u ON u.id=a.user_id WHERE a.event_id=?""",
        (ev["id"],),
    )
    head = f"{e('finish')} <b>{html.escape(ev['title'])}</b> yakunlandi\n\n"
    if not rows:
        text = head + "Hech kim qatnashmadi."
        if ev["channel"]:
            try:
                await bot.send_message(ev["channel"], text)
            except Exception:
                pass
        await bot.send_message(ev["owner_id"], text)
        return

    pool = []
    boosters = 0
    for r in rows:
        boosted = bool(ev["channel"]) and await has_boost(bot, ev["channel"], r["user_id"])
        boosters += 1 if boosted else 0
        pool.append((r, BOOST_BONUS if boosted else 1.0))
        await asyncio.sleep(0.05)

    winners = []
    for _ in range(min(ev["winners"] or 1, len(pool))):
        idx = random.choices(range(len(pool)), weights=[w for _, w in pool])[0]
        winners.append(pool.pop(idx)[0])

    wl = "\n".join(f"{i}. {mention(w['user_id'], w['full_name'])}" for i, w in enumerate(winners, 1))
    text = (head + f"Qatnashchilar: <b>{len(rows)}</b>\n"
            f"Boost berganlar: <b>{boosters}</b>\n\n"
            f"{e('winner')} <b>G'oliblar:</b>\n{wl}")
    if ev["channel"]:
        try:
            await bot.send_message(ev["channel"], text)
        except Exception:
            pass
    await bot.send_message(ev["owner_id"], text)
    for w in winners:
        try:
            await bot.send_message(
                w["user_id"],
                f"{e('winner')} Tabriklaymiz! Siz «{html.escape(ev['title'])}» konkursida g'olib bo'ldingiz!")
        except Exception:
            pass


async def watcher(bot: Bot):
    """Vaqti tugaganlarni yakunlaydi, kanal postidagi tugmalarni yangilab turadi."""
    while True:
        try:
            rows = await db_all(
                "SELECT id FROM events WHERE status='active' AND ends_at IS NOT NULL AND ends_at<=?",
                (int(time.time()),),
            )
            for r in rows:
                await finalize(bot, r["id"])

            dirty = await db_all("SELECT id FROM events WHERE status='active' AND dirty=1")
            for r in dirty:
                await db_run("UPDATE events SET dirty=0 WHERE id=?", (r["id"],))
                ev = await db_one("SELECT * FROM events WHERE id=?", (r["id"],))
                await refresh_channel_post(bot, ev)
                await asyncio.sleep(1)
        except Exception:
            logging.exception("watcher xatosi")
        await asyncio.sleep(10)


# ----------------------------------------------------------------------------
# Mening battlelarim / konkurslarim
# ----------------------------------------------------------------------------
async def show_my(m: Message, kind: str):
    rows = await db_all(
        "SELECT * FROM events WHERE owner_id=? AND kind=? AND status!='draft' "
        "ORDER BY id DESC LIMIT 20",
        (m.from_user.id, kind),
    )
    if not rows:
        what = "battle" if kind == "battle" else "konkurs"
        await m.answer(f"Sizda hozircha {what} yo'q.\n\n«{what.capitalize()} yaratish» "
                       "tugmasi orqali yangisini yarating.")
        return
    buttons = []
    for r in rows:
        n = await event_count(r)
        mark = "🟢" if r["status"] == "active" else "⚫"
        buttons.append([InlineKeyboardButton(text=f"{mark} {r['title']} ({n})",
                                             callback_data=f"ev:{r['id']}")])
    await m.answer("Tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(is_btn("my_battles"))
async def my_battles(m: Message, state: FSMContext):
    await state.clear()
    await show_my(m, "battle")


@router.message(is_btn("my_konkurs"))
async def my_konkurs(m: Message, state: FSMContext):
    await state.clear()
    await show_my(m, "konkurs")


@router.callback_query(F.data.startswith("ev:"))
async def open_event(c: CallbackQuery, bot: Bot):
    ev = await db_one("SELECT * FROM events WHERE id=?", (int(c.data[3:]),))
    if not ev or ev["owner_id"] != c.from_user.id:
        await c.answer("Topilmadi.", show_alert=True)
        return
    n = await event_count(ev)
    status = "faol" if ev["status"] == "active" else "yakunlangan"
    if ev["kind"] == "battle":
        info = (f"<b>{html.escape(ev['title'])}</b>\nIshtirokchilar: <b>{n}</b>, "
                f"ovozlar: <b>{await count_actions(ev['id'])}</b>\nHolati: {status}\n")
        top = await participants_rows(ev["id"], 10)
        if top:
            info += "\n" + "\n".join(
                f"{i}. {html.escape(person(r))} - {r['c']}" for i, r in enumerate(top, 1)) + "\n"
    else:
        info = (f"<b>{html.escape(ev['title'])}</b>\nQatnashchilar: <b>{n}</b>\nHolati: {status}\n")
    info += f"\nHavola: <code>{share_link(ev['id'])}</code>"
    rows = []
    if ev["status"] == "active":
        rows.append([InlineKeyboardButton(text="🏁 Hozir yakunlash", callback_data=f"fin:{ev['id']}")])
    await c.message.answer(info, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await send_post(bot, c.message.chat.id, ev, await event_kb(ev))
    await c.answer()


@router.callback_query(F.data.startswith("fin:"))
async def finish_cb(c: CallbackQuery, bot: Bot):
    ev = await db_one("SELECT * FROM events WHERE id=?", (int(c.data[4:]),))
    if not ev or ev["owner_id"] != c.from_user.id or ev["status"] != "active":
        await c.answer("Bajarib bo'lmadi.", show_alert=True)
        return
    await c.answer("Yakunlanmoqda...")
    await finalize(bot, ev["id"])
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Profil
# ----------------------------------------------------------------------------
@router.message(is_btn("profile"))
async def profile(m: Message, state: FSMContext):
    await state.clear()
    await upsert_user(m)
    uid = m.from_user.id
    u = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    created = (await db_one("SELECT COUNT(*) c FROM events WHERE owner_id=? AND kind='battle' "
                            "AND status!='draft'", (uid,)))["c"]
    joined = (await db_one("SELECT COUNT(*) c FROM participants WHERE user_id=?", (uid,)))["c"]
    given = (await db_one("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                          "WHERE a.user_id=? AND e.kind='battle'", (uid,)))["c"]
    received = (await db_one("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                             "WHERE e.kind='battle' AND a.option_id=?", (uid,)))["c"]
    points = received * 2 + given + joined  # ball formulasini xohlaganingizcha o'zgartiring
    lang = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}.get(u["lang"], u["lang"])
    uname = f"@{u['username']}" if u["username"] else "—"
    await m.answer(
        f"{e('profile_title')} <b>Mening profilim</b>\n\n"
        f"{e('id')} ID: <code>{uid}</code>\n"
        f"{e('name')} Ism: {html.escape(u['full_name'] or '')}\n"
        f"{e('username')} Username: {uname}\n"
        f"{e('language')} Til: {lang}\n"
        f"{e('date')} Ro'yxatdan o'tgan: {u['joined_at']}\n\n"
        f"{e('created')} Yaratgan battlelar: {created}\n"
        f"{e('joined')} Qatnashgan battlelar: {joined}\n"
        f"{e('given')} Bergan ovozlar: {given}\n"
        f"{e('received')} Olgan ovozlar: {received}\n"
        f"{e('points')} Ballar: {points}"
    )


# ----------------------------------------------------------------------------
# Til, Qo'llanma, Murojaat
# ----------------------------------------------------------------------------
@router.message(is_btn("lang"))
async def choose_lang(m: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
    ])
    await m.answer(f"{e('lang')} Tilni tanlang / Выберите язык:", reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def set_lang(c: CallbackQuery):
    lang = c.data[5:] if c.data[5:] in ("uz", "ru") else "uz"
    await db_exec("UPDATE users SET lang=? WHERE id=?", (lang, c.from_user.id))
    if lang == "ru":
        LANG[c.from_user.id] = "ru"
    else:
        LANG.pop(c.from_user.id, None)
    _lang_ctx.set(lang)
    await c.answer("Saqlandi ✅")
    try:
        await c.message.delete()
    except Exception:
        pass
    # reply-tugmalar yangi tilda chiqishi uchun menyuni qayta yuboramiz
    await c.message.answer(f"{e('home')} <b>Bosh menyu</b>", reply_markup=menu_kb(c.from_user.id))


@router.message(is_btn("guide"))
async def guide(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        f"{e('guide')} <b>Qo'llanma</b>\n\n"
        "<b>Battle:</b> post kanalga chiqadi. Ishtirokchilar bot havolasi orqali qo'shiladi "
        "(usernamesi bo'lishi shart), ularning tugmalari postda paydo bo'ladi. "
        "Odamlar kanalning o'zida tugmani bosib ovoz beradi. Tugagach top-N g'olib "
        "e'lon qilinadi, sizga esa kim kimga ovoz bergani yuboriladi.\n\n"
        "<b>Konkurs:</b> postdagi «Qatnashish» tugmasi botga o'tkazadi. Tugagach bot g'oliblarni "
        "tasodifiy tanlaydi. Kanalga boost bergan ishtirokchining yutish imkoni 30% ga oshadi.\n\n"
        "Bot kanalda admin bo'lishi shart."
    )


@router.message(is_btn("support"))
async def support_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Support.msg)
    await m.answer(f"{e('support')} Murojaatingizni yozing:", reply_markup=cancel_kb())


@router.message(Support.msg)
async def support_send(m: Message, state: FSMContext, bot: Bot):
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"📩 Murojaat: {html.escape(m.from_user.full_name)} "
            f"(@{m.from_user.username or '—'}, <code>{m.from_user.id}</code>)",
        )
        await m.copy_to(ADMIN_ID)
    await state.clear()
    await m.answer("Yuborildi ✅ Tez orada javob beramiz.", reply_markup=menu_kb(m.from_user.id))


# ----------------------------------------------------------------------------
# ADMIN PANEL (/admin yoki «Admin panel» tugmasi) - faqat ADMIN_ID uchun
# ----------------------------------------------------------------------------
admin_router = Router()
def _staff(event) -> bool:
    return bool(event.from_user) and is_staff(event.from_user.id)


admin_router.message.filter(_staff)
admin_router.callback_query.filter(_staff)

PAGE = 10
ORDER_NEW = "substr(joined_at,7,4)||substr(joined_at,4,2)||substr(joined_at,1,2) DESC, id DESC"
_tasks: set = set()


class Admin(StatesGroup):
    search = State()
    add_channel = State()
    bc_msg = State()
    bc_confirm = State()


def _not_cmd(m: Message) -> bool:
    return not (m.text and m.text.startswith("/"))


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


BACK = _btn("◀️ Orqaga", "adm:home")


def kb_of(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


async def adm_show(target, text: str, kb: InlineKeyboardMarkup | None = None):
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as ex:
            if "not modified" not in str(ex):
                await target.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        try:
            await target.answer()
        except Exception:
            pass
    else:
        await target.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def _count(sql: str, args=()) -> int:
    return (await db_one(sql, args))["c"]


async def admin_home_text() -> str:
    users = await _count("SELECT COUNT(*) c FROM users")
    battles = await _count("SELECT COUNT(*) c FROM events WHERE kind='battle' AND status='active'")
    konk = await _count("SELECT COUNT(*) c FROM events WHERE kind='konkurs' AND status='active'")
    chs = await _count("SELECT COUNT(*) c FROM req_channels")
    return (f"⚙️ <b>Admin panel</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{users}</b>\n"
            f"🥊 Faol battlelar: <b>{battles}</b>\n"
            f"🎁 Faol konkurslar: <b>{konk}</b>\n"
            f"📢 Majburiy kanallar: <b>{chs}</b>")


def admin_kb(uid: int) -> InlineKeyboardMarkup:
    pm = perms_of(uid)
    rows, r = [], []
    if "users" in pm:
        r += [_btn("👥 Foydalanuvchilar", "adm:users:0"), _btn("🔎 ID orqali qidirish", "adm:search")]
    if r:
        rows.append(r)
    r = []
    if "channels" in pm:
        r.append(_btn("📢 Majburiy kanallar", "adm:ch"))
    if "broadcast" in pm:
        r.append(_btn("✉️ Xabar yuborish", "adm:bc"))
    if r:
        rows.append(r)
    if uid == ADMIN_ID:
        rows.append([_btn("📜 Jurnal", "adm:log:0")])
    rows.append([InlineKeyboardButton(text="🌐 Web panel",
                                      web_app=WebAppInfo(url=antimulti.WEBAPP_URL.rstrip("/") + "/admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.message(Command("admin"))
@admin_router.message(is_btn("admin"))
async def adm_open(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(await admin_home_text(), reply_markup=admin_kb(m.from_user.id))


@admin_router.message(Command("cancel"), StateFilter(Admin))
async def adm_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(await admin_home_text(), reply_markup=admin_kb(m.from_user.id))


@admin_router.callback_query(F.data == "adm:home")
async def adm_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await adm_show(c, await admin_home_text(), admin_kb(c.from_user.id))


# ---- Foydalanuvchilar ------------------------------------------------------
def _uname(u) -> str:
    return (u["full_name"] or (f"@{u['username']}" if u["username"] else str(u["id"])))[:28]


@admin_router.callback_query(F.data.startswith("adm:users:"))
async def adm_users(c: CallbackQuery, state: FSMContext):
    await state.clear()
    page = max(0, int(c.data.split(":")[2]))
    total = await _count("SELECT COUNT(*) c FROM users")
    today = await _count("SELECT COUNT(*) c FROM users WHERE joined_at=strftime('%d.%m.%Y','now')")
    rows = await db_all(f"SELECT * FROM users ORDER BY {ORDER_NEW} LIMIT ? OFFSET ?",
                        (PAGE, page * PAGE))
    pages = max(1, (total + PAGE - 1) // PAGE)
    kb = [[_btn(f"👤 {_uname(u)} · {u['id']}", f"adm:u:{u['id']}")] for u in rows]
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"adm:users:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{pages}", "adm:noop"))
    if (page + 1) * PAGE < total:
        nav.append(_btn("▶️", f"adm:users:{page + 1}"))
    kb.append(nav)
    kb.append([_btn("📄 Ro'yxatni yuklab olish", "adm:export"), BACK])
    await adm_show(c, f"👥 <b>Foydalanuvchilar</b>\n\nJami: <b>{total}</b>\nBugun qo'shilgan: <b>{today}</b>\n\n"
                      "Ko'rish uchun foydalanuvchini tanlang:", InlineKeyboardMarkup(inline_keyboard=kb))


@admin_router.callback_query(F.data == "adm:noop")
async def adm_noop(c: CallbackQuery):
    await c.answer()


@admin_router.callback_query(F.data == "adm:export")
async def adm_export(c: CallbackQuery, bot: Bot):
    rows = await db_all(f"SELECT id, username, full_name, lang, joined_at FROM users ORDER BY {ORDER_NEW}")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "username", "full_name", "lang", "joined_at"])
    for r in rows:
        w.writerow([r["id"], r["username"] or "", r["full_name"] or "", r["lang"], r["joined_at"]])
    await bot.send_document(c.from_user.id,
                            BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="users.csv"),
                            caption=f"👥 Jami: {len(rows)}")
    await log_action(c.from_user.id, "export", "users", str(len(rows)))
    await c.answer()


async def device_accounts(uid: int) -> list[int]:
    row = await db_one("SELECT did FROM devices WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,))
    if not row:
        return []
    rows = await db_all("SELECT DISTINCT user_id FROM devices WHERE did=?", (row["did"],))
    return [r["user_id"] for r in rows]


async def user_card(uid: int) -> str | None:
    u = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        return None
    created = await _count("SELECT COUNT(*) c FROM events WHERE owner_id=? AND status!='draft'", (uid,))
    joined = await _count("SELECT COUNT(*) c FROM participants WHERE user_id=?", (uid,))
    given = await _count("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                         "WHERE a.user_id=? AND e.kind='battle'", (uid,))
    received = await _count("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                            "WHERE e.kind='battle' AND a.option_id=?", (uid,))
    konk = await _count("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                        "WHERE a.user_id=? AND e.kind='konkurs'", (uid,))
    uname = f"@{html.escape(u['username'])}" if u["username"] else "—"
    text = (f"👤 <b>Foydalanuvchi</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"📛 Ism: {mention(uid, u['full_name'])}\n"
            f"🔗 Username: {uname}\n"
            f"🌐 Til: {html.escape(u['lang'] or '')}\n"
            f"📅 Ro'yxatdan o'tgan: {u['joined_at']}\n" + ("⛔ <b>Bloklangan</b>\n" if u["banned"] else "") + "\n"
            f"🧑‍💻 Yaratgan tadbirlar: {created}\n"
            f"🎯 Qatnashgan battlelar: {joined}\n"
            f"🗳 Bergan ovozlar: {given}\n"
            f"📥 Olgan ovozlar: {received}\n"
            f"🎁 Qatnashgan konkurslar: {konk}")
    dev = await device_accounts(uid)
    if dev:
        text += f"\n\n📱 Shu qurilmadagi akkauntlar: <b>{len(dev)}</b>"
        if len(dev) > 1:
            text += "\n" + ", ".join(f"<code>{x}</code>" for x in dev)
    return text


@admin_router.callback_query(F.data.startswith("adm:u:"))
async def adm_user(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    text = await user_card(uid)
    if not text:
        await c.answer("Topilmadi.", show_alert=True)
        return
    await adm_show(c, text, await user_kb(uid, c.from_user.id))


# ---- ID orqali qidirish ----------------------------------------------------
@admin_router.callback_query(F.data == "adm:search")
async def adm_search_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.search)
    await adm_show(c, "🔎 Foydalanuvchi <b>ID</b> raqamini yuboring.\n"
                      "<i>@username yoki ism bilan ham qidirsa bo'ladi.</i>", kb_of([BACK]))


@admin_router.message(Admin.search, F.text, _not_cmd)
async def adm_search(m: Message):
    q = m.text.strip()
    if q.isdigit():
        rows = await db_all("SELECT * FROM users WHERE id=?", (int(q),))
    else:
        like = f"%{q.lstrip('@').lower()}%"
        rows = await db_all("SELECT * FROM users WHERE lower(username) LIKE ? "
                            "OR lower(full_name) LIKE ? LIMIT 10", (like, like))
    if not rows:
        await m.answer("❌ Topilmadi. Boshqa ID yuboring.", reply_markup=kb_of([BACK]))
        return
    if len(rows) == 1:
        uid = rows[0]["id"]
        await m.answer(await user_card(uid), disable_web_page_preview=True,
                       reply_markup=kb_of([InlineKeyboardButton(text="💬 Profilga o'tish", url=f"tg://user?id={uid}")],
                                          [BACK]))
        return
    kb = [[_btn(f"👤 {_uname(u)} · {u['id']}", f"adm:u:{u['id']}")] for u in rows]
    kb.append([BACK])
    await m.answer(f"Topildi: <b>{len(rows)}</b> ta", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# ---- Majburiy kanallar -----------------------------------------------------
async def channels_view(c_or_m):
    chs = await req_channels()
    text = "📢 <b>Majburiy kanallar</b>\n\n"
    text += ("\n".join(f"{i}. {x['channel']}" for i, x in enumerate(chs, 1)) if chs
             else "Hozircha kanal yo'q.")
    text += "\n\nFoydalanuvchilar botdan foydalanish uchun shu kanallarga obuna bo'lishi shart."
    kb = [[_btn(f"🗑 {x['channel']}", f"adm:chdel:{x['id']}")] for x in chs]
    kb.append([_btn("➕ Kanal qo'shish", "adm:chadd")])
    kb.append([BACK])
    await adm_show(c_or_m, text, InlineKeyboardMarkup(inline_keyboard=kb))


@admin_router.callback_query(F.data == "adm:ch")
async def adm_channels(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await channels_view(c)


@admin_router.callback_query(F.data == "adm:chadd")
async def adm_ch_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.add_channel)
    await adm_show(c, "📢 Kanalni yuboring (masalan <code>@kanal</code>).\n"
                      "Bot shu kanalda admin bo'lishi kerak.", kb_of([_btn("◀️ Orqaga", "adm:ch")]))


@admin_router.message(Admin.add_channel, F.text, _not_cmd)
async def adm_ch_add_got(m: Message, state: FSMContext, bot: Bot):
    ok, channel, title, reason = await check_channel(bot, m.text, None)
    if not ok:
        await m.answer(fail_text(reason) + "\n\nBoshqa kanal yuboring.", reply_markup=kb_of([_btn("◀️ Orqaga", "adm:ch")]))
        return
    await add_req_channel(channel, title, m.from_user.id)
    await state.clear()
    await m.answer(f"✅ <b>Ulandi:</b> {channel}\nEndi foydalanuvchilar shu kanalga obuna bo'lishi shart.")
    await channels_view(m)


@admin_router.callback_query(F.data.startswith("adm:chdel:"))
async def adm_ch_del(c: CallbackQuery):
    await remove_req_channel(int(c.data.split(":")[2]), c.from_user.id)
    _sub_cache.clear()
    await channels_view(c)


# ---- Xabar yuborish --------------------------------------------------------
async def connected_channels() -> list[str]:
    rows = await db_all("SELECT channel FROM req_channels UNION "
                        "SELECT channel FROM events WHERE channel IS NOT NULL AND channel!=''")
    seen, out = set(), []
    for r in rows:
        ch = r["channel"]
        if ch and ch.lower() not in seen:
            seen.add(ch.lower())
            out.append(ch)
    return out


@admin_router.callback_query(F.data == "adm:bc")
async def adm_bc(c: CallbackQuery, state: FSMContext):
    await state.clear()
    nu = await _count("SELECT COUNT(*) c FROM users")
    nc = len(await connected_channels())
    await adm_show(c, "✉️ <b>Xabar yuborish</b>\n\nKimga yuboramiz?", kb_of(
        [_btn(f"👥 Foydalanuvchilarga ({nu})", "adm:bct:users")],
        [_btn(f"📢 Ulangan kanallarga ({nc})", "adm:bct:channels")],
        [_btn("👥📢 Ikkalasiga", "adm:bct:all")],
        [BACK]))


@admin_router.callback_query(F.data.startswith("adm:bct:"))
async def adm_bc_target(c: CallbackQuery, state: FSMContext):
    await state.set_state(Admin.bc_msg)
    await state.update_data(target=c.data.split(":")[2])
    await adm_show(c, "Yuboriladigan xabarni yuboring (matn, rasm, video, fayl...). "
                      "Qanday bo'lsa, shundayligicha ketadi.\n<i>Albom emas, bitta xabar.</i>",
                   kb_of([_btn("◀️ Orqaga", "adm:bc")]))


@admin_router.message(Admin.bc_msg, _not_cmd)
async def adm_bc_got(m: Message, state: FSMContext):
    if m.media_group_id:
        return
    data = await state.get_data()
    await state.update_data(bc_chat=m.chat.id, bc_mid=m.message_id)
    await state.set_state(Admin.bc_confirm)
    nu = await _count("SELECT COUNT(*) c FROM users")
    nc = len(await connected_channels())
    target = data.get("target")
    parts = []
    if target in ("users", "all"):
        parts.append(f"👥 {nu} ta foydalanuvchi")
    if target in ("channels", "all"):
        parts.append(f"📢 {nc} ta kanal")
    await m.copy_to(m.chat.id)
    await m.answer("Yuqoridagi xabar yuboriladi:\n" + "\n".join(parts) + "\n\nTasdiqlaysizmi?",
                   reply_markup=kb_of([_btn("✅ Yuborish", "adm:bcgo"), _btn("❌ Bekor qilish", "adm:home")]))


async def run_broadcast(bot: Bot, report_to: int, targets, from_chat: int, mid: int):
    stats = {"u": [0, 0], "c": [0, 0]}
    for kind, tid in targets:
        for attempt in (1, 2):
            try:
                await bot.copy_message(tid, from_chat, mid)
                stats[kind][0] += 1
                break
            except TelegramRetryAfter as ex:
                await asyncio.sleep(ex.retry_after + 1)
                if attempt == 2:
                    stats[kind][1] += 1
            except Exception:
                stats[kind][1] += 1
                break
        await asyncio.sleep(0.05)
    text = "✅ <b>Yuborish tugadi</b>\n"
    if targets and any(k == "u" for k, _ in targets):
        text += f"\n👥 Foydalanuvchilar: {stats['u'][0]} ta yetdi, {stats['u'][1]} ta yetmadi"
    if any(k == "c" for k, _ in targets):
        text += f"\n📢 Kanallar: {stats['c'][0]} ta yetdi, {stats['c'][1]} ta yetmadi"
    await bot.send_message(report_to, text, reply_markup=kb_of([BACK]))


@admin_router.callback_query(F.data == "adm:bcgo")
async def adm_bc_go(c: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    mid, chat, target = data.get("bc_mid"), data.get("bc_chat"), data.get("target")
    await state.clear()
    if not mid:
        await c.answer("Xabar topilmadi, qaytadan boshlang.", show_alert=True)
        return
    targets = []
    if target in ("users", "all"):
        targets += [("u", r["id"]) for r in await db_all("SELECT id FROM users")]
    if target in ("channels", "all"):
        targets += [("c", ch) for ch in await connected_channels()]
    await log_action(c.from_user.id, "broadcast", str(target), f"{len(targets)} ta")
    await adm_show(c, f"⏳ Yuborish boshlandi ({len(targets)} ta). Tugagach xabar beraman.")
    t = asyncio.create_task(run_broadcast(bot, c.from_user.id, targets, chat, mid))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


# ---- Multi-akkaunt xabari (antimulti chaqiradi) ----------------------------
async def notify_multi(bot: Bot, ids: list[int]):
    ph = ",".join("?" * len(ids))
    users = {r["id"]: r for r in await db_all(f"SELECT * FROM users WHERE id IN ({ph})", tuple(ids))}
    lines = []
    for i, uid in enumerate(ids, 1):
        u = users.get(uid)
        who = (f"@{html.escape(u['username'])}" if u and u["username"]
               else mention(uid, u["full_name"] if u else None))
        lines.append(f"{i}. {who} — <code>{uid}</code>")
    evs = await db_all(
        f"SELECT DISTINCT e.id, e.title, e.channel FROM actions a JOIN events e ON e.id=a.event_id "
        f"WHERE a.user_id IN ({ph}) AND e.status='active'", tuple(ids))
    text = (f"🚨 <b>Multi akkaunt aniqlandi</b>\n"
            f"Bitta qurilmadan <b>{len(ids)}</b> ta akkaunt kirdi:\n\n" + "\n".join(lines))
    if evs:
        text += "\n\n<b>Faol tadbirlarda ishtirok etgan:</b>\n" + "\n".join(
            f"• #{ev['id']} {html.escape(ev['title'])}" + (f" ({ev['channel']})" if ev["channel"] else "")
            for ev in evs)
    text += "\n\n<i>Qurilma Mini App orqali tekshirildi.</i>"
    for rid in {ADMIN_ID} | {i for i, p in STAFF.items() if "multi" in p}:
        try:
            await bot.send_message(rid, text, disable_web_page_preview=True)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# ADMINLAR (ega admin beradi) + BLOKLASH + WEB PANEL API
# ----------------------------------------------------------------------------
PERMS = {"users": "Foydalanuvchilar", "channels": "Majburiy kanallar", "broadcast": "Xabar yuborish",
         "multi": "Multi-akkaunt", "ban": "Bloklash"}
STAFF: dict[int, set] = {}      # qo'shimcha adminlar: id -> imkoniyatlar (ega ADMIN_ID alohida)
BANNED: set[int] = set()


async def load_staff():
    STAFF.clear()
    for r in await db_all("SELECT user_id, perms FROM admins"):
        STAFF[r["user_id"]] = {p for p in (r["perms"] or "").split(",") if p in PERMS}
    BANNED.clear()
    BANNED.update(r["id"] for r in await db_all("SELECT id FROM users WHERE banned=1"))


def perms_of(uid: int) -> set:
    return set(PERMS) if uid == ADMIN_ID else STAFF.get(uid, set())


def is_staff(uid: int) -> bool:
    return uid == ADMIN_ID or uid in STAFF


LOG_LABELS = {"ban": "⛔ Bloklash", "unban": "✅ Blokdan chiqarish", "admin_set": "🛡 Admin tayinladi/o'zgartirdi",
              "admin_del": "🗑 Adminni olib tashladi", "channel_add": "📢 Kanal qo'shdi",
              "channel_del": "🗑 Kanalni o'chirdi", "broadcast": "✉️ Xabar yubordi", "export": "📄 Ro'yxatni yukladi"}


async def log_action(actor: int, action: str, target: str = "", details: str = ""):
    try:
        await db_exec("INSERT INTO admin_log(actor_id, action, target, details) VALUES(?,?,?,?)",
                      (actor, action, target, details))
    except Exception:
        logging.exception("admin_log")


async def add_req_channel(channel: str, title: str, actor: int):
    await db_exec("INSERT OR IGNORE INTO req_channels(channel, title) VALUES(?,?)", (channel, title))
    await log_action(actor, "channel_add", channel)


async def remove_req_channel(cid: int, actor: int):
    row = await db_one("SELECT channel FROM req_channels WHERE id=?", (cid,))
    await db_exec("DELETE FROM req_channels WHERE id=?", (cid,))
    await log_action(actor, "channel_del", row["channel"] if row else str(cid))


async def log_page(page: int, size: int = 15):
    total = await _count("SELECT COUNT(*) c FROM admin_log")
    rows = await db_all(
        "SELECT l.ts, l.actor_id, l.action, l.target, l.details, u.full_name, u.username FROM admin_log l "
        "LEFT JOIN users u ON u.id=l.actor_id ORDER BY l.id DESC LIMIT ? OFFSET ?", (size, page * size))
    items = [{"time": fmt_time(r["ts"]), "actor_id": r["actor_id"],
              "actor": r["full_name"] or (f"@{r['username']}" if r["username"] else str(r["actor_id"])),
              "action": LOG_LABELS.get(r["action"], r["action"]),
              "target": r["target"] or "", "details": r["details"] or ""} for r in rows]
    return total, items


async def set_banned(uid: int, flag: bool, actor: int = 0):
    await db_exec("UPDATE users SET banned=? WHERE id=?", (1 if flag else 0, uid))
    (BANNED.add if flag else BANNED.discard)(uid)
    if actor:
        await log_action(actor, "ban" if flag else "unban", str(uid))


async def set_admin(uid: int, perms, by: int):
    perms = [p for p in perms if p in PERMS]
    await db_exec("INSERT OR REPLACE INTO admins(user_id, perms, added_by) VALUES(?,?,?)",
                  (uid, ",".join(perms), by))
    await load_staff()
    await log_action(by, "admin_set", str(uid), ",".join(perms))


async def del_admin(uid: int, by: int = 0):
    await db_exec("DELETE FROM admins WHERE user_id=?", (uid,))
    await load_staff()
    if by:
        await log_action(by, "admin_del", str(uid))


CB_PERM = [("adm:log", "owner"), ("adm:users", "users"), ("adm:u:", "users"), ("adm:export", "users"), ("adm:search", "users"),
           ("adm:ch", "channels"), ("adm:bc", "broadcast"), ("adm:ban", "ban")]


class PermGate(BaseMiddleware):
    """Admin paneldagi tugmalarni imkoniyatlarga qarab cheklaydi."""

    async def __call__(self, handler, event, data):
        need = next((p for pre, p in CB_PERM if (event.data or "").startswith(pre)), None)
        ok = (event.from_user.id == ADMIN_ID) if need == "owner" else (not need or need in perms_of(event.from_user.id))
        if not ok:
            await event.answer("Sizda bu imkoniyat yo'q.", show_alert=True)
            return None
        return await handler(event, data)


admin_router.callback_query.middleware(PermGate())


async def user_kb(uid: int, viewer: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="💬 Profilga o'tish", url=f"tg://user?id={uid}")]]
    u = await db_one("SELECT banned FROM users WHERE id=?", (uid,))
    if "ban" in perms_of(viewer) and u and not is_staff(uid):
        rows.append([_btn("✅ Blokdan chiqarish" if u["banned"] else "⛔ Bloklash",
                          f"adm:ban:{uid}:{0 if u['banned'] else 1}")])
    rows.append([_btn("◀️ Ro'yxat", "adm:users:0"), BACK])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.callback_query(F.data.startswith("adm:ban:"))
async def adm_ban(c: CallbackQuery):
    _, _, uid, flag = c.data.split(":")
    uid = int(uid)
    if is_staff(uid):
        await c.answer("Adminni bloklab bo'lmaydi.", show_alert=True)
        return
    await set_banned(uid, flag == "1", c.from_user.id)
    await adm_show(c, await user_card(uid), await user_kb(uid, c.from_user.id))


@admin_router.callback_query(F.data.startswith("adm:log:"))
async def adm_log(c: CallbackQuery):
    page = max(0, int(c.data.split(":")[2]))
    total, items = await log_page(page)
    body = "\n\n".join(
        f"<code>{it['time']}</code> {html.escape(it['actor'])}\n{it['action']} {html.escape(it['target'])} {html.escape(it['details'])}"
        for it in items) or "Jurnal bo'sh."
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"adm:log:{page - 1}"))
    if (page + 1) * 15 < total:
        nav.append(_btn("▶️", f"adm:log:{page + 1}"))
    await adm_show(c, f"📜 <b>Admin jurnali</b> ({total})\n\n{body}", kb_of(nav, [BACK]) if nav else kb_of([BACK]))


# ---- Web panel API ---------------------------------------------------------
def api(need: str | None = None, owner: bool = False):
    def deco(fn):
        async def h(request: web.Request):
            u = antimulti.validate_init_data(request.headers.get("X-Init-Data", ""), max_age=86400)
            if not u:
                return web.json_response({"ok": False, "error": "Sessiya eskirgan. Paneldan chiqib qayta oching."}, status=401)
            uid = u["id"]
            if not is_staff(uid) or (owner and uid != ADMIN_ID) or (need and need not in perms_of(uid)):
                return web.json_response({"ok": False, "error": "Sizda ruxsat yo'q."}, status=403)
            try:
                body = await request.json()
            except Exception:
                body = {}
            try:
                res = await fn(uid, body, request.app["bot"])
            except Exception:
                logging.exception("admin api")
                return web.json_response({"ok": False, "error": "Server xatosi."}, status=500)
            return web.json_response({"ok": True, **res})
        return h
    return deco


@api()
async def api_me(uid, b, bot):
    me = await db_one("SELECT full_name FROM users WHERE id=?", (uid,))
    return {"id": uid, "name": (me["full_name"] if me else "") or str(uid), "owner": uid == ADMIN_ID,
            "perms": sorted(perms_of(uid)), "all_perms": PERMS,
            "stats": {
                "users": await _count("SELECT COUNT(*) c FROM users"),
                "today": await _count("SELECT COUNT(*) c FROM users WHERE joined_at=strftime('%d.%m.%Y','now')"),
                "battles": await _count("SELECT COUNT(*) c FROM events WHERE kind='battle' AND status='active'"),
                "konkurs": await _count("SELECT COUNT(*) c FROM events WHERE kind='konkurs' AND status='active'"),
                "channels": await _count("SELECT COUNT(*) c FROM req_channels"),
                "banned": await _count("SELECT COUNT(*) c FROM users WHERE banned=1")}}


@api("users")
async def api_users(uid, b, bot):
    page, q = max(0, int(b.get("page", 0))), str(b.get("q", "")).strip().lower()
    where, args = "", ()
    if q.isdigit():
        where, args = "WHERE id=?", (int(q),)
    elif q:
        like = f"%{q.lstrip('@')}%"
        where, args = "WHERE lower(username) LIKE ? OR lower(full_name) LIKE ?", (like, like)
    total = await _count(f"SELECT COUNT(*) c FROM users {where}", args)
    rows = await db_all(f"SELECT id, username, full_name, joined_at, banned FROM users {where} "
                        f"ORDER BY {ORDER_NEW} LIMIT 20 OFFSET ?", args + (page * 20,))
    return {"total": total, "items": [dict(r) for r in rows]}


@api("users")
async def api_user(uid, b, bot):
    t = int(b["id"])
    u = await db_one("SELECT * FROM users WHERE id=?", (t,))
    if not u:
        return {"found": False}
    return {"found": True, "id": t, "name": u["full_name"], "username": u["username"], "lang": u["lang"],
            "joined": u["joined_at"], "banned": bool(u["banned"]), "staff": is_staff(t),
            "created": await _count("SELECT COUNT(*) c FROM events WHERE owner_id=? AND status!='draft'", (t,)),
            "given": await _count("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                                  "WHERE a.user_id=? AND e.kind='battle'", (t,)),
            "received": await _count("SELECT COUNT(*) c FROM actions a JOIN events e ON e.id=a.event_id "
                                     "WHERE e.kind='battle' AND a.option_id=?", (t,)),
            "devices": await device_accounts(t)}


@api("ban")
async def api_ban(uid, b, bot):
    t = int(b["id"])
    if is_staff(t):
        return {"done": False, "reason": "Adminni bloklab bo'lmaydi."}
    await set_banned(t, bool(b.get("banned")), uid)
    return {"done": True}


@api("channels")
async def api_channels(uid, b, bot):
    return {"items": [dict(r) for r in await req_channels()]}


@api("channels")
async def api_channel_add(uid, b, bot):
    ok, channel, title, reason = await check_channel(bot, str(b.get("channel", "")), None)
    if not ok:
        return {"added": False, "reason": reason}
    await add_req_channel(channel, title, uid)
    return {"added": True, "channel": channel}


@api("channels")
async def api_channel_del(uid, b, bot):
    await remove_req_channel(int(b["id"]), uid)
    _sub_cache.clear()
    return {}


async def run_text_broadcast(bot: Bot, report_to: int, targets, text: str):
    ok = fail = 0
    for _, tid in targets:
        try:
            await bot.send_message(tid, text, parse_mode=None)
            ok += 1
        except TelegramRetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 1)
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await bot.send_message(report_to, f"✅ Web paneldan yuborish tugadi: {ok} ta yetdi, {fail} ta yetmadi")


@api("broadcast")
async def api_broadcast(uid, b, bot):
    text, target = str(b.get("text", "")).strip(), b.get("target")
    if not text or target not in ("users", "channels", "all"):
        return {"queued": 0}
    targets = []
    if target in ("users", "all"):
        targets += [("u", r["id"]) for r in await db_all("SELECT id FROM users")]
    if target in ("channels", "all"):
        targets += [("c", ch) for ch in await connected_channels()]
    await log_action(uid, "broadcast", str(target), f"{len(targets)} ta (web)")
    t = asyncio.create_task(run_text_broadcast(bot, uid, targets, text[:4000]))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"queued": len(targets)}


@api("multi")
async def api_multi(uid, b, bot):
    groups = []
    for r in await db_all("SELECT did, COUNT(DISTINCT user_id) n FROM devices GROUP BY did "
                          "HAVING n>=2 ORDER BY n DESC LIMIT 30"):
        us = await db_all("SELECT DISTINCT d.user_id AS id, u.username, u.full_name, u.banned FROM devices d "
                          "LEFT JOIN users u ON u.id=d.user_id WHERE d.did=?", (r["did"],))
        groups.append({"n": r["n"], "users": [dict(x) for x in us]})
    return {"groups": groups}


@api(owner=True)
async def api_admins(uid, b, bot):
    items = []
    for aid, pm in STAFF.items():
        u = await db_one("SELECT username, full_name FROM users WHERE id=?", (aid,))
        items.append({"id": aid, "name": (u["full_name"] if u else "") or "", "username": u["username"] if u else None,
                      "perms": sorted(pm)})
    return {"items": items}


@api(owner=True)
async def api_admin_set(uid, b, bot):
    t = int(b["id"])
    if t == ADMIN_ID or t <= 0:
        return {"saved": False, "reason": "Bu ID ni admin qilib bo'lmaydi."}
    new = t not in STAFF
    await set_admin(t, b.get("perms", []), uid)
    if new:
        try:
            await bot.send_message(t, "🛡 Siz botga <b>admin</b> etib tayinlandingiz.\n/admin ni bosing.")
        except Exception:
            pass
    return {"saved": True, "new": new}


@api(owner=True)
async def api_admin_del(uid, b, bot):
    await del_admin(int(b["id"]), uid)
    return {}


@api(owner=True)
async def api_log(uid, b, bot):
    total, items = await log_page(max(0, int(b.get("page", 0))), 20)
    return {"total": total, "items": items}


_rank_cache: dict[int, tuple[float, dict]] = {}


async def api_rank(request: web.Request):
    """Jonli reyting (ochiq: kanaldagi tugmalarda ham ovozlar ko'rinib turadi)."""
    try:
        eid = int(request.query.get("e", "0"))
    except ValueError:
        eid = 0
    hdr = {"Cache-Control": "no-store"}
    hit = _rank_cache.get(eid)
    if hit and time.time() - hit[0] < 3:
        return web.json_response(hit[1], headers=hdr)
    ev = await db_one("SELECT id, title, status, ends_at, winners, auto, channel FROM events "
                      "WHERE id=? AND kind='battle' AND status!='draft'", (eid,))
    if not ev:
        return web.json_response({"ok": False}, status=404, headers=hdr)
    rows = await participants_rows(eid, 100)
    data = {"ok": True, "title": (ev["channel"] if ev["auto"] and ev["channel"] else ev["title"]),
            "status": ev["status"], "ends_at": ev["ends_at"], "winners": ev["winners"] or 1,
            "total": await count_actions(eid), "now": int(time.time()),
            "items": [{"id": r["user_id"], "name": person(r), "votes": r["c"]} for r in rows]}
    _rank_cache[eid] = (time.time(), data)
    return web.json_response(data, headers=hdr)


async def h_rank_page(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "webapp", "rank.html"))


async def h_admin_page(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "webapp", "admin.html"))


def register_web_admin(app: web.Application, bot: Bot):
    app["bot"] = bot
    app.router.add_get("/admin", h_admin_page)
    app.router.add_get("/rank", h_rank_page)
    app.router.add_get("/api/rank", api_rank)
    app.router.add_post("/api/admin/log", api_log)
    for name, fn in [("me", api_me), ("users", api_users), ("user", api_user), ("ban", api_ban),
                     ("channels", api_channels), ("channel_add", api_channel_add),
                     ("channel_del", api_channel_del), ("broadcast", api_broadcast), ("multi", api_multi),
                     ("admins", api_admins), ("admin_set", api_admin_set), ("admin_del", api_admin_del)]:
        app.router.add_post(f"/api/admin/{name}", fn)


# ----------------------------------------------------------------------------
async def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")
    if not antimulti.WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL environment variable is not set; set it to the Render HTTPS URL")
    await init_db()
    await load_staff()
    await load_langs()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username
    antimulti.setup(db_one, db_all, db_exec, BOT_TOKEN,
                    notify=lambda ids: notify_multi(bot, ids))
    if antimulti.WEBAPP_URL:
        await antimulti.start_server(extra=lambda app: register_web_admin(app, bot))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(LangCtx())
    bot.session.middleware(I18nOut())
    dp.include_router(admin_router)
    dp.include_router(router)
    asyncio.create_task(watcher(bot))
    # chat_member (kanaldan chiqqanlar) va channel_post (#konkurs) yangilanishlari ham olinadi
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())