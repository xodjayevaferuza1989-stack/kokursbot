"""Qurilmani tasdiqlash uchun Web App serveri (aiohttp)."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

import games

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("webapp")
_tasks = set()


def _task_done(t):
    _tasks.discard(t)
    if not t.cancelled() and t.exception():
        log.error("after_verify xatosi", exc_info=t.exception())


def check_init_data(init_data: str, token: str, max_age: int = 86400):
    """Telegram WebApp initData imzosini tekshiradi. To'g'ri bo'lsa user dict qaytaradi."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", None)
    if not got or "user" not in pairs:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def setup(app: web.Application, bot, token: str):
    salt = hashlib.sha256(("ip" + token).encode()).hexdigest()

    async def page(_):
        with open(os.path.join(HERE, "verify.html"), encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def api_verify(request: web.Request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        user = check_init_data(str(data.get("initData", "")), token)
        if not user:
            log.warning("initData imzosi noto'g'ri yoki eskirgan (BOT_TOKEN to'g'rimi?)")
            return web.json_response({"ok": False, "error": "auth"}, status=403)
        dev_id = str(data.get("dev_id", ""))
        fp = str(data.get("fp", ""))
        if not re.fullmatch(r"[0-9a-zA-Z\-]{0,64}", dev_id) or not re.fullmatch(r"[0-9a-f]{64}", fp):
            return web.json_response({"ok": False, "error": "data"}, status=400)
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.remote or "")
        ip_h = hashlib.sha256((salt + ip).encode()).hexdigest()
        try:
            games.save_device(user, dev_id, fp, ip_h)
        except Exception:
            log.exception("save_device xatosi")
            return web.json_response({"ok": False, "error": "db"}, status=500)
        t = asyncio.create_task(games.after_verify(bot, user))
        _tasks.add(t)
        t.add_done_callback(_task_done)
        log.info("qurilma tasdiqlandi: user=%s", user.get("id"))
        return web.json_response({"ok": True})

    app.router.add_get("/verify", page)
    app.router.add_post("/api/verify", api_verify)
