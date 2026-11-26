"""Konkurs va Battle moduli (bot.py ga router sifatida ulanadi)."""
import asyncio
import re
import html
import json
import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyParameters, WebAppInfo)

from emojis import FALLBACK, label as emoji_label, pid

log = logging.getLogger("games")
router = Router()
TZ = timezone(timedelta(hours=5))
BOOST_BONUS = 1.25
WEBAPP_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")   # Render URL ni o'zi beradi   # masalan https://mening-botim.onrender.com
DEVICE_ON = bool(WEBAPP_URL)                           # bo'sh bo'lsa qurilma tekshiruvi o'chiq
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
MEDALS = ["🥇", "🥈", "🥉"]

from dbpath import DB_PATH
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS contests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner INTEGER, src_chat INTEGER, src_msg INTEGER,
  btn_text TEXT, btn_style TEXT, winners INTEGER, end_kind TEXT, end_at INTEGER, end_count INTEGER,
  channel_id INTEGER, channel_title TEXT, channel_username TEXT, extra TEXT, sub_main INTEGER,
  captcha INTEGER, boost INTEGER, btn_pos TEXT, post_msg INTEGER, btn_msg INTEGER,
  status TEXT DEFAULT 'active', created INTEGER);
CREATE TABLE IF NOT EXISTS contest_users(
  contest_id INTEGER, user_id INTEGER, n INTEGER, boosted INTEGER DEFAULT 0,
  name TEXT, username TEXT, PRIMARY KEY(contest_id,user_id));
CREATE TABLE IF NOT EXISTS battles(
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner INTEGER, name TEXT, prize TEXT, end_kind TEXT,
  end_at INTEGER, end_votes INTEGER, lang TEXT, channel_id INTEGER, channel_title TEXT,
  channel_username TEXT, extra TEXT, post_msg INTEGER, status TEXT DEFAULT 'active', created INTEGER);
CREATE TABLE IF NOT EXISTS b_part(
  battle_id INTEGER, user_id INTEGER, name TEXT, username TEXT, joined INTEGER,
  PRIMARY KEY(battle_id,user_id));
CREATE TABLE IF NOT EXISTS b_votes(
  battle_id INTEGER, voter INTEGER, cand INTEGER, vname TEXT, ts INTEGER,
  PRIMARY KEY(battle_id,voter));
