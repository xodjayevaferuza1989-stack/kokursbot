import asyncio
import json
import logging
import os
import random
import time
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, ChatJoinRequest, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyParameters, WebAppInfo)
from aiohttp import web

import adminpanel
import games
import webapp

# ====================== SOZLAMALAR ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = games.ADMIN_IDS            # games bilan umumiy set: panelda admin qo'shilsa, hamma joyda ko'rinadi
ENV_ADMINS = set(ADMIN_IDS)            # asosiy adminlar (ADMIN_IDS muhit o'zgaruvchisi): panel orqali o'chirib bo'lmaydi
from dbpath import DB_PATH

REF_BONUS = 20          # do'st taklif qilganda beriladigan ball
QUIZ_REWARD = 10        # viktorinaga to'g'ri javob uchun
DAILY_MIN, DAILY_MAX = 5, 25

from emojis import label as L, pid, tg
em = tg  # eski nom

# ====================== BAZA ======================
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, points INTEGER DEFAULT 0,
  last_bonus TEXT, ref_by INTEGER, lang TEXT DEFAULT 'uz',
  banned INTEGER DEFAULT 0, joined TEXT);
CREATE TABLE IF NOT EXISTS promos(
  code TEXT PRIMARY KEY, points INTEGER, max_uses INTEGER, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS promo_uses(code TEXT, user_id INTEGER, PRIMARY KEY(code,user_id));
CREATE TABLE IF NOT EXISTS quiz(
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, options TEXT, correct INTEGER);
CREATE TABLE IF NOT EXISTS quiz_done(user_id INTEGER, day TEXT, PRIMARY KEY(user_id,day));
CREATE TABLE IF NOT EXISTS shop(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, price INTEGER);
CREATE TABLE IF NOT EXISTS req_channels(
  chat_id INTEGER PRIMARY KEY, title TEXT, username TEXT);
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY, name TEXT, added_by INTEGER, added TEXT);
""")
db.executescript("""
CREATE TABLE IF NOT EXISTS join_reqs(chat_id INTEGER, user_id INTEGER, name TEXT, username TEXT, ts INTEGER, status TEXT,
  PRIMARY KEY(chat_id,user_id));
