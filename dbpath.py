"""Baza fayli yo'lini aniqlaydi.

DB_PATH ko'rsatilgan papkani yaratishga/yozishga urinadi. Papka yo'q yoki yozib bo'lmasa
(masalan Render'da Persistent Disk ulanmagan), loyiha papkasidagi bot.db ga o'tadi va ogohlantiradi.
"""
import logging
import os

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("db")


def resolve() -> str:
    want = os.getenv("DB_PATH", "bot.db")
    folder = os.path.dirname(os.path.abspath(want))
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return want
    except OSError as e:
        fallback = os.path.join(HERE, "bot.db")
        print(f"⚠️ DB_PATH={want!r} ishlamadi ({e}). {fallback} ishlatiladi: "
              "ma'lumotlar har restartda O'CHADI. Render'da Persistent Disk ulang (mount: /data).", flush=True)
        return fallback


DB_PATH = resolve()
