import asyncio
import difflib
import html
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import antimulti
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
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
    "done":       label("done", "Tayyor"),
    "cancel":     label("cancel", "Bekor qilish"),
}
SKIP_CH = "O'tkazib yuborish"
MANUAL = "Qo'lda yakunlayman"
NO_MIN = "Yo'q"


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


def menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [kb_button("battle", "Battle yaratish", "success"),
             kb_button("konkurs", "KONKURS yaratish", "success")],
            [kb_button("my_battles", "Mening battlelarim", "primary"),
             kb_button("my_konkurs", "Mening konkurslarim", "primary")],
            [kb_button("profile", "Profil", "primary"),
             kb_button("lang", "Til", "primary")],
            [kb_button("support", "Murojaat", "danger"),
             kb_button("guide", "Qo'llanma", "danger")],
        ],
        resize_keyboard=True,
    )


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
                    "ALTER TABLE users ADD COLUMN tg_lang TEXT"):
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
    await m.answer(f"{e('home')} <b>Bosh menyu</b>", reply_markup=menu_kb())


@router.message(Command("cancel"))
@router.message(F.text == BTN["cancel"])
async def cancel(m: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("event_id"):
        eid = data["event_id"]
        await db_exec("DELETE FROM event_media WHERE event_id=?", (eid,))
        await db_exec("DELETE FROM events WHERE id=? AND status='draft'", (eid,))
    await state.clear()
    await m.answer(f"{e('home')} Bosh menyu", reply_markup=menu_kb())


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


@router.message(F.text == BTN["battle"])
async def create_battle(m: Message, state: FSMContext):
    await start_create(m, state, "battle")


@router.message(F.text == BTN["konkurs"])
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


@router.message(Create.content, F.text == BTN["done"])
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
    if m.text == SKIP_CH:
        if data["kind"] == "battle":
            await m.answer("Battle uchun kanal shart. Kanalni yuboring.")
            return
    else:
        channel = m.text.strip()
        if not channel.startswith("@"):
            channel = "@" + channel
        try:
            me = await bot.get_chat_member(channel, bot.id)
            if me.status not in ("administrator", "creator"):
                raise ValueError
        except Exception:
            await m.answer("Kanal topilmadi yoki bot u yerda admin emas. Qayta yuboring.")
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
    if t != NO_MIN:
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
    if m.text != MANUAL:
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
        reply_markup=menu_kb(),
    )
    await send_post(bot, m.chat.id, ev, await event_kb(ev))


# ----------------------------------------------------------------------------
# Qatnashish (battle ishtirokchisi / konkurs), ovoz berish (kanalda)
# ----------------------------------------------------------------------------
def verify_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qurilmani tasdiqlash",
                             web_app=WebAppInfo(url=antimulti.WEBAPP_URL))]])


async def send_verify(bot: Bot, user_id: int) -> bool:
    try:
        await bot.send_message(
            user_id,
            "Ovoz berish / qatnashish uchun avval qurilmangizni tasdiqlang.\n"
            "Pastdagi tugmani bosing, keyin kanalga qaytib, tugmani qayta bosing.",
            reply_markup=verify_kb())
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
    """/multi 12  -> 12-konkursdagi shubhali akkauntlar guruhlari."""
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await m.answer("Ishlatish: <code>/multi 12</code>  (12 o'rniga konkurs raqami)")
        return
    ev = await db_one("SELECT * FROM events WHERE id=? AND kind='konkurs'", (int(arg),))
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


async def finish_battle(bot: Bot, ev):
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
    text = (head + f"Ishtirokchilar: <b>{len(rows)}</b>\nJami ovozlar: <b>{total}</b>\n\n"
            f"{e('winner')} <b>Natijalar:</b>\n" + "\n".join(lines))
    if ev["channel"]:
        try:
            await bot.send_message(ev["channel"], text)
        except Exception:
            pass
    await bot.send_message(ev["owner_id"], text)

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


@router.message(F.text == BTN["my_battles"])
async def my_battles(m: Message, state: FSMContext):
    await state.clear()
    await show_my(m, "battle")


@router.message(F.text == BTN["my_konkurs"])
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
@router.message(F.text == BTN["profile"])
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
@router.message(F.text == BTN["lang"])
async def choose_lang(m: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])
    await m.answer(f"{e('lang')} Tilni tanlang:", reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def set_lang(c: CallbackQuery):
    await db_exec("UPDATE users SET lang=? WHERE id=?", (c.data[5:], c.from_user.id))
    await c.answer("Saqlandi ✅")
    await c.message.delete()


@router.message(F.text == BTN["guide"])
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


@router.message(F.text == BTN["support"])
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
    await m.answer("Yuborildi ✅ Tez orada javob beramiz.", reply_markup=menu_kb())


# ----------------------------------------------------------------------------
async def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")
    if not antimulti.WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL environment variable is not set; set it to the Render HTTPS URL")
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username
    antimulti.setup(db_one, db_all, db_exec, BOT_TOKEN,
                    notify=lambda t: bot.send_message(ADMIN_ID, t))
    if antimulti.WEBAPP_URL:
        await antimulti.start_server()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    asyncio.create_task(watcher(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())