CREATE TABLE IF NOT EXISTS known_chats(chat_id INTEGER PRIMARY KEY, title TEXT, username TEXT, ctype TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS req_pass(chat_id INTEGER, user_id INTEGER, ts INTEGER, PRIMARY KEY(chat_id,user_id));
""")
for _col in ("kind TEXT DEFAULT 'normal'", "link TEXT"):      # eski bazalar uchun ustunlar
    try:
        db.execute("ALTER TABLE req_channels ADD COLUMN " + _col)
    except sqlite3.OperationalError:
        pass
db.commit()
ADMIN_IDS.update(r["id"] for r in db.execute("SELECT id FROM admins"))
if not db.execute("SELECT 1 FROM quiz").fetchone():
    db.execute("INSERT INTO quiz(question,options,correct) VALUES(?,?,?)",
               ("O'zbekiston poytaxti qaysi shahar?",
                json.dumps(["Samarqand", "Toshkent", "Buxoro", "Xiva"]), 1))
db.commit()

def today() -> str:
    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d")

def get_user(uid):
    return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def add_points(uid, n):
    db.execute("UPDATE users SET points=MAX(0,points+?) WHERE id=?", (n, uid))
    db.commit()

def register(user, ref=None) -> bool:
    if get_user(user.id):
        return False
    ref_by = ref if ref and ref != user.id and get_user(ref) else None
    db.execute("INSERT INTO users(id,name,ref_by,joined) VALUES(?,?,?,?)",
               (user.id, user.full_name, ref_by, today()))
    if ref_by:
        db.execute("UPDATE users SET points=points+? WHERE id=?", (REF_BONUS, ref_by))
    db.commit()
    return ref_by is not None

# ====================== TUGMALAR ======================
def btn(text, style=None):
    # style: success (yashil) / primary (ko'k) / danger (qizil)
    extra = {"style": style} if style else {}
    return KeyboardButton(text=text, **extra)

B_BATTLE, B_CONTEST = L("battle", "Battle yaratish"), L("contest", "KONKURS yaratish")
B_MY_BATTLES, B_MY_CONTESTS = L("my_battles", "Mening battlelarim"), L("my_contests", "Mening konkurslarim")
B_PROFILE, B_LANG = L("profile", "Profil"), L("lang", "Til")
B_SUPPORT, B_GUIDE = L("support", "Murojaat"), L("guide", "Qo'llanma")
B_MENU = L("menu", "Menyu")
B_QUIZ, B_DAILY = L("quiz", "Kunlik viktorina"), L("daily", "Kunlik bonus")
B_SHOP, B_PROMO = L("shop", "Ball do'koni"), L("promo", "Promokod")
B_SHARE, B_HOME = L("share", "Do'stlarga ulashib ball olish"), L("home", "Bosh menyu")
ICON_OF = {B_BATTLE: "battle", B_CONTEST: "contest", B_MY_BATTLES: "my_battles", B_MY_CONTESTS: "my_contests",
           B_PROFILE: "profile", B_LANG: "lang", B_SUPPORT: "support", B_GUIDE: "guide", B_MENU: "menu",
           B_QUIZ: "quiz", B_DAILY: "daily", B_SHOP: "shop", B_PROMO: "promo", B_SHARE: "share", B_HOME: "home"}

def main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [btn(B_BATTLE, "success"), btn(B_CONTEST, "success")],
        [btn(B_MY_BATTLES, "primary"), btn(B_MY_CONTESTS, "primary")],
        [btn(B_PROFILE, "primary"), btn(B_LANG, "primary")],
        [btn(B_SUPPORT, "danger"), btn(B_GUIDE, "danger")],
        [btn(B_MENU, "primary")]])

def bonus_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [btn(B_QUIZ, "success"), btn(B_DAILY, "success")],
        [btn(B_SHOP, "danger"), btn(B_PROMO, "danger")],
        [btn(B_PROFILE, "primary"), btn(B_LANG, "primary")],
        [btn(B_SHARE, "danger")],
        [btn(B_HOME, "primary")]])

A_STATS, A_BROADCAST = L("a_stats", "Statistika"), L("a_bc", "Xabar yuborish")
A_PROMO, A_QUIZ = L("a_promo", "Promokod qo'shish"), L("a_quiz", "Savol qo'shish")
A_SHOP, A_POINTS = L("a_shop", "Mahsulot qo'shish"), L("a_points", "Ball berish/ayirish")
A_BAN, A_UNBAN = L("a_ban", "Bloklash"), L("a_unban", "Blokdan chiqarish")
A_REQ, A_CHANS = L("a_req", "Majburiy kanallar"), L("a_chans", "Ulangan kanallar")
A_PROMOS, A_SHOPLIST = L("a_promos", "Promokodlar ro'yxati"), L("a_shoplist", "Mahsulotlar ro'yxati")
A_WEB, A_EXIT = L("web", "Web panel"), L("a_exit", "Admin paneldan chiqish")
ICON_OF.update({A_STATS: "a_stats", A_BROADCAST: "a_bc", A_PROMO: "a_promo", A_QUIZ: "a_quiz", A_SHOP: "a_shop",
                A_POINTS: "a_points", A_BAN: "a_ban", A_UNBAN: "a_unban", A_REQ: "a_req", A_CHANS: "a_chans",
                A_PROMOS: "a_promos", A_SHOPLIST: "a_shoplist", A_WEB: "web", A_EXIT: "a_exit"})

def admin_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [btn(A_WEB, "success")],
        [btn(A_STATS, "primary"), btn(A_BROADCAST, "success")],
        [btn(A_REQ, "success"), btn(A_CHANS, "primary")],
        [btn(A_PROMO, "success"), btn(A_QUIZ, "success")],
        [btn(A_PROMOS, "primary"), btn(A_SHOPLIST, "primary")],
        [btn(A_SHOP, "success"), btn(A_POINTS, "primary")],
        [btn(A_BAN, "danger"), btn(A_UNBAN, "danger")],
        [btn(A_EXIT, "danger")]])

# ====================== HOLATLAR ======================
class S(StatesGroup):
    promo = State()
    support = State()
    a_broadcast = State()
    a_reqch = State()
    a_promo = State()
    a_quiz = State()
    a_shop = State()
    a_points = State()
    a_ban = State()
    a_unban = State()

# ====================== MIDDLEWARE ======================
class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and u.id not in ADMIN_IDS:
            r = get_user(u.id)
            if r and r["banned"]:
                return
        return await handler(event, data)

dp = Dispatcher()
dp.update.outer_middleware(BanMiddleware())

# ====================== BOT UCHUN MAJBURIY KANALLAR ======================
_sub_ok = {}          # user_id -> oxirgi muvaffaqiyatli tekshiruv vaqti (tez-tez so'rov yubormaslik uchun)
SUB_CACHE_SEC = 120

def req_channels():
    return db.execute("SELECT * FROM req_channels ORDER BY rowid").fetchall()

async def missing_subs(bot: Bot, uid: int, chans):
    """Foydalanuvchi obuna bo'lmagan majburiy kanallar. Zayafka kanalda ariza yuborgan ham hisoblanadi."""
    bad = []
    for c in chans:
        try:
            mem = await bot.get_chat_member(c["chat_id"], uid)
        except Exception:
            continue   # bot kanaldan chiqarilgan yoki kanal o'chgan bo'lsa, foydalanuvchini to'smaymiz
        if mem.status in ("left", "kicked") or (mem.status == "restricted" and not mem.is_member):
            if c["kind"] == "request" and db.execute(
                    "SELECT 1 FROM join_reqs WHERE chat_id=? AND user_id=? AND status!='declined'", (c["chat_id"], uid)).fetchone():
                continue
            bad.append(c)
        else:
            db.execute("INSERT OR IGNORE INTO req_pass(chat_id,user_id,ts) VALUES(?,?,?)", (c["chat_id"], uid, int(time.time())))
            db.commit()
    return bad

@dp.my_chat_member()
async def on_bot_chat_status(e: ChatMemberUpdated, bot: Bot):
    """Bot kanalga admin qilinsa, adminlarga kanal ID sini yuboradi (yopiq kanalni panelga qo'shish uchun kerak)."""
    if e.chat.type == "channel" and e.new_chat_member.status == "administrator" and e.old_chat_member.status != "administrator":
        un = f"\n@{e.chat.username}" if e.chat.username else "\nYopiq kanal"
        for a in ADMIN_IDS:
            try:
                await bot.send_message(a, f"📣 Bot kanalga admin qilindi:\n<b>{e.chat.title}</b>{un}\nID: <code>{e.chat.id}</code>\n\n"
                                          "Web panel → Boshqa → Majburiy kanallar orqali qo'shishingiz mumkin.")
            except Exception:
                pass

@dp.chat_join_request()
async def on_join_request(r: ChatJoinRequest):
    """Zayafka kanallarga yuborilgan arizalarni saqlaydi (admin panelda tasdiqlanadi/rad etiladi)."""
    if db.execute("SELECT 1 FROM req_channels WHERE chat_id=?", (r.chat.id,)).fetchone():
        u = r.from_user
        db.execute("INSERT OR REPLACE INTO join_reqs(chat_id,user_id,name,username,ts,status) VALUES(?,?,?,?,?,'pending')",
                   (r.chat.id, u.id, u.full_name, u.username or "", int(time.time())))
        db.commit()

GATE_TEXT = ("🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling</b> 👇\n"
             "Obuna bo'lgach, «Tekshirish» tugmasini bosing.")

def gate_markup(bad, args=""):
    return games.sub_kb([{"title": c["title"], "username": c["username"], "link": c["link"]} for c in bad], "gate:" + args[:50])

class SubGate(BaseMiddleware):
    """Admin bo'lmagan foydalanuvchilar shaxsiy chatda majburiy kanallarga obuna bo'lmaguncha botdan foydalana olmaydi."""
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if not u or u.is_bot or u.id in ADMIN_IDS:
            return await handler(event, data)
        msg = event if isinstance(event, Message) else getattr(event, "message", None)
        if msg is None or msg.chat.type != "private":
            return await handler(event, data)   # kanal/guruhdagi tugmalarga tegmaymiz
        if isinstance(event, CallbackQuery) and (event.data or "").startswith("gate:"):
            return await handler(event, data)
        chans = req_channels()
        if not chans or time.time() - _sub_ok.get(u.id, 0) < SUB_CACHE_SEC:
            return await handler(event, data)
        bad = await missing_subs(data["bot"], u.id, chans)
        if not bad:
            _sub_ok[u.id] = time.time()
            return await handler(event, data)
        args = ""
        if isinstance(event, Message) and (event.text or "").startswith("/start "):
            args = event.text.split(maxsplit=1)[1].strip()
        if isinstance(event, CallbackQuery):
            await event.answer("❌ Avval majburiy kanallarga obuna bo'ling.", show_alert=True)
        await msg.answer(GATE_TEXT, reply_markup=gate_markup(bad, args))

class ChatSeen(BaseMiddleware):
    """Bot admin bo'lgan kanal/guruhlarni eslab qoladi (panelda ro'yxatdan tanlash uchun)."""
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat is not None and chat.type in ("channel", "supergroup", "group"):
            try:
                db.execute("""INSERT INTO known_chats(chat_id,title,username,ctype,ts) VALUES(?,?,?,?,?)
                              ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username, ts=excluded.ts""",
                           (chat.id, chat.title or chat.username or str(chat.id), chat.username or "", chat.type, int(time.time())))
                db.commit()
            except Exception:
                pass
        return await handler(event, data)

dp.channel_post.outer_middleware(ChatSeen())
dp.my_chat_member.outer_middleware(ChatSeen())
dp.message.outer_middleware(SubGate())
dp.callback_query.outer_middleware(SubGate())

WELCOME = (
    f"{tg('w_party')} <b>Botimizga xush kelibsiz!</b>\n\n"
    f"{tg('w_pin')} <b>Ushbu Bot Orqali Siz:</b>\n\n"
    f"{tg('w_mega')} Kanallaringizda Ovozli Konkurslar Qilishingiz Mumkin!\n\n"
    f"{tg('w_gold')} Botni Kanalga Admin Qiling 👮‍♂️\n"
    f"{tg('w_silver')} Kanalga <b>#battil</b> deb yozib yuboring tayyor {tg('w_ok')}\n\n"
    f"{tg('w_pin')} <b>Foydali Taraflar</b>\n\n"
    f"{tg('w_people')} Ovoz Beruvchilar Kanalingizga Obuna Boʻlishadi {tg('w_ok')}\n\n"
    f"{tg('w_warn')} Agar Ovoz beruvchi kanaldan chiqib ketsa, ovozi avtomatik real vaqtda ayriladi {tg('w_ok')}\n\n"
    f"{tg('w_down')} Quyidagi menyudan birini tanlang:")

# ====================== ASOSIY HANDLERLAR ======================
@dp.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Bekor qilindi.\n\nBosh menyu", reply_markup=main_menu())

@dp.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    if command.args and (command.args.startswith("join_") or command.args.startswith("vote_")):
        register(m.from_user)
        return await games.deeplink(m.bot, m, command.args, state)
    ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    if register(m.from_user, ref):
        try:
            await m.bot.send_message(ref, f"{em('gift')} Do'stingiz qo'shildi! +{REF_BONUS} ball")
        except Exception:
            pass
    await m.answer(WELCOME, reply_markup=main_menu())

@dp.callback_query(F.data.startswith("gate:"))
async def gate_check(c: CallbackQuery, state: FSMContext, bot: Bot):
    bad = await missing_subs(bot, c.from_user.id, req_channels())
    if bad:
        await c.answer("❌ Hali hamma kanalga obuna bo'lmadingiz.", show_alert=True)
        try:
            await c.message.edit_reply_markup(reply_markup=gate_markup(bad, c.data[5:]))
        except Exception:
            pass
        return
    _sub_ok[c.from_user.id] = time.time()
    await c.answer("✅ Rahmat!")
    try:
        await c.message.delete()
    except Exception:
        pass
    args = c.data[5:]
    await state.clear()
    if args.startswith("join_") and args[5:].isdigit():
        register(c.from_user)
        return await games.contest_join(bot, c.from_user, int(args[5:]), state)
    if args.startswith("vote_"):
        p = args.split("_")
        if len(p) == 3 and p[1].isdigit() and p[2].isdigit():
            register(c.from_user)
            return await games.battle_vote(bot, c.from_user, int(p[1]), int(p[2]))
    ref = int(args[4:]) if args.startswith("ref_") and args[4:].isdigit() else None
    if register(c.from_user, ref):
        try:
            await bot.send_message(ref, f"{em('gift')} Do'stingiz qo'shildi! +{REF_BONUS} ball")
        except Exception:
            pass
    await bot.send_message(c.from_user.id, WELCOME, reply_markup=main_menu())

async def show_bonus_menu(m: Message):
    u = get_user(m.from_user.id)
    await m.answer(f"{em('gift')} <b>Bonus menyu</b>\n{em('coin')} Ballaringiz: <b>{u['points']}</b>",
                   reply_markup=bonus_menu())

async def show_home(m: Message):
    await m.answer("Bosh menyu", reply_markup=main_menu())

async def profile(m: Message):
    u = get_user(m.from_user.id)
    refs = db.execute("SELECT COUNT(*) c FROM users WHERE ref_by=?", (u["id"],)).fetchone()["c"]
    await m.answer(f"👤 <b>Profil</b>\nID: <code>{u['id']}</code>\nIsm: {u['name']}\n"
                   f"{em('coin')} Ball: <b>{u['points']}</b>\n👥 Taklif qilganlar: <b>{refs}</b>\n"
                   f"🌐 Til: {u['lang']}")

async def language(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        games.ibi("flag_uz", "O'zbekcha", cb="lang:uz"),
        games.ibi("flag_ru", "Русский", cb="lang:ru"),
        games.ibi("flag_en", "English", cb="lang:en")]])
    await m.answer("🌐 Tilni tanlang:", reply_markup=kb)