CREATE TABLE IF NOT EXISTS b_attempts(battle_id INTEGER, user_id INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS b_dev(battle_id INTEGER, root INTEGER, strikes INTEGER, PRIMARY KEY(battle_id,root));
CREATE TABLE IF NOT EXISTS b_removed(battle_id INTEGER, user_id INTEGER, PRIMARY KEY(battle_id,user_id));
CREATE TABLE IF NOT EXISTS user_dev(
  user_id INTEGER PRIMARY KEY, dev_id TEXT, fp TEXT, ip_h TEXT, name TEXT, username TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS pending(
  user_id INTEGER PRIMARY KEY, kind TEXT, a INTEGER, b INTEGER);
""")
db.commit()

# ====================== YORDAMCHILAR ======================
def now_ts(): return int(time.time())
def fmt_ts(ts): return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")
def esc(s): return html.escape(s or "")
def q1(sql, *a): return db.execute(sql, a).fetchone()
def qa(sql, *a): return db.execute(sql, a).fetchall()
def ex(sql, *a):
    cur = db.execute(sql, a)
    db.commit()
    return cur

def parse_dt(s):
    try:
        ts = int(datetime.strptime(s.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TZ).timestamp())
        return ts if ts > now_ts() else None
    except Exception:
        return None

def ib(text, cb=None, url=None, style=None, web=None, icon=None):
    kw = {"style": style} if style and style != "default" else {}
    return InlineKeyboardButton(text=text, callback_data=cb, url=url,
                                web_app=WebAppInfo(url=web) if web else None, **kw)

CHANNEL_PREMIUM = os.getenv("CHANNEL_PREMIUM", "") == "1"   # Telegram: kanallarda premium emoji faqat Fragment username'li botlarga ruxsat

def ibi(key, text, cb=None, ch=False, **kw):
    if ch and not CHANNEL_PREMIUM:   # kanal posti: oddiy emoji (aks holda Telegram xato berishi mumkin)
        return ib(f"{FALLBACK.get(key, '')} {text}".strip(), cb=cb, **kw)
    """Premium emoji ikonkali inline tugma (ID yo'q bo'lsa oddiy emoji matnda)."""
    return ib(emoji_label(key, text), cb=cb, icon=key, **kw)

def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
CANCEL = ibi("cancel", "Bekor qilish", cb="cancel", style="danger")
CANCEL_KB = kb([[CANCEL]])

_tasks, _pending = set(), set()
def debounce(key, fn, delay=3):
    """Tugmalarni yangilashni jamlab, Telegram limitidan oshmaslik uchun."""
    if key in _pending:
        return
    _pending.add(key)
    async def run():
        await asyncio.sleep(delay)
        _pending.discard(key)
        try:
            await fn()
        except Exception as e:
            log.warning("refresh %s: %s", key, e)
    t = asyncio.create_task(run())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)

async def resolve_channel(bot: Bot, m: Message, owner_id: int):
    """@username yoki forward qilingan xabardan kanalni topadi. dict yoki xato matni qaytaradi."""
    chat = None
    origin = getattr(m, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None):
        chat = origin.chat
    elif m.text and m.text.strip().startswith("@"):
        try:
            chat = await bot.get_chat(m.text.strip())
        except Exception:
            return "❌ Kanal topilmadi. Username'ni tekshiring."
    else:
        return "❌ Kanalni @username ko'rinishida yuboring yoki kanaldan xabar forward qiling."
    return await check_channel(bot, chat, owner_id)

async def check_channel(bot: Bot, chat, owner_id: int):
    """Kanal ochiqmi, bot va egasi admin ekanini tekshiradi. dict yoki xato matni qaytaradi."""
    if not chat.username:
        return "❌ Kanal ochiq (public, username'li) bo'lishi kerak."
    try:
        me = await bot.me()
        bm = await bot.get_chat_member(chat.id, me.id)
        if bm.status != "administrator":
            return "❌ Bot bu kanalda administrator emas. Avval botni admin qiling."
        um = await bot.get_chat_member(chat.id, owner_id)
        if um.status not in ("creator", "administrator"):
            return "❌ Siz bu kanalda administrator emassiz."
    except Exception:
        return "❌ Tekshirib bo'lmadi. Bot kanalda admin ekanini tekshiring."
    return {"id": chat.id, "title": chat.title or chat.username, "username": chat.username}

async def not_subscribed(bot: Bot, user_id: int, chans):
    bad = []
    for c in chans:
        try:
            mem = await bot.get_chat_member(c["id"], user_id)
            if mem.status in ("left", "kicked"):
                bad.append(c)
        except Exception:
            bad.append(c)
    return bad

SUB_TEXT = ("❌ Qatnashishdan oldin quyidagi kanal/guruhlarga qo'shiling 👇\n"
            "Qo'shilgach, «Tekshirish» tugmasini bosing.")

def _curl(c):
    try:
        link = c["link"]
    except (KeyError, IndexError):
        link = None
    return link or f"https://t.me/{c['username']}"

def sub_kb(bad, cb):
    rows = [[ib(f"📢 {c['title']}", url=_curl(c))] for c in bad]
    rows.append([ibi("check", "Tekshirish", cb=cb, style="success")])
    return kb(rows)

async def reply(bot, uid, text, markup=None, cb: CallbackQuery | None = None):
    """cb bo'lsa xabarni tahrirlaydi, bo'lmasa yangi xabar yuboradi."""
    if cb is not None:
        try:
            await cb.message.edit_text(text, reply_markup=markup)
            return
        except Exception as e:
            if "not modified" in str(e):
                return
    await bot.send_message(uid, text, reply_markup=markup)

# ====================== UMUMIY: BEKOR QILISH ======================
@router.callback_query(F.data == "cancel")
async def cancel_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await c.message.answer("❌ Bekor qilindi.\n\nBosh menyu")

@router.callback_query(F.data == "ended")
async def ended_cb(c: CallbackQuery):
    await c.answer("🏁 Yakunlangan.", show_alert=True)

# ====================== KONKURS: YARATISH ======================
class CS(StatesGroup):
    post = State()
    btn = State()
    style = State()
    subs = State()
    winners = State()
    kind = State()
    end_time = State()
    end_count = State()
    chan = State()
    check = State()

BTN_PRESETS = ["Qatnashaman!", "Qatnashish", "Ishtirok etish"]

async def contest_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CS.post)
    await m.answer("🏆 <b>Konkurs yaratish</b>\n\n❌ Bekor qilish: /cancel")
    await m.answer("📝 Konkurs uchun post yuboring: matn, rasm, video yoki GIF (bittadan). "
                   "Formatlash saqlanadi.", reply_markup=CANCEL_KB)

@router.message(CS.post)
async def c_post(m: Message, state: FSMContext):
    if m.media_group_id:
        return await m.answer("⚠️ Albom hozircha qo'llab-quvvatlanmaydi. Bitta rasm, video, GIF yoki matn yuboring.")
    if not (m.text or m.photo or m.video or m.animation):
        return await m.answer("❌ Matn, rasm, video yoki GIF yuboring.")
    await state.update_data(src_chat=m.chat.id, src_msg=m.message_id)
    await state.set_state(CS.btn)
    rows = [[ib(t, cb=f"cbt:{i}")] for i, t in enumerate(BTN_PRESETS)]
    await m.answer("✏️ Tugmada ko'rinadigan matnni yuboring yoki quyidagi variantlardan birini tanlang.\n\n"
                   "‼️ Tugma qayerda bo'lishi (post ostida yoki postning pastida) oxirida, saqlashdan oldin tanlanadi.",
                   reply_markup=kb(rows + [[CANCEL]]))

async def ask_style(target, state):
    await state.set_state(CS.style)
    rows = [[ib("⚪ Oddiy", cb="cst:default"), ib("🔵", cb="cst:primary", style="primary"),
             ib("🔴", cb="cst:danger", style="danger"), ib("🟢", cb="cst:success", style="success")]]
    await target.answer("✅ Tugma matni saqlandi.\n\n🎨 Endi tugma rangini tanlang 👇", reply_markup=kb(rows))

@router.callback_query(CS.btn, F.data.startswith("cbt:"))
async def c_btn_preset(c: CallbackQuery, state: FSMContext):
    await state.update_data(btn_text=BTN_PRESETS[int(c.data[4:])])
    await c.answer()
    await ask_style(c.message, state)

@router.message(CS.btn, F.text)
async def c_btn_text(m: Message, state: FSMContext):
    if len(m.text) > 40:
        return await m.answer("❌ Tugma matni 40 belgidan oshmasin.")
    await state.update_data(btn_text=m.text.strip())
    await ask_style(m, state)

@router.callback_query(CS.style, F.data.startswith("cst:"))
async def c_style(c: CallbackQuery, state: FSMContext):
    await state.update_data(btn_style=c.data[4:])
    await c.answer()
    await state.set_state(CS.subs)
    await c.message.answer(
        "📢 <b>Majburiy obuna</b>\n\nFoydalanuvchilar qatnashish uchun obuna bo'lishi kerak bo'lgan "
        "kanallarni qo'shing: kanalni <code>@kanalnomi</code> ko'rinishida yuboring (yoki kanaldan xabar forward qiling).\n"
        "Bot ham, siz ham u kanalda admin bo'lishingiz kerak.\n\n"
        "❗ Agar kanallarsiz qatnashish mumkin bo'lishini istasangiz, quyidagi tugmani bosing:",
        reply_markup=kb([[ibi("nosub", "Konkurs majburiy obunalarsiz", cb="csub:none", style="danger")],
                         [ibi("next", "Faqat konkurs kanaliga obuna bilan davom etish", cb="csub:main", style="success")],
                         [CANCEL]]))

@router.message(CS.subs)
async def c_subs_add(m: Message, state: FSMContext, bot: Bot):
    res = await resolve_channel(bot, m, m.from_user.id)
    if isinstance(res, str):
        return await m.answer(res)
    d = await state.get_data()
    extra = d.get("extra", [])
    if all(x["id"] != res["id"] for x in extra):
        extra.append(res)
    await state.update_data(extra=extra)
    names = ", ".join("@" + x["username"] for x in extra)
    await m.answer(f"✅ Qo'shildi. Majburiy kanallar: {names}\nYana qo'shing yoki davom eting:",
                   reply_markup=kb([[ibi("next", "Davom etish", cb="csub:main", style="success")], [CANCEL]]))

@router.callback_query(CS.subs, F.data.startswith("csub:"))
async def c_subs_go(c: CallbackQuery, state: FSMContext):
    if c.data == "csub:none":
        await state.update_data(sub_main=0, extra=[])
    else:
        await state.update_data(sub_main=1)
    await c.answer()
    d = await state.get_data()
    if d.get("winners") and d.get("chan"):
        return await show_check(c.message, state)
    await state.set_state(CS.winners)
    await c.message.answer("🏆 Bot nechta g'olib tanlasin?\n\nRaqam yuboring (1 dan 100 gacha).", reply_markup=CANCEL_KB)

@router.message(CS.winners, F.text)
async def c_winners(m: Message, state: FSMContext):
    if not m.text.strip().isdigit() or not 1 <= int(m.text) <= 100:
        return await m.answer("❌ 1 dan 100 gacha raqam yuboring.")
    await state.update_data(winners=int(m.text))
    await m.answer("⭐ G'oliblar soni saqlandi.")
    await ask_kind(m, state)

async def ask_kind(m: Message, state: FSMContext):
    await state.set_state(CS.kind)
    await m.answer("🏁 Konkurs qanday yakunlansin?",
                   reply_markup=kb([[ibi("time", "Vaqt bilan", cb="ck:time")],
                                    [ibi("count", "Ishtirokchilar soni bilan", cb="ck:count")], [CANCEL]]))

@router.callback_query(CS.kind, F.data.startswith("ck:"))
async def c_kind(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if c.data == "ck:time":
        await state.update_data(end_kind="time")
        await state.set_state(CS.end_time)
        await c.message.answer("🕒 Tugash vaqtini yozing:\n\nMisol: <code>07.10.2026 15:00</code>\n\n"
                               "Vaqt O'zbekiston vaqti (UTC+5) bo'yicha.", reply_markup=CANCEL_KB)
    else:
        await state.update_data(end_kind="count")
        await state.set_state(CS.end_count)
        await c.message.answer("👥 Nechta ishtirokchi yetganda konkurs yakunlansin?\n\nMasalan: 100", reply_markup=CANCEL_KB)

async def after_end(m: Message, state: FSMContext):
    d = await state.get_data()
    if d.get("chan"):
        return await show_check(m, state)
    await state.set_state(CS.chan)
    await m.answer("📢 <b>E'lon kanali</b>\n\nKonkurs e'lon qilinadigan kanalni <code>@kanalnomi</code> ko'rinishida "
                   "yuboring (yoki kanaldan xabar forward qiling).\nBot va siz kanalda admin bo'lishingiz kerak.",
                   reply_markup=CANCEL_KB)

@router.message(CS.end_time, F.text)
async def c_end_time(m: Message, state: FSMContext):
    ts = parse_dt(m.text)
    if not ts:
        return await m.answer("❌ Format noto'g'ri yoki vaqt o'tib ketgan. Masalan: <code>07.10.2026 15:00</code>")
    await state.update_data(end_at=ts)
    await m.answer("⭐ Tugash vaqti saqlandi.")
    await after_end(m, state)

@router.message(CS.end_count, F.text)
async def c_end_count(m: Message, state: FSMContext):
    if not m.text.strip().isdigit() or not 1 <= int(m.text) <= 1000000:
        return await m.answer("❌ Raqam yuboring.")
    await state.update_data(end_count=int(m.text))
    await m.answer("⭐ Saqlandi.")
    await after_end(m, state)

@router.message(CS.chan)
async def c_chan(m: Message, state: FSMContext, bot: Bot):
    res = await resolve_channel(bot, m, m.from_user.id)
    if isinstance(res, str):
        return await m.answer(res)
    await state.update_data(chan=res, pos="under", captcha=0, boost=0)
    await show_check(m, state)

def c_check_text(d):
    if d["end_kind"] == "time":
        end = f"🕒 Konkurs <b>{fmt_ts(d['end_at'])}</b> da yakunlanadi (UTC+5)"
    else:
        end = f"👥 Ishtirokchilar soni <b>{d['end_count']}</b> taga yetganda konkurs yakunlanadi"
    subs = []
    if d.get("sub_main"):
        subs.append("@" + d["chan"]["username"])
    subs += ["@" + x["username"] for x in d.get("extra", [])]
    pos = "post ostida" if d["pos"] == "under" else "postning pastida (alohida xabar)"
    return ("🧐 <b>Konkursni diqqat bilan qayta tekshiring</b>\n\n"
            f"{end}\n🏆 G'oliblar soni: <b>{d['winners']}</b>\n"
            f"📢 E'lon kanali: {esc(d['chan']['title'])}\n"
            f"🔒 Majburiy obuna: {', '.join(subs) if subs else 'yo`q'}\n\n"
            f"‼️ Qatnashish tugmasi: <b>{pos}</b>.\nTugma joyini pastdagi «Tugma joylashuvi» tugmasi bilan o'zgartirish mumkin.")

def c_check_kb(d):
    pos = "post ostida" if d["pos"] == "under" else "postning pastida"
    return kb([[ib(f"‼️ Tugma joylashuvi: {pos}", cb="ct:pos", style="primary")],
               [ib(("✅" if d["captcha"] else "❌") + " 📱 Qurilmani tasdiqlash", cb="ct:captcha")],
               [ib(("✅" if d["boost"] else "❌") + " Omad busti", cb="ct:boost")],
               [ibi("save", "Konkursni saqlash", cb="ct:save", style="success")],
               [ibi("swap", "Yakunlash usulini almashtirish", cb="ct:kind", style="primary")],
               [CANCEL]])

async def show_check(m: Message, state: FSMContext, edit: bool = False):
    await state.set_state(CS.check)
    d = await state.get_data()
    if edit:
        try:
            return await m.edit_text(c_check_text(d), reply_markup=c_check_kb(d))
        except Exception:
            return
    await m.answer(c_check_text(d), reply_markup=c_check_kb(d))

@router.callback_query(CS.check, F.data.startswith("ct:"))
async def c_check_actions(c: CallbackQuery, state: FSMContext, bot: Bot):
    act = c.data[3:]
    d = await state.get_data()
    if act == "pos":
        await state.update_data(pos="below" if d["pos"] == "under" else "under")
    elif act == "captcha":
        await state.update_data(captcha=0 if d["captcha"] else 1)
        if not DEVICE_ON and not d["captcha"]:
            await c.answer("⚠️ WEBAPP_URL sozlanmagan, tekshiruv hozircha ishlamaydi.", show_alert=True)
            return await show_check(c.message, state, edit=True)
    elif act == "boost":
        await state.update_data(boost=0 if d["boost"] else 1)
    elif act == "kind":
        await c.answer()
        return await ask_kind(c.message, state)
    elif act == "save":
        return await c_save(c, state, bot)
    await c.answer()
    await show_check(c.message, state, edit=True)

def contest_markup(c, bot_username, count=0, ended=False):
    if ended:
        return kb([[ibi("cend", "Konkurs yakunlangan", cb="ended", style="danger", ch=True)]])
    text = c["btn_text"] + (f" ({count})" if count else "")
    return kb([[ib(text, url=f"https://t.me/{bot_username}?start=join_{c['id']}", style=c["btn_style"])]])

async def c_save(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    ch = d["chan"]
    cur = ex("""INSERT INTO contests(owner,src_chat,src_msg,btn_text,btn_style,winners,end_kind,end_at,end_count,
        channel_id,channel_title,channel_username,extra,sub_main,captcha,boost,btn_pos,created)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             c.from_user.id, d["src_chat"], d["src_msg"], d["btn_text"], d["btn_style"], d["winners"],
             d["end_kind"], d.get("end_at"), d.get("end_count"), ch["id"], ch["title"], ch["username"],
             json.dumps(d.get("extra", [])), d.get("sub_main", 0), d["captcha"], d["boost"], d["pos"], now_ts())
    cid = cur.lastrowid
    row = q1("SELECT * FROM contests WHERE id=?", cid)
    me = (await bot.me()).username
    try:
        markup = contest_markup(row, me)
        post = await bot.copy_message(ch["id"], d["src_chat"], d["src_msg"],
                                      reply_markup=markup if d["pos"] == "under" else None)
        btn_msg = post.message_id
        if d["pos"] == "below":
            b = await bot.send_message(ch["id"], "👇 Qatnashish uchun tugmani bosing", reply_markup=markup)
            btn_msg = b.message_id
        ex("UPDATE contests SET post_msg=?, btn_msg=? WHERE id=?", post.message_id, btn_msg, cid)
    except Exception as e:
        ex("DELETE FROM contests WHERE id=?", cid)
        await c.answer()
        return await c.message.answer(f"❌ Kanalga joylab bo'lmadi: {esc(str(e))}")
    await state.clear()
    await c.answer()
    await c.message.answer(f"⭐ <b>Konkurs e'lon qilindi!</b>\n\n📢 Kanal: {esc(ch['title'])}\n#️⃣ Raqami: #{cid}")

# ====================== KONKURS: QATNASHISH ======================
def c_chans(c):
    out = []
    if c["sub_main"]:
        out.append({"id": c["channel_id"], "title": c["channel_title"], "username": c["channel_username"]})
    return out + json.loads(c["extra"] or "[]")

def boost_kb(c):
    return kb([[ibi("boost", "Boost berish", url=f"https://t.me/{c['channel_username']}?boost"),
                ibi("boostchk", "Boostni tekshirish", cb=f"boost:{c['id']}", style="success")]])

BOOST_TEXT = ("\n\n🚀 +25% qo'shimcha yutish imkoniyati uchun pastdagi «Boost berish» tugmasini bosing, "
              "so'ng «Boostni tekshirish»ni bosing.")

async def contest_join(bot: Bot, u, cid: int, state: FSMContext | None = None, cb: CallbackQuery | None = None):
    c = q1("SELECT * FROM contests WHERE id=?", cid)
    if not c or c["status"] != "active":
        return await reply(bot, u.id, "❌ Bu konkurs yakunlangan yoki topilmadi.", cb=cb)
    row = q1("SELECT n FROM contest_users WHERE contest_id=? AND user_id=?", cid, u.id)
    if row:
        text = f"✅ Siz allaqachon qatnashgansiz ({row['n']}-ishtirokchi)." + (BOOST_TEXT if c["boost"] else "")
        return await reply(bot, u.id, text, boost_kb(c) if c["boost"] else None, cb)
    bad = await not_subscribed(bot, u.id, c_chans(c))
    if bad:
        return await reply(bot, u.id, SUB_TEXT, sub_kb(bad, f"chk:c:{cid}"), cb)
    if c["captcha"] and DEVICE_ON:
        if not await device_gate(bot, u, "c", cid, 0, cb):
            return
        other = contest_conflict(cid, u.id)
        if other:
            await reply(bot, u.id, dup_text(other, "qatnashgansiz"), cb=cb)
            await notify_dup(bot, f"Konkurs #{cid} ({c['channel_title']})", "qatnashmoqchi bo'ldi", u, other)
            return
    await contest_register(bot, u, c, cb)


async def contest_register(bot: Bot, u, c, cb=None):
    n = q1("SELECT COUNT(*) c FROM contest_users WHERE contest_id=?", c["id"])["c"] + 1
    ex("INSERT OR IGNORE INTO contest_users(contest_id,user_id,n,name,username) VALUES(?,?,?,?,?)",
       c["id"], u.id, n, u.full_name, u.username)
    text = f"✅ Siz {n}-bo'lib konkursga qatnashdingiz. Omad!" + (BOOST_TEXT if c["boost"] else "")
    await reply(bot, u.id, text, boost_kb(c) if c["boost"] else None, cb)
    debounce(("cbtn", c["id"]), lambda: refresh_contest_btn(bot, c["id"]))
    if c["end_kind"] == "count" and n >= c["end_count"]:
        await contest_finish(bot, c["id"])

async def refresh_contest_btn(bot: Bot, cid: int):
    c = q1("SELECT * FROM contests WHERE id=?", cid)
    if not c or c["status"] != "active":
        return
    cnt = q1("SELECT COUNT(*) c FROM contest_users WHERE contest_id=?", cid)["c"]
    me = (await bot.me()).username
    await bot.edit_message_reply_markup(chat_id=c["channel_id"], message_id=c["btn_msg"],
                                        reply_markup=contest_markup(c, me, cnt))

@router.callback_query(F.data.startswith("boost:"))
async def boost_check(c: CallbackQuery, bot: Bot):
    cid = int(c.data[6:])
    ct = q1("SELECT * FROM contests WHERE id=?", cid)
    if not ct or not q1("SELECT 1 FROM contest_users WHERE contest_id=? AND user_id=?", cid, c.from_user.id):
        return await c.answer("Avval konkursga qatnashing.", show_alert=True)
    try:
        res = await bot.get_user_chat_boosts(ct["channel_id"], c.from_user.id)
        ok = len(res.boosts) > 0
    except Exception:
        return await c.answer("❌ Tekshirib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)
    if ok:
        ex("UPDATE contest_users SET boosted=1 WHERE contest_id=? AND user_id=?", cid, c.from_user.id)
        await c.answer("✅ Boost topildi! Yutish imkoniyatingiz +25% oshdi.", show_alert=True)
    else:
        await c.answer("❌ Boost topilmadi. Avval «Boost berish» tugmasini bosing.", show_alert=True)

# ====================== KONKURS: YAKUNLASH ======================
def weighted_sample(items, weights, k):
    items, weights, out = list(items), list(weights), []
    for _ in range(k):
        i = random.choices(range(len(items)), weights)[0]
        out.append(items.pop(i))
        weights.pop(i)
    return out

async def contest_finish(bot: Bot, cid: int):
    c = q1("SELECT * FROM contests WHERE id=?", cid)
    if not c or c["status"] != "active":
        return
    ex("UPDATE contests SET status='done' WHERE id=?", cid)
    users = qa("SELECT * FROM contest_users WHERE contest_id=?", cid)
    winners = weighted_sample(users, [BOOST_BONUS if u["boosted"] else 1 for u in users],
                              min(c["winners"], len(users)))
    if winners:
        lines = []
        for i, w in enumerate(winners):
            medal = MEDALS[i] if i < 3 else "🏅"
            uname = f" (@{esc(w['username'])})" if w["username"] else ""
            lines.append(f"{medal} <a href=\"tg://user?id={w['user_id']}\">{esc(w['name'])}</a>{uname}")
        wtxt = "\n".join(lines)
    else:
        wtxt = "Ishtirokchilar bo'lmadi."
    text = (f"🏆 <b>KONKURS YAKUNLANDI!</b>\n\n🎉 <b>G'oliblar:</b>\n{wtxt}\n\n"
            f"👥 Jami ishtirokchilar: {len(users)}\n\n🍀 Qatnashganlarning barchasiga rahmat!")
    try:
        await bot.send_message(c["channel_id"], text, reply_parameters=ReplyParameters(message_id=c["post_msg"]))
        await bot.edit_message_reply_markup(chat_id=c["channel_id"], message_id=c["btn_msg"],
                                            reply_markup=contest_markup(c, "", ended=True))
    except Exception as e:
        log.warning("contest_finish post: %s", e)
    for w in winners:
        try:
            await bot.send_message(w["user_id"], f"🎉 Tabriklaymiz! Siz {esc(c['channel_title'])}dagi konkursda g'olib bo'ldingiz!")
        except Exception:
            pass
    try:
        await bot.send_message(c["owner"], "🏁 <b>Konkursingiz yakunlandi!</b>\n\n" + text)
    except Exception:
        pass

# ====================== BATTLE: YARATISH ======================
class BS(StatesGroup):
    name = State()
    prize = State()
    kind = State()
    votes = State()
    end_time = State()
    lang = State()
    extra = State()
    chan = State()

LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}

async def battle_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BS.name)
    await m.answer("🧑‍💻 <b>Battle yaratish</b>\n\n❌ Bekor qilish: /cancel")
    await m.answer("📝 Battle nomini kiriting\n\nMisol:\n• Yozgi batl 🔥", reply_markup=CANCEL_KB)

