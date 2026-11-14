"""
Multi-akkaunt aniqlash: Telegram Mini App orqali qurilma belgisini yig'adi.

Ishlashi:
 1. Foydalanuvchi ovoz bermoqchi bo'lganda bot unga Mini App tugmasini yuboradi.
 2. Mini App brauzer belgilarini (fingerprint) + qurilmada saqlanadigan doimiy ID (did) ni
    yig'ib, Telegram initData bilan birga serverga yuboradi.
 3. Server initData imzosini tekshiradi (soxta user_id bo'lmasligi uchun), qurilmani yozadi.
 4. Bir qurilmadan (did yoki fp+IP bir xil) MAX_PER_DEVICE tadan ko'p akkaunt bo'lsa - ovoz bermaydi.

Eslatma: Telegram qurilma ID sini bermaydi. Bu 100% kafolat emas, lekin ko'pchilikni ushlaydi.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

# ----------------------------- sozlamalar -----------------------------------
WEBAPP_URL = os.getenv("WEBAPP_URL", "")        # masalan https://sizning-domen.uz  (HTTPS shart!)
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
MAX_PER_DEVICE = 1          # bitta qurilmadan nechta akkaunt ovoz bera oladi
INITDATA_MAX_AGE = 3600     # initData necha soniya yaroqli
REPORT_MIN_GROUP = int(os.getenv("MULTI_REPORT_MIN", "3"))  # shuncha akkaunt bir qurilmada bo'lsa admin ga xabar beriladi

_db_one = _db_all = _db_exec = None
_bot_token = ""
_notify = None              # async def notify(ids: list[int]) - adminga xabar


def setup(db_one, db_all, db_exec, bot_token: str, notify=None):
    global _db_one, _db_all, _db_exec, _bot_token, _notify
    _db_one, _db_all, _db_exec, _bot_token, _notify = db_one, db_all, db_exec, bot_token, notify


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
    user_id INTEGER,
    did TEXT,            -- qurilmada saqlanadigan doimiy ID (localStorage/cookie/IndexedDB)
    fp TEXT,             -- brauzer/qurilma belgilari xeshi
    ip TEXT,
    platform TEXT,
    created_at INTEGER,
    PRIMARY KEY(user_id, did, fp)
);
CREATE INDEX IF NOT EXISTS idx_dev_did ON devices(did);
CREATE INDEX IF NOT EXISTS idx_dev_fp_ip ON devices(fp, ip);
CREATE TABLE IF NOT EXISTS multi_reports(
    did TEXT PRIMARY KEY,   -- shu qurilma uchun adminga yuborilgan eng katta guruh hajmi
    size INTEGER
);
"""


async def init_schema(db_exec_script):
    await db_exec_script(SCHEMA)


# ----------------------------- initData tekshiruvi --------------------------
def validate_init_data(init_data: str):
    """Telegram imzosini tekshiradi. To'g'ri bo'lsa user dict, bo'lmasa None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got_hash = pairs.pop("hash", "")
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", _bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > INITDATA_MAX_AGE:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote) or ""


# ----------------------------- qurilma mantig'i -----------------------------
async def accounts_on_device(did: str, fp: str, ip: str) -> set[int]:
    """Shu qurilma belgilariga mos barcha user_id lar.
    Kuchli moslik: did bir xil. O'rtacha moslik: fp va IP ikkalasi bir xil."""
    ids = set()
    for r in await _db_all("SELECT DISTINCT user_id FROM devices WHERE did=?", (did,)):
        ids.add(r["user_id"])
    for r in await _db_all("SELECT DISTINCT user_id FROM devices WHERE fp=? AND ip=?", (fp, ip)):
        ids.add(r["user_id"])
    return ids


async def register_device(user: dict, did: str, fp: str, ip: str, platform: str) -> dict:
    uid = user["id"]
    others = (await accounts_on_device(did, fp, ip)) - {uid}
    await _db_exec(
        "INSERT OR IGNORE INTO devices(user_id, did, fp, ip, platform, created_at) VALUES(?,?,?,?,?,?)",
        (uid, did, fp, ip, platform, int(time.time())),
    )
    group = others | {uid}
    allowed = len(others) < MAX_PER_DEVICE
    if len(group) >= REPORT_MIN_GROUP and _notify:
        # bir xil guruh haqida qayta-qayta yozmaslik: faqat guruh kattalashganda xabar beriladi
        prev = await _db_one("SELECT size FROM multi_reports WHERE did=?", (did,))
        if not prev or len(group) > prev["size"]:
            await _db_exec("INSERT OR REPLACE INTO multi_reports(did, size) VALUES(?,?)",
                           (did, len(group)))
            try:
                await _notify(sorted(group))
            except Exception:
                logging.exception("multi-akkaunt xabari yuborilmadi")
    return {"ok": True, "allowed": allowed, "group": len(group)}


async def is_verified(user_id: int) -> bool:
    """Foydalanuvchi Mini App orqali tekshiruvdan o'tganmi va ruxsat berilganmi."""
    row = await _db_one("SELECT did, fp, ip FROM devices WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                        (user_id,))
    if not row:
        return False
    others = (await accounts_on_device(row["did"], row["fp"], row["ip"])) - {user_id}
    if len(others) < MAX_PER_DEVICE:
        return True
    # boshqa akkaunt(lar) oldin tekshiruvdan o'tgan bo'lsa, birinchi ro'yxatdan o'tgan akkaunt ruxsat oladi
    allowed_ids = {r["user_id"] for r in await _db_all(
        "SELECT user_id FROM devices WHERE did=? OR (fp=? AND ip=?) ORDER BY created_at ASC LIMIT ?",
        (row["did"], row["fp"], row["ip"], MAX_PER_DEVICE))}
    return user_id in allowed_ids


# ----------------------------- HTTP server ----------------------------------
async def h_verify(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    user = validate_init_data(data.get("initData", ""))
    if not user:
        return web.json_response({"ok": False, "error": "initData yaroqsiz"}, status=403)
    did = str(data.get("did", ""))[:64]
    fp = str(data.get("fp", ""))[:128]
    if len(did) < 8 or len(fp) < 8:
        return web.json_response({"ok": False, "error": "belgilar yetarli emas"}, status=400)
    res = await register_device(user, did, fp, client_ip(request), str(data.get("platform", ""))[:32])
    return web.json_response(res)


async def h_index(request: web.Request):
    path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
    return web.FileResponse(path)


async def start_server():
    app = web.Application()
    app.router.add_get("/", h_index)
    app.router.add_post("/verify", h_verify)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    logging.info("Mini App server: port %s", WEB_PORT)