@dp.callback_query(F.data.startswith("lang:"))
async def set_lang(c: CallbackQuery):
    db.execute("UPDATE users SET lang=? WHERE id=?", (c.data[5:], c.from_user.id))
    db.commit()
    await c.message.edit_text("✅ Til saqlandi.")

async def daily_bonus(m: Message):
    u = get_user(m.from_user.id)
    if u["last_bonus"] == today():
        return await m.answer("⏳ Bugungi bonusni olib bo'lgansiz. Ertaga qaytib keling!")
    n = random.randint(DAILY_MIN, DAILY_MAX)
    db.execute("UPDATE users SET last_bonus=? WHERE id=?", (today(), u["id"]))
    add_points(u["id"], n)
    await m.answer(f"{em('gift')} Kunlik bonus: <b>+{n}</b> ball!")

async def daily_quiz(m: Message):
    if db.execute("SELECT 1 FROM quiz_done WHERE user_id=? AND day=?",
                  (m.from_user.id, today())).fetchone():
        return await m.answer("🧠 Bugungi viktorinada qatnashgansiz. Ertaga yangi savol bo'ladi!")
    q = db.execute("SELECT * FROM quiz ORDER BY RANDOM() LIMIT 1").fetchone()
    if not q:
        return await m.answer("Hozircha savollar yo'q.")
    opts = json.loads(q["options"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=o, callback_data=f"quiz:{q['id']}:{i}")] for i, o in enumerate(opts)])
    await m.answer(f"🧠 <b>{q['question']}</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(c: CallbackQuery):
    _, qid, idx = c.data.split(":")
    try:
        db.execute("INSERT INTO quiz_done VALUES(?,?)", (c.from_user.id, today()))
    except sqlite3.IntegrityError:
        return await c.answer("Bugun javob bergansiz!", show_alert=True)
    db.commit()
    q = db.execute("SELECT * FROM quiz WHERE id=?", (qid,)).fetchone()
    if int(idx) == q["correct"]:
        add_points(c.from_user.id, QUIZ_REWARD)
        await c.message.edit_text(f"✅ To'g'ri! <b>+{QUIZ_REWARD}</b> ball.")
    else:
        right = json.loads(q["options"])[q["correct"]]
        await c.message.edit_text(f"❌ Noto'g'ri. To'g'ri javob: <b>{right}</b>")

async def shop(m: Message):
    items = db.execute("SELECT * FROM shop").fetchall()
    if not items:
        return await m.answer("🛒 Do'kon hozircha bo'sh.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"{i['title']} — {i['price']} ball", callback_data=f"buy:{i['id']}")] for i in items])
    u = get_user(m.from_user.id)
    await m.answer(f"🛒 <b>Ball do'koni</b>\n{em('coin')} Ballaringiz: <b>{u['points']}</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    item = db.execute("SELECT * FROM shop WHERE id=?", (c.data[4:],)).fetchone()
    u = get_user(c.from_user.id)
    if not item:
        return await c.answer("Mahsulot topilmadi", show_alert=True)
    if u["points"] < item["price"]:
        return await c.answer("Ball yetarli emas!", show_alert=True)
    add_points(u["id"], -item["price"])
    await c.message.answer(f"✅ <b>{item['title']}</b> sotib olindi. Admin siz bilan bog'lanadi.")
    for a in ADMIN_IDS:
        try:
            await c.bot.send_message(a, f"🛒 Yangi buyurtma\n{item['title']} ({item['price']} ball)\n"
                                        f"Kim: {u['name']} (<code>{u['id']}</code>)")
        except Exception:
            pass
    await c.answer()

async def promo_ask(m: Message, state: FSMContext):
    await state.set_state(S.promo)
    await m.answer("🎟 Promokodni yuboring:")

@dp.message(S.promo, F.text)
async def promo_apply(m: Message, state: FSMContext):
    if m.text in ROUTES or m.text in STATE_ROUTES:
        return await buttons(m, state)
    await state.clear()
    code = m.text.strip().upper()
    p = db.execute("SELECT * FROM promos WHERE code=?", (code,)).fetchone()
    if not p or p["used"] >= p["max_uses"]:
        return await m.answer("❌ Promokod noto'g'ri yoki muddati tugagan.")
    try:
        db.execute("INSERT INTO promo_uses VALUES(?,?)", (code, m.from_user.id))
    except sqlite3.IntegrityError:
        return await m.answer("⚠️ Bu promokoddan foydalangansiz.")
    db.execute("UPDATE promos SET used=used+1 WHERE code=?", (code,))
    add_points(m.from_user.id, p["points"])
    await m.answer(f"✅ Promokod qabul qilindi: <b>+{p['points']}</b> ball!")

async def share(m: Message):
    me = await m.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{m.from_user.id}"
    await m.answer(f"👥 Do'stlaringizni taklif qiling — har biri uchun <b>+{REF_BONUS}</b> ball!\n\n"
                   f"Sizning havolangiz:\n<code>{link}</code>")

async def support_ask(m: Message, state: FSMContext):
    await state.set_state(S.support)
    await m.answer("📝 Murojaatingizni yozing:")

@dp.message(S.support)
async def support_send(m: Message, state: FSMContext):
    if (m.text or "") in ROUTES or (m.text or "") in STATE_ROUTES:
        return await buttons(m, state)
    await state.clear()
    for a in ADMIN_IDS:
        try:
            await m.bot.send_message(a, f"📝 Murojaat: {m.from_user.full_name} (<code>{m.from_user.id}</code>)")
            await m.copy_to(a)
        except Exception:
            pass
    await m.answer("✅ Murojaatingiz yuborildi.")

async def stub(m: Message):
    await m.answer("Bu bo'lim tez orada qo'shiladi.")

# Menyu tugmalari istalgan holatda state'ni tozalab ishlaydi
ROUTES = {
    B_MENU: show_bonus_menu, B_HOME: show_home, B_PROFILE: profile, B_LANG: language,
    B_DAILY: daily_bonus, B_QUIZ: daily_quiz, B_SHOP: shop, B_SHARE: share,
    B_MY_BATTLES: games.my_battles, B_MY_CONTESTS: games.my_contests, B_GUIDE: stub,
}
STATE_ROUTES = {B_PROMO: promo_ask, B_SUPPORT: support_ask,
                B_BATTLE: games.battle_start, B_CONTEST: games.contest_start}

@dp.message(F.text.in_(set(ROUTES) | set(STATE_ROUTES)))
async def buttons(m: Message, state: FSMContext):
    await state.clear()
    register(m.from_user)
    if m.text in ROUTES:
        await ROUTES[m.text](m)
    else:
        await STATE_ROUTES[m.text](m, state)

# ====================== ADMIN PANEL ======================
def is_admin(m: Message) -> bool:
    return m.from_user.id in ADMIN_IDS

@dp.message(Command("admin"), F.func(is_admin))
async def admin_open(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Admin panel</b>", reply_markup=admin_menu())
    await send_web_panel(m)

async def send_web_panel(m: Message):
    # initData faqat INLINE tugma orqali ochilgan Web App'da bo'ladi (reply klaviatura tugmasida yo'q)
    if not games.WEBAPP_URL:
        return await m.answer("⚠️ Web panel uchun Render'da <b>WEBAPP_URL</b> ni sozlang (https://...onrender.com).")
    await m.answer("🖥 <b>Web panel</b>: statistika, adminlar va premium emoji boshqaruvi.",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                       games.ibi("web", "Web panelni ochish", web=f"{games.WEBAPP_URL}/admin")]]))

@dp.message(F.text == A_WEB, F.func(is_admin))
async def admin_web(m: Message):
    await send_web_panel(m)

@dp.message(F.text == A_EXIT, F.func(is_admin))
async def admin_exit(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Chiqildi.", reply_markup=main_menu())

@dp.message(F.text == A_STATS, F.func(is_admin))
async def admin_stats(m: Message):
    total = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    new = db.execute("SELECT COUNT(*) c FROM users WHERE joined=?", (today(),)).fetchone()["c"]
    banned = db.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
    pts = db.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
    nb = db.execute("SELECT COUNT(*) c FROM battles").fetchone()["c"]
    nc = db.execute("SELECT COUNT(*) c FROM contests").fetchone()["c"]
    await m.answer(f"📊 <b>Statistika</b>\nJami: <b>{total}</b>\nBugun: <b>{new}</b>\n"
                   f"Bloklangan: <b>{banned}</b>\nJami ballar: <b>{pts}</b>\n\n"
                   f"⚔️ Battlelar: <b>{nb}</b>\n🏆 Konkurslar: <b>{nc}</b>\n"
                   f"📣 Ulangan kanallar: <b>{len(connected_channels())}</b>\n"
                   f"🔒 Majburiy kanallar: <b>{len(req_channels())}</b>")

ASK = {
    A_PROMO: (S.a_promo, "🎟 Format: <code>KOD BALL LIMIT</code>\nMasalan: <code>YANGI50 50 100</code>"),
    A_QUIZ: (S.a_quiz, "🧠 Format:\n<code>Savol | var1 | var2 | var3 | var4 | to'g'ri_raqam</code>\n"
                       "Masalan: <code>2+2? | 3 | 4 | 5 | 6 | 2</code>"),
    A_SHOP: (S.a_shop, "🛒 Format: <code>Nomi | narx</code>\nMasalan: <code>Telegram Premium | 500</code>"),
    A_POINTS: (S.a_points, "🪙 Format: <code>user_id ball</code>\nAyirish uchun minus: <code>123456 -10</code>"),
    A_BAN: (S.a_ban, "⛔ Bloklanadigan user ID:"),
    A_UNBAN: (S.a_unban, "✅ Blokdan chiqariladigan user ID:"),
}

@dp.message(F.text.in_(set(ASK)), F.func(is_admin))
async def admin_ask(m: Message, state: FSMContext):
    st, text = ASK[m.text]
    await state.set_state(st)
    await m.answer(text)

def connected_channels():
    """Battle yoki konkurs yaratilgan (ulangan) kanallar."""
    return db.execute("""SELECT channel_id AS id, MAX(channel_title) AS title, MAX(channel_username) AS username
        FROM (SELECT channel_id, channel_title, channel_username FROM battles
              UNION ALL SELECT channel_id, channel_title, channel_username FROM contests)
        GROUP BY channel_id""").fetchall()

def is_admin_cb(c: CallbackQuery) -> bool:
    return c.from_user.id in ADMIN_IDS

# ---------- XABAR YUBORISH ----------
BC_TARGETS = {"users": "👥 foydalanuvchilarga", "chans": "📣 ulangan kanallarga", "both": "👥📣 foydalanuvchilar va kanallarga"}

@dp.message(F.text == A_BROADCAST, F.func(is_admin))
async def admin_bc_menu(m: Message, state: FSMContext):
    await state.clear()
    nu = db.execute("SELECT COUNT(*) c FROM users WHERE banned=0").fetchone()["c"]
    nc = len(connected_channels())
    await m.answer("📢 <b>Xabar kimga yuboriladi?</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [games.ibi("bc_users", f"Foydalanuvchilarga ({nu})", cb="abc:users")],
        [games.ibi("bc_chans", f"Ulangan kanallarga ({nc})", cb="abc:chans")],
        [games.ibi("bc_both", "Ikkalasiga", cb="abc:both")]]))