@router.message(BS.name, F.text)
async def b_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:100])
    await state.set_state(BS.prize)
    await m.answer("🎁 Sovrin matnini kiriting\n\nMisol:\n• 🥇 Top 1 ga gift\nAgar sovrin bo'lmasa \"-\" deb yuboring.",
                   reply_markup=CANCEL_KB)

@router.message(BS.prize, F.text)
async def b_prize(m: Message, state: FSMContext):
    await state.update_data(prize=m.text.strip()[:300])
    await state.set_state(BS.kind)
    await m.answer("🏁 Batl qanday tugasin?",
                   reply_markup=kb([[ibi("time", "Vaqt bilan", cb="bk:time")], [ibi("votes", "Ovoz soni bilan", cb="bk:votes")], [CANCEL]]))

@router.callback_query(BS.kind, F.data.startswith("bk:"))
async def b_kind(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if c.data == "bk:time":
        await state.update_data(end_kind="time")
        await state.set_state(BS.end_time)
        await c.message.answer("⏳ Tugash vaqtini yozing:\n\nMisol: <code>07.10.2026 15:00</code>\n\n"
                               "Vaqt O'zbekiston vaqti (UTC+5) bo'yicha.", reply_markup=CANCEL_KB)
    else:
        await state.update_data(end_kind="votes")
        await state.set_state(BS.votes)
        await c.message.answer("🎯 Nechta ovoz yig'ilganda tugasin?\n\nMasalan: 20", reply_markup=CANCEL_KB)

async def ask_lang(m: Message, state: FSMContext):
    await state.set_state(BS.lang)
    await m.answer("🌐 Kanaldagi batl posti qaysi tilda bo'lsin?\n\nTugmalar ham shu tilda chiqadi.",
                   reply_markup=kb([[ib(v, cb=f"bl:{k}")] for k, v in LANGS.items()] + [[CANCEL]]))

@router.message(BS.end_time, F.text)
async def b_end_time(m: Message, state: FSMContext):
    ts = parse_dt(m.text)
    if not ts:
        return await m.answer("❌ Format noto'g'ri yoki vaqt o'tib ketgan. Masalan: <code>07.10.2026 15:00</code>")
    await state.update_data(end_at=ts)
    await ask_lang(m, state)

@router.message(BS.votes, F.text)
async def b_votes(m: Message, state: FSMContext):
    if not m.text.strip().isdigit() or not 1 <= int(m.text) <= 1000000:
        return await m.answer("❌ Raqam yuboring.")
    await state.update_data(end_votes=int(m.text))
    await ask_lang(m, state)

@router.callback_query(BS.lang, F.data.startswith("bl:"))
async def b_lang(c: CallbackQuery, state: FSMContext):
    code = c.data[3:]
    await state.update_data(lang=code, extra=[])
    await c.answer()
    await c.message.answer(f"⭐ Post tili: {LANGS[code]}")
    await state.set_state(BS.extra)
    await c.message.answer(
        "📢 Ovoz berish va qatnashish uchun obuna bo'lish kerak bo'lgan <b>majburiy kanallarni</b> qo'shing.\n"
        "Batl o'tkaziladigan kanalga obuna bo'lish majburiy va sukut bo'yicha yoqilgan.\n\n"
        "Kanal qo'shish uchun:\n1. Botni kanalingizga administrator sifatida qo'shing (bot obunani tekshirishi uchun shart).\n"
        "2. Botga kanalni <code>@kanalnomi</code> ko'rinishida yuboring (yoki kanaldan xabarni forward qiling).\n\n"
        "Qo'shimcha kanal kerak bo'lmasa, quyidagi tugmani bosing 👇",
        reply_markup=kb([[ibi("next", "Qo'shimcha kanalsiz davom etish", cb="be:go", style="success")], [CANCEL]]))

@router.message(BS.extra)
async def b_extra_add(m: Message, state: FSMContext, bot: Bot):
    res = await resolve_channel(bot, m, m.from_user.id)
    if isinstance(res, str):
        return await m.answer(res)
    d = await state.get_data()
    extra = d.get("extra", [])
    if all(x["id"] != res["id"] for x in extra):
        extra.append(res)
    await state.update_data(extra=extra)
    await m.answer("✅ Qo'shildi: " + ", ".join("@" + x["username"] for x in extra) + "\nYana qo'shing yoki davom eting:",
                   reply_markup=kb([[ibi("next", "Davom etish", cb="be:go", style="success")], [CANCEL]]))

@router.callback_query(BS.extra, F.data == "be:go")
async def b_extra_go(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(BS.chan)
    await c.message.answer("⭐ Saqlandi.")
    await c.message.answer("📢 Kanal username kiriting:\nMisol: <code>@mystarchannel</code>", reply_markup=CANCEL_KB)

# ====================== BATTLE: POST ======================
def b_chans(b):
    return [{"id": b["channel_id"], "title": b["channel_title"], "username": b["channel_username"]}] + \
           json.loads(b["extra"] or "[]")

def label(r): return "@" + r["username"] if r["username"] else r["name"]

def standings(bid):
    return qa("""SELECT p.user_id uid, p.name, p.username, COUNT(v.voter) votes
                 FROM b_part p LEFT JOIN b_votes v ON v.battle_id=p.battle_id AND v.cand=p.user_id
                 WHERE p.battle_id=? GROUP BY p.user_id ORDER BY votes DESC, p.joined ASC""", bid)

def battle_end_line(b):
    if b["end_kind"] == "manual":
        return ""   # vaqt/ovoz chegarasi yo'q: egasi qo'lda to'xtatadi
    if b["end_kind"] == "votes":
        return f"🎯 <b>Birinchi ishtirokchi {b['end_votes']} ta ovoz yig'sa, batl avtomatik tugaydi.</b>"
    return f"⏳ <b>Batl {fmt_ts(b['end_at'])} da (UTC+5) avtomatik tugaydi.</b>"

def battle_text(b, bot_username):
    prize = "Hozircha Sir 🤫" if b["prize"].strip() == "-" else esc(b["prize"])
    return (f"🏆 <b>{esc(b['name'])}</b>\n\n@{bot_username} dan qilindi\n"
            "❗ <b>Konkurs shartlari:</b> shu kanalga obuna bo'lish va do'stlaringiz sizga ovoz berishini so'rashdan iborat.\n\n"
            "⚠️ Agar ovoz beruvchi kanaldan chiqib ketsa, ovozi avtomatik olib tashlanadi ⛔\n\n"
            f"🎁 <b>Konkursga qo'yilgan yutuqlar:</b> — {prize}\n\n"
            + (battle_end_line(b) + "\n\n" if battle_end_line(b) else "") +
            "➕ <b>Konkursga qo'shilish uchun quyidagi tugmani bosing</b> 👇")

def battle_markup(b, bot_username, ended=False):
    rows = [[ib(f"{label(p)} ({p['votes']})", url=f"https://t.me/{bot_username}?start=vote_{b['id']}_{p['uid']}",
                style="primary")] for p in standings(b["id"])[:30]]
    if ended:
        rows.append([ibi("bend", "Battle tugagan", cb="ended", style="danger", ch=True)])
    else:
        rows.append([ibi("bjoin", "Konkursga qo'shilish", cb=f"bjoin:{b['id']}", style="success", ch=True)])
        rows.append([ibi("bres", "Natijalar", cb=f"bres:{b['id']}", style="danger", ch=True)])
    rows.append([ibi("bvot", "Ovoz berganlar", cb=f"bvot:{b['id']}", style="primary", ch=True)])
    return kb(rows)

@router.message(BS.chan)
async def b_chan(m: Message, state: FSMContext, bot: Bot):
    res = await resolve_channel(bot, m, m.from_user.id)
    if isinstance(res, str):
        return await m.answer(res)
    await create_battle(m, m.from_user.id, state, bot, res)

async def create_battle(m: Message, owner_id: int, state: FSMContext, bot: Bot, res: dict):
    d = await state.get_data()
    cur = ex("""INSERT INTO battles(owner,name,prize,end_kind,end_at,end_votes,lang,channel_id,channel_title,
        channel_username,extra,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
             owner_id, d["name"], d["prize"], d["end_kind"], d.get("end_at"), d.get("end_votes"),
             d["lang"], res["id"], res["title"], res["username"], json.dumps(d.get("extra", [])), now_ts())
    bid = cur.lastrowid
    b = q1("SELECT * FROM battles WHERE id=?", bid)
    me = (await bot.me()).username
    try:
        post = await bot.send_message(res["id"], battle_text(b, me), reply_markup=battle_markup(b, me))
    except Exception as e:
        ex("DELETE FROM battles WHERE id=?", bid)
        return await m.answer(f"❌ Kanalga joylab bo'lmadi: {esc(str(e))}")
    ex("UPDATE battles SET post_msg=? WHERE id=?", post.message_id, bid)
    await state.clear()
    end = f"{b['end_votes']} ta ovoz yig'ilganda" if b["end_kind"] == "votes" else f"{fmt_ts(b['end_at'])} da"
    extra = ", ".join("@" + x["username"] for x in json.loads(b["extra"]))
    await m.answer("⭐ <b>Battle yaratildi!</b>\n\n"
                   f"📝 Nomi: {esc(b['name'])}\n📢 Kanal: @{res['username']}\n🎁 Sovrin: {esc(b['prize'])}\n"
                   f"🎯 Batl tugashi: {end}\n🌐 Post tili: {LANGS[b['lang']]}\n"
                   f"🔒 Majburiy kanallar: @{res['username']}{', ' + extra if extra else ''}")

# ====================== KANALDAGI #batl ======================
BATL_NAME = "OVOZ BATL BOSHLANDI"

def pick_owner(admins, signature):
    """Kanal posti muallifini bilmaymiz: imzo mos kelsa o'sha admin, bo'lmasa kanal egasi."""
    humans = [a for a in admins if not a.user.is_bot]
    if signature:
        for a in humans:
            if signature in (a.user.full_name, getattr(a, "custom_title", None)):
                return a.user.id
    for a in humans:
        if a.status == "creator":
            return a.user.id
    return humans[0].user.id if humans else None

@router.channel_post(F.text.strip().lower() == "#battil")
async def channel_batl(m: Message, bot: Bot):
    """Kanalga #battil yozilsa, shu kanalning o'ziga battle posti darhol chiqadi."""
    chat = m.chat
    if not chat.username:
        return await bot.send_message(chat.id, "❌ Battle uchun kanal ochiq (public, username'li) bo'lishi kerak.")
    try:
        owner = pick_owner(await bot.get_chat_administrators(chat.id), m.author_signature)
    except Exception:
        log.exception("adminlarni olib bo'lmadi")
        return
    if owner is None:
        return
    cur = ex("""INSERT INTO battles(owner,name,prize,end_kind,end_at,end_votes,lang,channel_id,channel_title,
        channel_username,extra,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
             owner, BATL_NAME, "-", "manual", None, None, "uz", chat.id, chat.title or chat.username,
             chat.username, "[]", now_ts())
    bid = cur.lastrowid
    b = q1("SELECT * FROM battles WHERE id=?", bid)
    me = (await bot.me()).username
    try:
        post = await bot.send_message(chat.id, battle_text(b, me), reply_markup=battle_markup(b, me))
    except Exception as e:
        ex("DELETE FROM battles WHERE id=?", bid)
        log.warning("battle postini joylab bo'lmadi: %s", e)
        return
    ex("UPDATE battles SET post_msg=? WHERE id=?", post.message_id, bid)

@router.channel_post(F.text.strip().lower() == "#tuga")
async def channel_tuga(m: Message, bot: Bot):
    """Kanalga #tuga yozilsa: shu kanaldagi faol battle(lar) tugatiladi, natijalar e'lon qilinadi."""
    try:
        await m.delete()
    except Exception:
        pass
    for b in qa("SELECT id FROM battles WHERE channel_id=? AND status='active'", m.chat.id):
        await battle_finish(bot, b["id"])

# ---- #kick: foydalanuvchini kanal/guruhdan 1 soatga ban ----
KICK_RE = re.compile(r"^#kick(?:\s+(\d{5,15}))?(?:\s+(\d{1,3}))?\s*$", re.I)

async def do_kick(bot: Bot, chat_id: int, uid: int, hours: int) -> str:
    hours = max(1, min(hours, 720))
    try:
        if (await bot.get_chat_member(chat_id, uid)).status in ("administrator", "creator"):
            return "❌ Adminni ban qilib bo'lmaydi."
        await bot.ban_chat_member(chat_id, uid, until_date=datetime.now(timezone.utc) + timedelta(hours=hours))
        return f"✅ {uid} foydalanuvchi {hours} soatga ban qilindi (ovozlari avtomatik olib tashlanadi)."
    except Exception as e:
        return "❌ Bajarilmadi: " + str(e)[:90]

@router.channel_post(F.text.regexp(r"(?i)^#kick\b"))
async def channel_kick(m: Message, bot: Bot):
    """Kanalga '#kick 123456789' (ixtiyoriy: '#kick 123456789 3' = 3 soat) yozilsa, shu odam 1 soatga ban qilinadi."""
    try:
        await m.delete()
    except Exception:
        pass
    mt = KICK_RE.match(m.text.strip())
    res = "❌ Format: #kick 123456789 (ixtiyoriy soat: #kick 123456789 3)"
    if mt and mt.group(1):
        res = await do_kick(bot, m.chat.id, int(mt.group(1)), int(mt.group(2) or 1))
    try:
        owner = pick_owner(await bot.get_chat_administrators(m.chat.id), m.author_signature)
        if owner:
            await bot.send_message(owner, f"{esc(m.chat.title)}: {res}")
    except Exception:
        pass

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^#kick\b"))
async def group_kick(m: Message, bot: Bot):
    """Guruhda admin odamning xabariga '#kick' deb javob bersa (yoki '#kick 123456789'), u 1 soatga ban qilinadi."""
    try:
        if (await bot.get_chat_member(m.chat.id, m.from_user.id)).status not in ("administrator", "creator"):
            return
    except Exception:
        return
    mt = KICK_RE.match(m.text.strip())
    rep = m.reply_to_message
    uid = rep.from_user.id if rep and rep.from_user else (int(mt.group(1)) if mt and mt.group(1) else None)
    hours = int(mt.group(2)) if mt and mt.group(2) else 1
    try:
        await m.delete()
    except Exception:
        pass
    await bot.send_message(m.chat.id, await do_kick(bot, m.chat.id, uid, hours) if uid else
                           "❌ Odamning xabariga #kick deb javob bering yoki: #kick 123456789")

# ====================== BATTLE: QO'SHILISH, OVOZ ======================
async def refresh_battle(bot: Bot, bid: int):
    b = q1("SELECT * FROM battles WHERE id=?", bid)
    if not b:
        return
    me = (await bot.me()).username
    await bot.edit_message_reply_markup(chat_id=b["channel_id"], message_id=b["post_msg"],
                                        reply_markup=battle_markup(b, me, ended=b["status"] != "active"))

@router.callback_query(F.data.startswith("bjoin:"))
async def b_join(c: CallbackQuery, bot: Bot):
    b = q1("SELECT * FROM battles WHERE id=?", int(c.data[6:]))
    if not b or b["status"] != "active":
        return await c.answer("🏁 Battle tugagan.", show_alert=True)
    if q1("SELECT 1 FROM b_removed WHERE battle_id=? AND user_id=?", b["id"], c.from_user.id):
        return await c.answer("🚫 Multi-akkaunt ishlatgani uchun chetlatilgansiz.", show_alert=True)
    if q1("SELECT 1 FROM b_part WHERE battle_id=? AND user_id=?", b["id"], c.from_user.id):
        return await c.answer("✅ Siz allaqachon qo'shilgansiz.", show_alert=True)
    bad = await not_subscribed(bot, c.from_user.id, b_chans(b))
    if bad:
        return await c.answer("❌ Avval kanallarga obuna bo'ling: " + ", ".join("@" + x["username"] for x in bad), show_alert=True)
    u = c.from_user
    ex("INSERT INTO b_part(battle_id,user_id,name,username,joined) VALUES(?,?,?,?,?)",
       b["id"], u.id, u.full_name, u.username, now_ts())
    await c.answer("✅ Siz konkursga muvaffaqiyatli qo'shildingiz!", show_alert=True)
    debounce(("bm", b["id"]), lambda: refresh_battle(bot, b["id"]))

def rating_text(b):
    st = standings(b["id"])
    lines = [f"{MEDALS[i] if i < 3 else str(i + 1) + '.'} {esc(label(p))} — 📦 {p['votes']} ovoz" for i, p in enumerate(st[:10])]
    body = "\n".join(lines) if lines else "Hozircha ishtirokchilar yo'q."
    status = "🟢 Batl faol" if b["status"] == "active" else "🔴 Batl tugagan"
    return f"🧑‍💻 <b>ISHTIROKCHILAR REYTINGI:</b>\n————————————\n{body}\n————————————\n{status}"

@router.callback_query(F.data.startswith("bres:"))
async def b_results(c: CallbackQuery):
    b = q1("SELECT * FROM battles WHERE id=?", int(c.data[5:]))
    if not b:
        return await c.answer()
    st = standings(b["id"])[:5]
    text = "📊 Natijalar:\n" + ("\n".join(f"{i + 1}. {label(p)} — {p['votes']}" for i, p in enumerate(st)) or "Hozircha yo'q")
    await c.answer(text[:200], show_alert=True)

@router.callback_query(F.data.startswith("bvot:"))
async def b_voters(c: CallbackQuery):
    bid = int(c.data[5:])
    total = q1("SELECT COUNT(*) c FROM b_votes WHERE battle_id=?", bid)["c"]
    rows = qa("SELECT vname FROM b_votes WHERE battle_id=? ORDER BY ts DESC LIMIT 8", bid)
    text = f"🗳 Ovoz berganlar: {total}\n" + "\n".join(r["vname"] for r in rows)
    await c.answer(text[:200], show_alert=True)

def acc_ref(uid):
    """@username yoki profil havolasi."""
    r = q1("SELECT * FROM user_dev WHERE user_id=?", uid)
    if r and r["username"]:
        return "@" + r["username"]
    return f'<a href="tg://user?id={uid}">{esc((r["name"] if r else "") or str(uid))}</a>'

async def notify_multi(bot: Bot, b, u, ids, stage: int):
    """Multi-akkaunt hisoboti: battle egasiga (bot admini bo'lmasa ham) va adminlarga."""
    link = f"https://t.me/{b['channel_username']}/{b['post_msg']}" if b["post_msg"] else f"https://t.me/{b['channel_username']}"
    lines = "\n".join(f"{i}-akkaunt: {acc_ref(a)}" for i, a in enumerate(ids, 1))
    text = (f"🚨 <b>Multi akkaunt aniqlandi!</b>\n\n⚔️ Battle: {link}\n👤 Shu odam: {acc_ref(u.id)}\n\n"
            f"📱 <b>Multi akk: {len(ids)} ta</b>\n{lines}\n\n"
            + ("⏱ Hammasi kanaldan 1 soatga ban qilindi." if stage == 1 else "🚫 Hammasi battledan chetlatildi."))
    for to in {b["owner"], *ADMIN_IDS}:
        try:
            await bot.send_message(to, text)
        except Exception:
            pass

async def multi_guard(bot: Bot, b, u) -> bool:
    """Bir qurilmadan 3+ akkaunt: 1-marta 1 soatga ban; qayta urinsa battledan chetlatiladi va kanalda e'lon qilinadi.
    True qaytsa, ovoz bloklangan va foydalanuvchiga javob berilgan."""
    bid = b["id"]
    group = [u.id] + [o["user_id"] for o in same_device(u.id)]
    ph = ",".join("?" * len(group))
    ex("INSERT INTO b_attempts(battle_id,user_id,ts) VALUES(?,?,?)", bid, u.id, now_ts())
    accs = {r["x"] for r in qa(f"SELECT voter AS x FROM b_votes WHERE battle_id=? AND voter IN ({ph})", bid, *group)}
    accs |= {r["x"] for r in qa(f"SELECT DISTINCT user_id AS x FROM b_attempts WHERE battle_id=? AND user_id IN ({ph})", bid, *group)}
    accs.add(u.id)
    if len(accs) < 3:
        return False
    root = min(group)
    st = q1("SELECT strikes FROM b_dev WHERE battle_id=? AND root=?", bid, root)
    ids = [a for a in accs if a not in ADMIN_IDS]
    ph2 = ",".join("?" * len(ids))
    rows = [q1("SELECT * FROM user_dev WHERE user_id=?", a) for a in ids]
    names = ", ".join(esc(disp(r)) for r in rows[:3] if r) or esc(u.full_name)
    if len(ids) > 3:
        names += f" (+{len(ids) - 3})"
    ex(f"DELETE FROM b_votes WHERE battle_id=? AND voter IN ({ph2})", bid, *ids)
    if not st or st["strikes"] == 0:
        ex("INSERT OR REPLACE INTO b_dev(battle_id,root,strikes) VALUES(?,?,1)", bid, root)
        for a in ids:
            await do_kick(bot, b["channel_id"], a, 1)
            ex("INSERT INTO b_attempts(battle_id,user_id,ts) VALUES(?,?,?)", bid, a, now_ts())   # keyingi urinishda hammasi hisobga olinadi
        await notify_multi(bot, b, u, ids, 1)
        await reply(bot, u.id, "🚫 <b>Bir qurilmadan bir nechta akkaunt aniqlandi.</b>\nSiz 1 soatga ban qilindingiz. "
                    "Qayta urinsangiz, battledan chetlatilasiz.")
    else:
        ex("INSERT OR REPLACE INTO b_dev(battle_id,root,strikes) VALUES(?,?,2)", bid, root)
        for a in ids:
            ex("INSERT OR IGNORE INTO b_removed(battle_id,user_id) VALUES(?,?)", bid, a)
        ex(f"DELETE FROM b_votes WHERE battle_id=? AND cand IN ({ph2})", bid, *ids)
        ex(f"DELETE FROM b_part WHERE battle_id=? AND user_id IN ({ph2})", bid, *ids)
        await notify_multi(bot, b, u, ids, 2)
        await reply(bot, u.id, "🚫 Multi-akkaunt ishlatgani uchun siz battledan chetlatildingiz.")
        try:
            await bot.send_message(b["channel_id"], f"🚫 <b>{names}</b> multi akkaunt ishlatgani uchun battledan chetlatildi.",
                                   reply_parameters=ReplyParameters(message_id=b["post_msg"]))
        except Exception:
            log.exception("kanalga chetlatish xabarini yozib bo'lmadi")
    debounce(("bm", bid), lambda: refresh_battle(bot, bid))
    return True

async def battle_vote(bot: Bot, u, bid: int, pid: int, cb: CallbackQuery | None = None):
    b = q1("SELECT * FROM battles WHERE id=?", bid)
    if not b or b["status"] != "active":
        return await reply(bot, u.id, "🏁 Bu battle tugagan yoki topilmadi.", cb=cb)
    if q1("SELECT 1 FROM b_removed WHERE battle_id=? AND user_id=?", bid, u.id):
        return await reply(bot, u.id, "🚫 Multi-akkaunt ishlatgani uchun siz bu battledan chetlatilgansiz.", cb=cb)
    cand = q1("SELECT * FROM b_part WHERE battle_id=? AND user_id=?", bid, pid)
    if not cand:
        return await reply(bot, u.id, "❌ Ishtirokchi topilmadi.", cb=cb)
    if q1("SELECT 1 FROM b_votes WHERE battle_id=? AND voter=?", bid, u.id):
        return await reply(bot, u.id, "⚠️ Siz bu battle'da allaqachon ovoz bergansiz.\n\n" + rating_text(b), cb=cb)
    bad = await not_subscribed(bot, u.id, b_chans(b))
    if bad:
        return await reply(bot, u.id, SUB_TEXT, sub_kb(bad, f"chk:v:{bid}:{pid}"), cb)
    if DEVICE_ON:
        if not await device_gate(bot, u, "v", bid, pid, cb):
            return
        other = battle_conflict(bid, u.id)
        if other:
            if await multi_guard(bot, b, u):
                return
            await reply(bot, u.id, dup_text(other, "ovoz bergansiz"), cb=cb)
            await notify_dup(bot, f"Battle #{bid} «{b['name']}»", "ovoz bermoqchi bo'ldi", u, other)
            return
    ex("INSERT INTO b_votes(battle_id,voter,cand,vname,ts) VALUES(?,?,?,?,?)", bid, u.id, pid, u.full_name, now_ts())
    await reply(bot, u.id, f"⭐️ {esc(label(cand))} ga ovoz berdingiz. Ovozingiz qabul qilindi!", cb=cb)
    debounce(("bm", bid), lambda: refresh_battle(bot, bid))
    top = standings(bid)[0]["votes"]
    if b["end_kind"] == "votes" and top >= b["end_votes"]:
        await battle_finish(bot, bid)

# ====================== BATTLE: YAKUNLASH, KANALDAN CHIQISH ======================
async def battle_finish(bot: Bot, bid: int):
    b = q1("SELECT * FROM battles WHERE id=?", bid)
    if not b or b["status"] != "active":
        return
    ex("UPDATE battles SET status='done' WHERE id=?", bid)
    st = standings(bid)[:10]
    lines = [f"{MEDALS[i] if i < 3 else '🏅'} {esc(label(p))} — 📦 {p['votes']} ta ovoz" for i, p in enumerate(st)]
    body = "\n".join(lines) if lines else "Ishtirokchilar bo'lmadi."
    text = f"{esc(b['name'])} 🏆\n🏁 <b>KONKURS NATIJALARI!</b> 🏆\n\n{body}\n\n🎉 Barcha ishtirokchilarga rahmat!"
    try:
        await bot.send_message(b["channel_id"], text, reply_parameters=ReplyParameters(message_id=b["post_msg"]))
        await refresh_battle(bot, bid)
    except Exception as e:
        log.warning("battle_finish: %s", e)
    if st and st[0]["votes"] > 0:
        try:
            await bot.send_message(st[0]["uid"], f"🎉 Tabriklaymiz! Siz {esc(b['channel_title'])}dagi battle'da g'olib bo'ldingiz!")
        except Exception:
            pass

@router.chat_member()
async def on_member(ev: ChatMemberUpdated, bot: Bot):
    """Ovoz beruvchi kanaldan chiqsa, ovozi olib tashlanadi (bot kanalda admin bo'lishi shart)."""
    if ev.new_chat_member.status not in ("left", "kicked"):
        return
    uid = ev.new_chat_member.user.id
    for b in qa("SELECT * FROM battles WHERE status='active'"):
        if ev.chat.id in [c["id"] for c in b_chans(b)]:
            if ex("DELETE FROM b_votes WHERE battle_id=? AND voter=?", b["id"], uid).rowcount:
                bid = b["id"]
                debounce(("bm", bid), lambda bid=bid: refresh_battle(bot, bid))

# ====================== QURILMANI TASDIQLASH ======================
DEVICE_TEXT = ("📱 <b>Qurilmani tasdiqlash</b>\n\nFiribgarlikdan himoya uchun qurilmangiz tekshiriladi. "
               "Pastdagi tugmani bosing, sahifa o'zi tekshiradi va yopiladi.\n\n"
               "<i>Faqat qurilma belgilarining xeshi saqlanadi.</i>")

class U:
    """Web App'dan kelgan foydalanuvchini aiogram User kabi ko'rsatadi."""
    def __init__(self, d):
        self.id = d["id"]
        self.full_name = (d.get("first_name", "") + " " + d.get("last_name", "")).strip() or str(d["id"])
        self.username = d.get("username")

def disp(r):
    return ("@" + r["username"]) if r["username"] else (r["name"] or str(r["user_id"]))

def save_device(user, dev_id, fp, ip_h):
    u = U(user)
    ex("INSERT OR REPLACE INTO user_dev(user_id,dev_id,fp,ip_h,name,username,ts) VALUES(?,?,?,?,?,?,?)",
       u.id, dev_id, fp, ip_h, u.full_name, u.username, now_ts())

def same_device(uid):
    """Shu foydalanuvchi bilan bir qurilmada ko'ringan boshqa akkauntlar."""
    me = q1("SELECT * FROM user_dev WHERE user_id=?", uid)
    if not me:
        return []
    return qa("""SELECT * FROM user_dev WHERE user_id!=?
                 AND ((dev_id=? AND dev_id!='') OR (fp=? AND ip_h=?))""", uid, me["dev_id"], me["fp"], me["ip_h"])

def _first_used(table, key_col, key, uid):
    others = same_device(uid)
    if not others:
        return None
    ids = [o["user_id"] for o in others]
    ph = ",".join("?" * len(ids))
    col = "voter" if table == "b_votes" else "user_id"
    hit = q1(f"SELECT {col} AS x FROM {table} WHERE {key_col}=? AND {col} IN ({ph})", key, *ids)
    return q1("SELECT * FROM user_dev WHERE user_id=?", hit["x"]) if hit else None

def battle_conflict(bid, uid): return _first_used("b_votes", "battle_id", bid, uid)
def contest_conflict(cid, uid): return _first_used("contest_users", "contest_id", cid, uid)

def dup_text(other, what):
    return (f"❌ Siz shu qurilmadan avval {what}.\n👤 Akkaunt: <b>{esc(disp(other))}</b>\n\n"
            "Bir qurilmadan faqat bitta akkaunt qatnasha oladi.")

_dup_seen = set()
async def notify_dup(bot: Bot, where, action, u, other):
    key = (where, u.id, other["user_id"])
    if key in _dup_seen:
        return
    _dup_seen.add(key)
    linked = same_device(u.id)
    lines = [f"• {esc(disp(r))} (<code>{r['user_id']}</code>)" for r in linked[:10]]
    me = ("@" + u.username) if u.username else u.full_name
    text = (f"🚨 <b>Bir qurilmada bir nechta akkaunt!</b>\n\n📍 {esc(where)}\n"
            f"👤 {action}: <b>{esc(me)}</b> (<code>{u.id}</code>)\n"
            f"👤 Avval qatnashgan: <b>{esc(disp(other))}</b> (<code>{other['user_id']}</code>)\n\n"
            f"📱 Shu qurilmada aniqlangan akkauntlar: <b>{len(linked) + 1}</b> ta\n" + "\n".join(lines) +
            "\n\n⛔ Takroriy ovoz/qatnashish qabul qilinmadi.")
    for a in ADMIN_IDS:
        try:
            await bot.send_message(a, text)
        except Exception:
            pass

async def device_gate(bot: Bot, u, kind, a, b=0, cb=None) -> bool:
    """Qurilma tasdiqlanmagan bo'lsa Web App tugmasini yuboradi va False qaytaradi."""
    if q1("SELECT 1 FROM user_dev WHERE user_id=?", u.id):
        return True
    ex("INSERT OR REPLACE INTO pending(user_id,kind,a,b) VALUES(?,?,?,?)", u.id, kind, a, b)
    await reply(bot, u.id, DEVICE_TEXT,
                kb([[ibi("device", "Qurilmani tasdiqlash", web=f"{WEBAPP_URL}/verify", style="success")]]), cb)
    return False

async def after_verify(bot: Bot, user):
    """Tasdiqlashdan keyin to'xtab qolgan amalni (ovoz/qatnashish) davom ettiradi."""
    u = U(user)
    p = q1("SELECT * FROM pending WHERE user_id=?", u.id)
    if not p:
        return await bot.send_message(u.id, "✅ Qurilma tasdiqlandi.")
    ex("DELETE FROM pending WHERE user_id=?", u.id)
    if p["kind"] == "c":
        await contest_join(bot, u, p["a"])
    else:
        await battle_vote(bot, u, p["a"], p["b"])

# ====================== OBUNANI TEKSHIRISH TUGMASI ======================
@router.callback_query(F.data.startswith("chk:"))
async def chk(c: CallbackQuery, state: FSMContext, bot: Bot):
    p = c.data.split(":")
    await c.answer()
    if p[1] == "c":
        await contest_join(bot, c.from_user, int(p[2]), state, c)
    elif p[1] == "v":
        await battle_vote(bot, c.from_user, int(p[2]), int(p[3]), c)

async def deeplink(bot: Bot, m: Message, args: str, state: FSMContext):
    if args.startswith("join_") and args[5:].isdigit():
        await contest_join(bot, m.from_user, int(args[5:]), state)
    elif args.startswith("vote_"):
        p = args.split("_")
        if len(p) == 3 and p[1].isdigit() and p[2].isdigit():
            await battle_vote(bot, m.from_user, int(p[1]), int(p[2]))

# ====================== MENING BATTLELARIM / KONKURSLARIM ======================
def my_list(kind, uid):
    if kind == "b":
        rows = qa("SELECT id,name,status FROM battles WHERE owner=? ORDER BY id DESC LIMIT 20", uid)
        btns = [[ib(f"{'🟢' if r['status'] == 'active' else '🏁'} #{r['id']} {r['name']}", cb=f"mb:{r['id']}")] for r in rows]
        title = "🧑‍💻 <b>Mening battlelarim</b>\n\nKerakli battlni tanlang:"
    else:
        rows = qa("SELECT id,channel_title,status FROM contests WHERE owner=? ORDER BY id DESC LIMIT 20", uid)
        btns = [[ib(f"{'🟢' if r['status'] == 'active' else '🏁'} #{r['id']} {r['channel_title']}", cb=f"mc:{r['id']}")] for r in rows]
        title = "🧑‍💻 <b>Mening konkurslarim</b>\n\nKerakli konkursni tanlang:"
    return (title, kb(btns)) if rows else ("Hozircha hech narsa yo'q.", None)

async def my_battles(m: Message):
    text, markup = my_list("b", m.from_user.id)
    await m.answer(text, reply_markup=markup)

async def my_contests(m: Message):
    text, markup = my_list("c", m.from_user.id)
    await m.answer(text, reply_markup=markup)

@router.callback_query(F.data.in_({"mbl", "mcl"}))
async def back_to_list(c: CallbackQuery):
    text, markup = my_list("b" if c.data == "mbl" else "c", c.from_user.id)
    await c.answer()
    await c.message.edit_text(text, reply_markup=markup)

def status_txt(s): return "🟢 Faol" if s == "active" else "🏁 Tugagan"

@router.callback_query(F.data.startswith("mb:"))
async def mb_detail(c: CallbackQuery):
    b = q1("SELECT * FROM battles WHERE id=? AND owner=?", int(c.data[3:]), c.from_user.id)
    if not b:
        return await c.answer("Topilmadi", show_alert=True)
    parts = q1("SELECT COUNT(*) c FROM b_part WHERE battle_id=?", b["id"])["c"]
    votes = q1("SELECT COUNT(*) c FROM b_votes WHERE battle_id=?", b["id"])["c"]
    rows = [[ibi("stop", "Battle to'xtatish", cb=f"mbs:{b['id']}", style="danger")]] if b["status"] == "active" else []
    rows.append([ibi("w_back", "Orqaga", cb="mbl")])
    await c.answer()
    await c.message.edit_text(f"🧑‍💻 <b>{esc(b['name'])}</b>\n\n🎁 Sovrin: {esc(b['prize'])}\n"
                              f"👥 Ishtirokchilar: {parts}\n📦 Ovozlar: {votes}\n📌 Holati: {status_txt(b['status'])}",
                              reply_markup=kb(rows))

@router.callback_query(F.data.startswith("mbs:"))
async def mb_stop(c: CallbackQuery, bot: Bot):
    b = q1("SELECT * FROM battles WHERE id=? AND owner=?", int(c.data[4:]), c.from_user.id)
    if not b:
        return await c.answer("Topilmadi", show_alert=True)
    await c.answer()
    await battle_finish(bot, b["id"])
    await c.message.edit_text(f"⭐ {esc(b['name'])} — battle to'xtatildi va natijalar kanalga joylandi!",
                              reply_markup=kb([[ibi("w_back", "Orqaga", cb="mbl")]]))

@router.callback_query(F.data.startswith("mc:"))
async def mc_detail(c: CallbackQuery):
    ct = q1("SELECT * FROM contests WHERE id=? AND owner=?", int(c.data[3:]), c.from_user.id)
    if not ct:
        return await c.answer("Topilmadi", show_alert=True)
    n = q1("SELECT COUNT(*) c FROM contest_users WHERE contest_id=?", ct["id"])["c"]
    end = f"{ct['end_count']} ta ishtirokchi yetganda" if ct["end_kind"] == "count" else fmt_ts(ct["end_at"])
    rows = [[ibi("stop", "Konkursni to'xtatish", cb=f"mcs:{ct['id']}", style="danger")]] if ct["status"] == "active" else []
    rows.append([ibi("w_back", "Orqaga", cb="mcl")])
    await c.answer()
    await c.message.edit_text(f"🏆 <b>Konkurs #{ct['id']}</b>\n\n📢 Kanal: {esc(ct['channel_title'])}\n"
                              f"👥 Ishtirokchilar: {n}\n🏅 G'oliblar soni: {ct['winners']}\n🏁 Tugash: {end}\n"
                              f"📌 Holati: {status_txt(ct['status'])}", reply_markup=kb(rows))

@router.callback_query(F.data.startswith("mcs:"))
async def mc_stop(c: CallbackQuery, bot: Bot):
    ct = q1("SELECT * FROM contests WHERE id=? AND owner=?", int(c.data[4:]), c.from_user.id)
    if not ct:
        return await c.answer("Topilmadi", show_alert=True)
    await c.answer()
    await contest_finish(bot, ct["id"])
    await c.message.edit_text("⭐ Konkurs tugatildi. Natijalar kanalga yuborildi.",
                              reply_markup=kb([[ibi("w_back", "Orqaga", cb="mcl")]]))

# ====================== FONDAGI VAZIFA ======================
async def scheduler(bot: Bot):
    while True:
        try:
            t = now_ts()
            for r in qa("SELECT id FROM battles WHERE status='active' AND end_kind='time' AND end_at<=?", t):
                await battle_finish(bot, r["id"])
            for r in qa("SELECT id FROM contests WHERE status='active' AND end_kind='time' AND end_at<=?", t):
                await contest_finish(bot, r["id"])
        except Exception as e:
            log.warning("scheduler: %s", e)
        await asyncio.sleep(20)

def start_background(bot: Bot):
    t = asyncio.create_task(scheduler(bot))
    _tasks.add(t)
