"""Web App admin panel: faqat adminlar uchun (Telegram initData imzosi + ADMIN ro'yxati)."""
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

import emojis
import games
import webapp

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("adminpanel")
UZ = timezone(timedelta(hours=5))


LINK_RE = re.compile(r"(?:t\.me/\+|t\.me/joinchat/|tg://join\?invite=)([A-Za-z0-9_\-]{8,})")


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg, self.status = msg, status


def _restart_process():
    log.warning("Bot qayta ishga tushirilmoqda (admin panel buyrug'i)...")
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


def setup(app: web.Application, bot, token: str, *, db, admin_ids: set, env_admins: set,
          connected_channels, req_channels, on_req_change=None):
    """admin_ids — bot bilan umumiy set (o'zgartirilsa, bot ham darhol ko'radi)."""

    def one(sql, *args):
        return db.execute(sql, args).fetchone()[0]

    def api(fn):
        async def handler(request: web.Request):
            user = webapp.check_init_data(request.headers.get("X-Init-Data", ""), token)
            if not user or user.get("id") not in admin_ids:
                return web.json_response({"ok": False, "error": "forbidden"}, status=403)
            try:
                body = await request.json() if request.can_read_body else {}
            except Exception:
                body = {}
            try:
                res = await fn(user, body if isinstance(body, dict) else {})
            except ApiError as e:
                return web.json_response({"ok": False, "error": e.msg}, status=e.status)
            except Exception:
                log.exception("admin API xatosi: %s", fn.__name__)
                return web.json_response({"ok": False, "error": "server"}, status=500)
            return web.json_response({"ok": True, **res})
        return handler

    # ---------- sahifa ----------
    async def page(_):
        with open(os.path.join(HERE, "admin.html"), encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    # ---------- me / statistika ----------
    async def me(user, body):
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or "Admin"
        return {"id": user["id"], "name": name, "owner": user["id"] in env_admins}

    async def stats(user, body):
        today = datetime.now(UZ).date()
        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            week.append({"day": d.isoformat(), "wd": d.weekday(),
                         "n": one("SELECT COUNT(*) FROM users WHERE joined=?", d.isoformat())})
        return {
            "users": one("SELECT COUNT(*) FROM users"),
            "today": one("SELECT COUNT(*) FROM users WHERE joined=?", today.isoformat()),
            "banned": one("SELECT COUNT(*) FROM users WHERE banned=1"),
            "points": one("SELECT COALESCE(SUM(points),0) FROM users"),
            "battles": one("SELECT COUNT(*) FROM battles"),
            "battles_active": one("SELECT COUNT(*) FROM battles WHERE status='active'"),
            "contests": one("SELECT COUNT(*) FROM contests"),
            "contests_active": one("SELECT COUNT(*) FROM contests WHERE status='active'"),
            "channels": len(connected_channels()),
            "req_channels": len(req_channels()),
            "admins": len(admin_ids),
            "emoji_set": len(emojis.IDS),
            "emoji_total": len(emojis.ORDER),
            "week": week,
        }

    # ---------- adminlar ----------
    def admin_rows():
        names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM admins")}
        rows = []
        for uid in sorted(admin_ids, key=lambda x: (x not in env_admins, x)):
            u = db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            rows.append({"id": uid, "name": names.get(uid) or (u["name"] if u else "") or "—",
                         "owner": uid in env_admins})
        return rows

    async def admins(user, body):
        return {"admins": admin_rows()}

    async def admins_add(user, body):
        raw = str(body.get("id", "")).strip()
        if not re.fullmatch(r"\d{5,15}", raw):
            raise ApiError("ID faqat raqamlardan iborat bo'lishi kerak (5–15 xona).")
        uid = int(raw)
        if uid in admin_ids:
            raise ApiError("Bu foydalanuvchi allaqachon admin.")
        name = ""
        try:
            ch = await bot.get_chat(uid)
            name = " ".join(x for x in (ch.first_name, ch.last_name) if x) or (ch.title or "")
        except Exception:
            u = db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            name = u["name"] if u else ""
        db.execute("INSERT OR REPLACE INTO admins(id,name,added_by,added) VALUES(?,?,?,?)",
                   (uid, name, user["id"], datetime.now(UZ).strftime("%Y-%m-%d")))
        db.commit()
        admin_ids.add(uid)
        notified = True
        try:
            await bot.send_message(uid, "🎉 Siz bot administratori qilindingiz.\n/admin buyrug'i bilan panelni oching.")
        except Exception:
            notified = False     # foydalanuvchi botga hali /start bosmagan
        return {"admins": admin_rows(), "notified": notified}

    async def admins_remove(user, body):
        try:
            uid = int(body.get("id"))
        except (TypeError, ValueError):
            raise ApiError("ID noto'g'ri.")
        if uid in env_admins:
            raise ApiError("Asosiy adminni (ADMIN_IDS) panel orqali o'chirib bo'lmaydi.")
        if uid == user["id"]:
            raise ApiError("O'zingizni o'chira olmaysiz.")
        if uid not in admin_ids:
            raise ApiError("Bunday admin topilmadi.", 404)
        db.execute("DELETE FROM admins WHERE id=?", (uid,))
        db.commit()
        admin_ids.discard(uid)
        return {"admins": admin_rows()}

    # ---------- premium emoji ----------
    async def emoji_list(user, body):
        return {"items": emojis.items(), "set": len(emojis.IDS)}

    async def emoji_save(user, body):
        raw = body.get("items")
        if not isinstance(raw, dict) or not raw:
            raise ApiError("Saqlash uchun o'zgarish yo'q.")
        clean, bad_format = {}, []
        for k, v in raw.items():
            if k not in emojis.FALLBACK:
                continue
            v = str(v or "").strip()
            if v and not re.fullmatch(r"\d{5,25}", v):
                bad_format.append(k)
                continue
            clean[k] = v
        verified, invalid, checked = {}, [], True
        ids = sorted({v for v in clean.values() if v})
        if ids:
            try:
                found = {}
                for i in range(0, len(ids), 100):
                    for s in await bot.get_custom_emoji_stickers(custom_emoji_ids=ids[i:i + 100]):
                        found[s.custom_emoji_id] = s.emoji or ""
                for k, v in list(clean.items()):
                    if not v:
                        continue
                    if v in found:
                        verified[k] = found[v]
                    else:
                        invalid.append(k)
                        clean.pop(k)
            except Exception:
                log.exception("emoji ID'larni Telegram orqali tekshirib bo'lmadi")
                checked = False   # tarmoq xatosi: tekshirmasdan saqlaymiz
        emojis.save_ids(clean)
        return {"items": emojis.items(), "set": len(emojis.IDS), "saved": len(clean),
                "invalid": invalid + bad_format, "verified": verified, "checked": checked}

    async def restart(user, body):
        asyncio.get_running_loop().call_later(1.2, _restart_process)
        return {}

    # ---------- foydalanuvchilar ----------
    async def users_search(user, body):
        q, sort = str(body.get("q", "")).strip(), body.get("sort", "new")
        where, args = "1=1", []
        if q.isdigit():
            where, args = "id=?", [int(q)]
        elif q:
            where, args = "name LIKE ?", [f"%{q}%"]
        if sort == "ban":
            where += " AND banned=1"
        order = "points DESC" if sort == "top" else "rowid DESC"
        rows = db.execute(f"SELECT id,name,points,joined,banned FROM users WHERE {where} ORDER BY {order} LIMIT 40", args).fetchall()
        return {"users": [dict(r) for r in rows]}

    def user_row(uid):
        r = db.execute("SELECT id,name,points,joined,banned FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            raise ApiError("Foydalanuvchi topilmadi.", 404)
        return dict(r)

    async def users_ban(user, body):
        uid = int(body.get("id", 0))
        user_row(uid)
        if uid in admin_ids:
            raise ApiError("Adminni bloklab bo'lmaydi.")
        db.execute("UPDATE users SET banned=? WHERE id=?", (1 if body.get("ban") else 0, uid))
        db.commit()
        return {"user": user_row(uid)}

    async def users_points(user, body):
        uid, delta = int(body.get("id", 0)), int(body.get("delta", 0))
        user_row(uid)
        if not delta or abs(delta) > 1_000_000:
            raise ApiError("Ball noto'g'ri.")
        db.execute("UPDATE users SET points=MAX(0,points+?) WHERE id=?", (delta, uid))
        db.commit()
        return {"user": user_row(uid)}

    # ---------- xabar yuborish ----------
    jobs, running = {}, set()

    async def bc_start(user, body):
        text, target = str(body.get("text", "")).strip(), body.get("target")
        if not text or len(text) > 4000:
            raise ApiError("Matn bo'sh yoki juda uzun (4000 belgigacha).")
        if target not in ("users", "chans", "both"):
            raise ApiError("Kimga yuborilishi noto'g'ri.")
        markup, bt, bu = None, str(body.get("btn_text", "")).strip(), str(body.get("btn_url", "")).strip()
        if bt and bu:
            if not re.match(r"https?://", bu):
                raise ApiError("Havola https:// bilan boshlanishi kerak.")
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=bt[:40], url=bu)]])
        if body.get("test"):
            try:
                await bot.send_message(user["id"], text, reply_markup=markup)
            except Exception as e:
                raise ApiError("Xabar formati xato: " + str(e)[:90])
            return {"test": True}
        if any(j["state"] == "run" for j in jobs.values()):
            raise ApiError("Boshqa yuborish davom etmoqda.")
        ids = []
        if target in ("users", "both"):
            ids += [r["id"] for r in db.execute("SELECT id FROM users WHERE banned=0")]
        if target in ("chans", "both"):
            ids += [c["id"] for c in connected_channels()]
        jid = str(int(time.time() * 1000))
        job = jobs[jid] = {"state": "run", "total": len(ids), "sent": 0, "failed": 0}

        async def run():
            for to in ids:
                for _ in range(2):
                    try:
                        await bot.send_message(to, text, reply_markup=markup)
                        job["sent"] += 1
                        break
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after + 1)
                    except Exception:
                        job["failed"] += 1
                        break
                await asyncio.sleep(0.05)
            job["state"] = "done"
        t = asyncio.create_task(run())
        running.add(t)
        t.add_done_callback(running.discard)
        return {"job": jid, **job}

    async def bc_status(user, body):
        j = jobs.get(str(body.get("job")))
        if not j:
            raise ApiError("Topilmadi.", 404)
        return dict(j)

    async def bc_info(user, body):
        return {"users": one("SELECT COUNT(*) FROM users WHERE banned=0"), "chans": len(connected_channels())}

    # ---------- promokodlar ----------
    async def promos(user, body):
        return {"rows": [dict(r) for r in db.execute("SELECT code,points,max_uses,used FROM promos ORDER BY rowid DESC")]}

    async def promos_add(user, body):
        code = str(body.get("code", "")).strip().upper()
        try:
            pts, mx = int(body.get("points", 0)), int(body.get("max_uses", 0))
        except (TypeError, ValueError):
            raise ApiError("Ball va limit raqam bo'lishi kerak.")
        if not re.fullmatch(r"[A-Z0-9_\-]{3,32}", code) or pts < 1 or mx < 1:
            raise ApiError("Kod 3–32 belgi (A-Z, 0-9), ball va limit 1 dan katta bo'lsin.")
        db.execute("INSERT OR REPLACE INTO promos(code,points,max_uses,used) VALUES(?,?,?,0)", (code, pts, mx))
        db.commit()
        return await promos(user, body)

    async def promos_remove(user, body):
        code = str(body.get("code", "")).upper()
        db.execute("DELETE FROM promos WHERE code=?", (code,))
        db.execute("DELETE FROM promo_uses WHERE code=?", (code,))
        db.commit()
        return await promos(user, body)

    # ---------- ball do'koni ----------
    async def shop(user, body):
        return {"rows": [dict(r) for r in db.execute("SELECT id,title,price FROM shop ORDER BY id DESC")]}

    async def shop_add(user, body):
        title = str(body.get("title", "")).strip()[:80]
        try:
            price = int(body.get("price", 0))
        except (TypeError, ValueError):
            raise ApiError("Narx raqam bo'lishi kerak.")
        if not title or price < 1:
            raise ApiError("Nom va narx (1 dan katta) kiriting.")
        db.execute("INSERT INTO shop(title,price) VALUES(?,?)", (title, price))
        db.commit()
        return await shop(user, body)

    async def shop_remove(user, body):
        db.execute("DELETE FROM shop WHERE id=?", (int(body.get("id", 0)),))
        db.commit()
        return await shop(user, body)

    # ---------- majburiy kanallar ----------
    def reqch_rows():
        out = []
        for r in req_channels():
            d = dict(r)
            d["kind"] = d.get("kind") or "normal"
            d["pending"] = one("SELECT COUNT(*) FROM join_reqs WHERE chat_id=? AND status='pending'", d["chat_id"])
            out.append(d)
        return out

    async def reqch(user, body):
        return {"rows": reqch_rows()}

    async def reqch_add(user, body):
        ref, kind = str(body.get("ref", "")).strip(), body.get("kind", "normal")
        if kind not in ("normal", "request"):
            raise ApiError("Kanal turi noto'g'ri.")
        given_link, lm = None, LINK_RE.search(ref)
        if lm:        # yopiq kanal taklif havolasi: bot admin bo'lgan, tanish kanallar orasidan topiladi
            target = None
            for r in db.execute("SELECT chat_id FROM known_chats ORDER BY ts DESC LIMIT 60").fetchall():
                try:
                    if lm.group(1) in (await bot.get_chat(r["chat_id"])).invite_link or "":
                        target, given_link = r["chat_id"], "https://t.me/+" + lm.group(1)
                        break
                except Exception:
                    continue
            if target is None:
                raise ApiError("Havola bo'yicha kanal topilmadi. Botni kanalga admin qiling, kanalga biror xabar yozing va ro'yxatdan tanlang.")
        elif re.fullmatch(r"-?\d{6,16}", ref):
            target = int(ref)
        elif re.fullmatch(r"@?[A-Za-z0-9_]{4,32}", ref):
            target = "@" + ref.lstrip("@")
        else:
            raise ApiError("Ro'yxatdan tanlang yoki @username, ID yoki taklif havolasini yozing.")
        try:
            chat = await bot.get_chat(target)
        except Exception:
            raise ApiError("Kanal topilmadi. Bot kanalda adminmi?")
        try:
            me = await bot.me()
            if (await bot.get_chat_member(chat.id, me.id)).status != "administrator":
                raise ApiError("Bot bu kanalda administrator emas.")
        except ApiError:
            raise
        except Exception:
            raise ApiError("Tekshirib bo'lmadi: bot kanalda adminmi?")
        link = None
        if kind == "normal" and not chat.username and given_link:
            link = given_link                              # yopiq oddiy kanal: o'zingizning havolangiz ishlatiladi
        elif kind == "request" or not chat.username:      # zayafka yoki yopiq kanal: havolani bot o'zi yaratadi
            try:
                link = (await bot.create_chat_invite_link(chat.id, name="Bot", creates_join_request=(kind == "request"))).invite_link
            except Exception:
                raise ApiError("Havola yaratib bo'lmadi: botga «Foydalanuvchilarni taklif qilish» huquqini bering.")
        db.execute("INSERT OR REPLACE INTO req_channels(chat_id,title,username,kind,link) VALUES(?,?,?,?,?)",
                   (chat.id, chat.title or chat.username or str(chat.id), chat.username or "", kind, link))
        db.commit()
        on_req_change and on_req_change()
        return {"rows": reqch_rows()}

    async def reqch_known(user, body):
        have = {r["chat_id"] for r in req_channels()}
        me, rows = await bot.me(), []
        for r in db.execute("SELECT chat_id,title,username FROM known_chats ORDER BY ts DESC LIMIT 40").fetchall():
            if r["chat_id"] in have:
                continue
            try:
                if (await bot.get_chat_member(r["chat_id"], me.id)).status == "administrator":
                    rows.append({"id": r["chat_id"], "title": r["title"], "username": r["username"] or ""})
            except Exception:
                continue
        return {"rows": rows}

    def req_ch(cid):
        r = db.execute("SELECT * FROM req_channels WHERE chat_id=?", (cid,)).fetchone()
        if not r:
            raise ApiError("Kanal topilmadi.", 404)
        return dict(r)

    async def reqch_info(user, body):
        ch = req_ch(int(body.get("id", 0)))
        cid, kind = ch["chat_id"], ch.get("kind") or "normal"
        try:
            members = await bot.get_chat_member_count(cid)
        except Exception:
            members = None
        users = one("SELECT COUNT(*) FROM users WHERE banned=0")
        via = one("SELECT COUNT(*) FROM req_pass WHERE chat_id=?", cid)
        day0 = int(datetime.now(UZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        info = {"title": ch["title"], "username": ch["username"], "kind": kind, "link": ch.get("link") or "",
                "members": members, "via_bot": via, "users": users,
                "today": one("SELECT COUNT(*) FROM req_pass WHERE chat_id=? AND ts>=?", cid, day0),
                "week": one("SELECT COUNT(*) FROM req_pass WHERE chat_id=? AND ts>=?", cid, day0 - 6 * 86400),
                "pct_users": round(via / users * 100, 1) if users else 0,
                "pct_members": round(via / members * 100, 1) if members else 0}
        if kind == "request":
            for st in ("pending", "approved", "declined"):
                info[st] = one("SELECT COUNT(*) FROM join_reqs WHERE chat_id=? AND status=?", cid, st)
        return {"info": info}

    async def reqch_requests(user, body):
        cid = int(body.get("id", 0))
        rows = db.execute("""SELECT user_id,name,username,ts,status FROM join_reqs WHERE chat_id=?
                             ORDER BY (status='pending') DESC, ts DESC LIMIT 100""", (cid,)).fetchall()
        return {"rows": [dict(r) for r in rows]}

    async def reqch_decide(user, body):
        cid, approve = int(body.get("id", 0)), bool(body.get("approve"))
        if body.get("all"):
            ids = [r[0] for r in db.execute("SELECT user_id FROM join_reqs WHERE chat_id=? AND status='pending' LIMIT 200", (cid,))]
        else:
            ids = [int(body.get("user_id", 0))]
        ok = fail = 0
        for uid in ids:
            try:
                await (bot.approve_chat_join_request if approve else bot.decline_chat_join_request)(cid, uid)
                db.execute("UPDATE join_reqs SET status=? WHERE chat_id=? AND user_id=?", ("approved" if approve else "declined", cid, uid))
                ok += 1
            except Exception:
                db.execute("UPDATE join_reqs SET status=? WHERE chat_id=? AND user_id=?", ("approved" if approve else "declined", cid, uid))
                fail += 1     # ariza eskirgan yoki foydalanuvchi allaqachon qo'shilgan
            await asyncio.sleep(0.05)
        db.commit()
        return {"ok_count": ok, "fail_count": fail}

    async def reqch_remove(user, body):
        cid = int(body.get("id", 0))
        db.execute("DELETE FROM req_channels WHERE chat_id=?", (cid,))
        db.execute("DELETE FROM join_reqs WHERE chat_id=?", (cid,))
        db.execute("DELETE FROM req_pass WHERE chat_id=?", (cid,))
        db.commit()
        on_req_change and on_req_change()
        return {"rows": reqch_rows()}

    # ---------- battle / konkurslar ----------
    def battle_rows():
        return [dict(r) for r in db.execute(
            """SELECT id, name, channel_username AS username, status,
               (SELECT COUNT(*) FROM b_votes v WHERE v.battle_id=battles.id) AS votes,
               (SELECT COUNT(*) FROM b_part p WHERE p.battle_id=battles.id) AS parts
               FROM battles ORDER BY (status='active') DESC, id DESC LIMIT 40""")]

    def contest_rows():
        return [dict(r) for r in db.execute(
            """SELECT id, 'Konkurs #' || id AS name, channel_username AS username, status, 0 AS votes,
               (SELECT COUNT(*) FROM contest_users u WHERE u.contest_id=contests.id) AS parts
               FROM contests ORDER BY (status='active') DESC, id DESC LIMIT 40""")]

    async def battles(user, body):
        return {"rows": battle_rows()}

    async def contests(user, body):
        return {"rows": contest_rows()}

    async def battles_finish(user, body):
        bid = int(body.get("id", 0))
        if not db.execute("SELECT 1 FROM battles WHERE id=? AND status='active'", (bid,)).fetchone():
            raise ApiError("Faol battle topilmadi.", 404)
        await games.battle_finish(bot, bid)
        return {"rows": battle_rows()}

    async def contests_finish(user, body):
        cid = int(body.get("id", 0))
        if not db.execute("SELECT 1 FROM contests WHERE id=? AND status='active'", (cid,)).fetchone():
            raise ApiError("Faol konkurs topilmadi.", 404)
        await games.contest_finish(bot, cid)
        return {"rows": contest_rows()}

    app.router.add_get("/admin", page)
    for path, fn in (("me", me), ("stats", stats), ("admins", admins), ("admins/add", admins_add),
                     ("admins/remove", admins_remove), ("emoji", emoji_list), ("emoji/save", emoji_save),
                     ("restart", restart), ("users", users_search), ("users/ban", users_ban),
                     ("users/points", users_points), ("broadcast", bc_start), ("broadcast/status", bc_status),
                     ("broadcast/info", bc_info),
                     ("promos", promos), ("promos/add", promos_add), ("promos/remove", promos_remove),
                     ("shop", shop), ("shop/add", shop_add), ("shop/remove", shop_remove),
                     ("reqch", reqch), ("reqch/add", reqch_add), ("reqch/remove", reqch_remove), ("reqch/info", reqch_info), ("reqch/known", reqch_known),
                     ("reqch/requests", reqch_requests), ("reqch/decide", reqch_decide),
                     ("battles", battles), ("battles/finish", battles_finish),
                     ("contests", contests), ("contests/finish", contests_finish)):
        app.router.add_post(f"/api/admin/{path}", api(fn))