@dp.callback_query(F.data.startswith("abc:"), F.func(is_admin_cb))
async def admin_bc_target(c: CallbackQuery, state: FSMContext):
    t = c.data[4:]
    if t not in BC_TARGETS:
        return await c.answer()
    await state.set_state(S.a_broadcast)
    await state.update_data(target=t)
    await c.answer()
    await c.message.answer(f"✍️ Yuboriladigan xabarni yuboring ({BC_TARGETS[t]}).\nMatn, rasm, video — hammasi bo'ladi. Bekor qilish: /cancel")

@dp.message(S.a_broadcast, F.func(is_admin))
async def admin_bc_preview(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.update_data(src=[m.chat.id, m.message_id])
    await m.answer(f"📨 Yuqoridagi xabar <b>{BC_TARGETS[d['target']]}</b> yuboriladi. Tasdiqlaysizmi?",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                       games.ibi("check", "Yuborish", cb="abcgo"),
                       games.ibi("cancel", "Bekor", cb="abcno")]]),
                   reply_parameters=ReplyParameters(message_id=m.message_id))

@dp.callback_query(F.data == "abcno", F.func(is_admin_cb))
async def admin_bc_no(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await c.message.edit_text("❌ Bekor qilindi.")

async def send_copy(bot: Bot, to: int, src_chat: int, src_msg: int) -> bool:
    for _ in range(2):
        try:
            await bot.copy_message(to, src_chat, src_msg)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception:
            return False
    return False

@dp.callback_query(F.data == "abcgo", F.func(is_admin_cb))
async def admin_bc_go(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if not d.get("src"):
        return await c.answer("Xabar topilmadi, qaytadan boshlang.", show_alert=True)
    await state.clear()
    await c.answer()
    await c.message.edit_text("⏳ Yuborilmoqda...")
    src_chat, src_msg = d["src"]
    t, report = d["target"], []
    if t in ("users", "both"):
        ids = [r["id"] for r in db.execute("SELECT id FROM users WHERE banned=0")]
        ok = 0
        for uid in ids:
            ok += await send_copy(bot, uid, src_chat, src_msg)
            await asyncio.sleep(0.05)
        report.append(f"👥 Foydalanuvchilar: <b>{ok}/{len(ids)}</b>")
    if t in ("chans", "both"):
        chs = connected_channels()
        ok, fail = 0, []
        for ch in chs:
            if await send_copy(bot, ch["id"], src_chat, src_msg):
                ok += 1
            else:
                fail.append(ch["title"] or str(ch["id"]))
            await asyncio.sleep(0.1)
        report.append(f"📣 Kanallar: <b>{ok}/{len(chs)}</b>")
        if fail:
            report.append("⚠️ Yuborilmadi (bot admin emas?): " + ", ".join(fail[:10]))
    await c.message.edit_text("✅ <b>Tugadi</b>\n\n" + "\n".join(report))

# ---------- MAJBURIY KANALLAR ----------
def req_view():
    rows = req_channels()
    text = ("🔒 <b>Majburiy kanallar</b>\n\nBotdan foydalanish uchun obuna bo'lish shart bo'lgan kanallar.\n\n"
            + ("\n".join(f"{i}. {r['title']} — " + (f"@{r['username']}" if r["username"] else "yopiq kanal") for i, r in enumerate(rows, 1))
               if rows else "Hozircha yo'q: hamma botdan erkin foydalanadi."))
    kbd = [[games.ibi("del", r['title'], cb=f"ard:{r['chat_id']}")] for r in rows]
    kbd.append([games.ibi("add", "Kanal qo'shish", cb="arc")])
    return text, InlineKeyboardMarkup(inline_keyboard=kbd)

@dp.message(F.text == A_REQ, F.func(is_admin))
async def admin_req_open(m: Message, state: FSMContext):
    await state.clear()
    text, markup = req_view()
    await m.answer(text, reply_markup=markup)

@dp.callback_query(F.data == "arc", F.func(is_admin_cb))
async def admin_req_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.a_reqch)
    await c.answer()
    await c.message.answer("📢 Kanalni <code>@kanalnomi</code> ko'rinishida yuboring (yoki kanaldan xabar forward qiling).\n"
                           "Bot shu kanalda <b>administrator</b> bo'lishi va kanal ochiq (username'li) bo'lishi kerak.\n\nBekor qilish: /cancel")

@dp.callback_query(F.data.startswith("ard:"), F.func(is_admin_cb))
async def admin_req_del(c: CallbackQuery):
    if c.data[4:].lstrip("-").isdigit():
        db.execute("DELETE FROM req_channels WHERE chat_id=?", (int(c.data[4:]),))
        db.commit()
        _sub_ok.clear()
    await c.answer("O'chirildi")
    text, markup = req_view()
    await c.message.edit_text(text, reply_markup=markup)

async def resolve_req_channel(bot: Bot, m: Message):
    chat = None
    origin = getattr(m, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None):
        chat = origin.chat
    elif m.text and (m.text.strip().startswith("@") or m.text.strip().lstrip("-").isdigit()):
        t = m.text.strip()
        try:
            chat = await bot.get_chat(int(t) if t.lstrip("-").isdigit() else t)
        except Exception:
            return "❌ Kanal topilmadi. Username yoki ID ni tekshiring."
    else:
        return "❌ Kanalni @username yoki ID (-100…) ko'rinishida yuboring yoki kanaldan xabar forward qiling."
    try:
        me = await bot.me()
        if (await bot.get_chat_member(chat.id, me.id)).status != "administrator":
            return "❌ Bot bu kanalda administrator emas. Avval botni admin qiling."
    except Exception:
        return "❌ Tekshirib bo'lmadi. Bot kanalda admin ekanini tekshiring."
    link = None
    if not chat.username:     # yopiq kanal: obuna havolasini bot o'zi yaratadi
        try:
            link = (await bot.create_chat_invite_link(chat.id, name="Bot")).invite_link
        except Exception:
            return "❌ Havola yaratib bo'lmadi: botga «Foydalanuvchilarni taklif qilish» huquqini bering."
    return {"id": chat.id, "title": chat.title or chat.username or str(chat.id), "username": chat.username or "", "link": link}

@dp.message(S.a_reqch, F.func(is_admin))
async def admin_req_save(m: Message, state: FSMContext, bot: Bot):
    res = await resolve_req_channel(bot, m)
    if isinstance(res, str):
        return await m.answer(res)
    db.execute("INSERT OR REPLACE INTO req_channels(chat_id,title,username,kind,link) VALUES(?,?,?,'normal',?)",
               (res["id"], res["title"], res["username"], res["link"]))
    db.commit()
    _sub_ok.clear()
    await state.clear()
    text, markup = req_view()
    await m.answer("✅ Qo'shildi.\n\n" + text, reply_markup=markup)

# ---------- ULANGAN KANALLAR ----------
@dp.message(F.text == A_CHANS, F.func(is_admin))
async def admin_chans(m: Message):
    chs = connected_channels()
    if not chs:
        return await m.answer("📋 Hozircha ulangan kanallar yo'q (hali battle yoki konkurs yaratilmagan).")
    lines = []
    for i, ch in enumerate(chs[:40], 1):
        nb = db.execute("SELECT COUNT(*) c FROM battles WHERE channel_id=?", (ch["id"],)).fetchone()["c"]
        nc = db.execute("SELECT COUNT(*) c FROM contests WHERE channel_id=?", (ch["id"],)).fetchone()["c"]
        un = f"@{ch['username']}" if ch["username"] else str(ch["id"])
        lines.append(f"{i}. {ch['title']} — {un}  (⚔️ {nb} · 🏆 {nc})")
    more = f"\n\n… yana {len(chs) - 40} ta" if len(chs) > 40 else ""
    await m.answer(f"📋 <b>Ulangan kanallar: {len(chs)}</b>\n\n" + "\n".join(lines) + more)

def promos_view():
    rows = db.execute("SELECT rowid AS rid, * FROM promos ORDER BY rowid DESC LIMIT 40").fetchall()
    text = "🎟 <b>Promokodlar</b>\n\n" + ("\n".join(
        f"<code>{r['code']}</code>: {r['points']} ball · ishlatilgan <b>{r['used']}/{r['max_uses']}</b>" for r in rows)
        if rows else "Hozircha yo'q.")
    return text, InlineKeyboardMarkup(inline_keyboard=[[games.ibi("del", r["code"], cb=f"apd:{r['rid']}")] for r in rows])

def shop_view():
    rows = db.execute("SELECT * FROM shop ORDER BY id DESC LIMIT 40").fetchall()
    text = "🛍 <b>Ball do'koni mahsulotlari</b>\n\n" + ("\n".join(f"{r['title']}: <b>{r['price']}</b> ball" for r in rows)
                                                    if rows else "Hozircha yo'q.")
    return text, InlineKeyboardMarkup(inline_keyboard=[[games.ibi("del", f"{r['title']} ({r['price']})", cb=f"asd:{r['id']}")] for r in rows])

@dp.message(F.text == A_PROMOS, F.func(is_admin))
async def admin_promos(m: Message):
    text, markup = promos_view()
    await m.answer(text + "\n\nO'chirish uchun tugmani bosing 👇" if markup.inline_keyboard else text, reply_markup=markup)

@dp.callback_query(F.data.startswith("apd:"), F.func(is_admin_cb))
async def admin_promo_del(c: CallbackQuery):
    r = db.execute("SELECT code FROM promos WHERE rowid=?", (c.data[4:],)).fetchone()
    if r:
        db.execute("DELETE FROM promos WHERE code=?", (r["code"],))
        db.execute("DELETE FROM promo_uses WHERE code=?", (r["code"],))
        db.commit()
    await c.answer("O'chirildi")
    text, markup = promos_view()
    await c.message.edit_text(text, reply_markup=markup)

@dp.message(F.text == A_SHOPLIST, F.func(is_admin))
async def admin_shoplist(m: Message):
    text, markup = shop_view()
    await m.answer(text + "\n\nO'chirish uchun tugmani bosing 👇" if markup.inline_keyboard else text, reply_markup=markup)

@dp.callback_query(F.data.startswith("asd:"), F.func(is_admin_cb))
async def admin_shop_del(c: CallbackQuery):
    db.execute("DELETE FROM shop WHERE id=?", (c.data[4:],))
    db.commit()
    await c.answer("O'chirildi")
    text, markup = shop_view()
    await c.message.edit_text(text, reply_markup=markup)

@dp.message(S.a_promo, F.func(is_admin))
async def do_promo(m: Message, state: FSMContext):
    try:
        code, pts, limit = m.text.split()
        db.execute("INSERT OR REPLACE INTO promos(code,points,max_uses,used) VALUES(?,?,?,0)",
                   (code.upper(), int(pts), int(limit)))
        db.commit()
    except Exception:
        return await m.answer("❌ Format xato. Qayta urinib ko'ring.")
    await state.clear()
    await m.answer("✅ Promokod qo'shildi.")

@dp.message(S.a_quiz, F.func(is_admin))
async def do_quiz(m: Message, state: FSMContext):
    try:
        parts = [p.strip() for p in m.text.split("|")]
        q, opts, correct = parts[0], parts[1:-1], int(parts[-1]) - 1
        assert 2 <= len(opts) <= 6 and 0 <= correct < len(opts)
        db.execute("INSERT INTO quiz(question,options,correct) VALUES(?,?,?)",
                   (q, json.dumps(opts, ensure_ascii=False), correct))
        db.commit()
    except Exception:
        return await m.answer("❌ Format xato. Qayta urinib ko'ring.")
    await state.clear()
    await m.answer("✅ Savol qo'shildi.")

@dp.message(S.a_shop, F.func(is_admin))
async def do_shop(m: Message, state: FSMContext):
    try:
        title, price = [p.strip() for p in m.text.split("|")]
        db.execute("INSERT INTO shop(title,price) VALUES(?,?)", (title, int(price)))
        db.commit()
    except Exception:
        return await m.answer("❌ Format xato. Qayta urinib ko'ring.")
    await state.clear()
    await m.answer("✅ Mahsulot qo'shildi.")

@dp.message(S.a_points, F.func(is_admin))
async def do_points(m: Message, state: FSMContext):
    try:
        uid, n = m.text.split()
        assert get_user(int(uid))
        add_points(int(uid), int(n))
    except Exception:
        return await m.answer("❌ Format xato yoki user topilmadi.")
    await state.clear()
    await m.answer("✅ Bajarildi.")

async def set_ban(m: Message, state: FSMContext, val: int):
    if not (m.text or "").strip().isdigit() or not get_user(int(m.text)):
        return await m.answer("❌ User topilmadi.")
    db.execute("UPDATE users SET banned=? WHERE id=?", (val, int(m.text)))
    db.commit()
    await state.clear()
    await m.answer("✅ Bajarildi.")

@dp.message(S.a_ban, F.func(is_admin))
async def do_ban(m: Message, state: FSMContext):
    await set_ban(m, state, 1)

@dp.message(S.a_unban, F.func(is_admin))
async def do_unban(m: Message, state: FSMContext):
    await set_ban(m, state, 0)

# ====================== PREMIUM EMOJI ID OLISH (admin uchun) ======================
def _has_custom_emoji(m: Message) -> bool:
    return bool(m.from_user) and m.from_user.id in ADMIN_IDS and any(e.type == "custom_emoji" for e in (m.entities or []))

@dp.message(StateFilter(None), F.func(_has_custom_emoji))
async def emoji_ids(m: Message):
    ents = [e for e in m.entities if e.type == "custom_emoji"]
    lines = [f"{i}) <code>{e.custom_emoji_id}</code>" for i, e in enumerate(ents, 1)]
    await m.answer("🆔 Premium emoji ID'lari (yuborilgan tartibda):\n\n" + "\n".join(lines))

# ====================== RENDER UCHUN WEB SERVER ======================
_web_refs = []

async def health(_):
    return web.Response(text="ok")

async def run_web(bot):
    app = web.Application()
    app.router.add_get("/", health)
    webapp.setup(app, bot, BOT_TOKEN)
    adminpanel.setup(app, bot, BOT_TOKEN, db=db, admin_ids=ADMIN_IDS, env_admins=ENV_ADMINS, on_req_change=_sub_ok.clear,
                     connected_channels=connected_channels, req_channels=req_channels)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()
    _web_refs.extend([runner, site])   # GC o'chirib yubormasligi uchun

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await run_web(bot)
    dp.include_router(games.router)
    games.start_background(bot)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
