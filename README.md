# Batl bot — Render'ga deploy

## Fayllar
bot.py, games.py, webapp.py, verify.html, emojis.py, requirements.txt, render.yaml, .python-version

## Deploy (Render)
1. Papkani GitHub'ga push qiling (yangi repo).
2. Render → New → Blueprint → repo'ni tanlang (render.yaml avtomatik o'qiladi).
   Qo'lda qilsangiz: New → Web Service, Build: `pip install -r requirements.txt`, Start: `python bot.py`.
3. Environment o'zgaruvchilari:
   - BOT_TOKEN   — @BotFather tokeni
   - ADMIN_IDS   — admin ID'lari, vergul bilan (123,456)
   - WEBAPP_URL  — https://<servis-nomi>.onrender.com  (qurilma tekshiruvi uchun)
   - DB_PATH     — /data/bot.db  (Persistent Disk, mount: /data)
   - Emoji ko'rinishi — oddiy Unicode emojilar; premium emoji ID'lari ishlatilmaydi.
4. Faqat BITTA instance ishlating (polling).

## Muhim
- Persistent Disk faqat pullik rejada (Starter). Bepul rejada bot.db har restartda o'chadi
  va servis 15 daqiqadan keyin uxlaydi.
- Disk ulamasangiz ma'lumotlar yo'qoladi.

## Kanal buyruqlari (bot kanalda admin bo'lishi kerak)
- `#battil` — shu kanalga battle posti chiqadi (tugash vaqti yo'q, qo'lda tugatiladi).
- `#tuga` — shu kanaldagi faol battle tugatiladi, natijalar e'lon qilinadi.
- `#kick 123456789` — foydalanuvchi shu kanaldan 1 soatga ban qilinadi (`#kick 123456789 3` = 3 soat). Ovozlari avtomatik olib tashlanadi.
  Guruhda admin odamning xabariga `#kick` deb javob bersa ham ishlaydi. Adminlar ban qilinmaydi.

## Admin panel (/admin)
- 🔒 Majburiy kanallar — botdan foydalanish uchun obuna shart bo'lgan kanallar (bot kanalda admin, kanal ochiq bo'lishi kerak).
  Adminlar bundan ozod. Obunasiz foydalanuvchiga kanal tugmalari va «Tekshirish» chiqadi; deep-link (ovoz/qatnashish) obunadan keyin davom etadi.
- 📢 Xabar yuborish — kimga: foydalanuvchilarga / ulangan kanallarga / ikkalasiga. Yuborishdan oldin tasdiqlash so'raladi.
- 📋 Ulangan kanallar — battle/konkurs yaratilgan kanallar ro'yxati.

## Web App admin panel (/admin → «🖥 Web panelni ochish»)
Faqat adminlar uchun (Telegram imzosi + admin ro'yxati tekshiriladi). WEBAPP_URL sozlangan bo'lishi shart.
- 📊 Statistika: foydalanuvchilar, battle/konkurs, kanallar, 7 kunlik o'sish grafigi.
- 🛡 Adminlar: ID bo'yicha qo'shish/o'chirish (bazada saqlanadi; ADMIN_IDS dagilar asosiy admin, o'chirib bo'lmaydi).
- ✨ Emoji: barcha joylarda oddiy Unicode emojilar ishlatiladi.
  ro'yxat tartibida yuborasiz → bot ID ro'yxatini qaytaradi → panelga tashlaysiz. Saqlagach «Qo'llash» botni qayta ishga tushiradi.
- 🎟 Promokodlar (ishlatilgan/limit, qo'shish, o'chirish), 🛍 Ball do'koni, 🔒 Majburiy kanallar, ⚔️ Battlelar va 🏆 Konkurslar (tugatish) — «Boshqa» bo'limida.
- Bot admin menyusida ham: «🎫 Promokodlar ro'yxati» va «🛍 Mahsulotlar ro'yxati» (o'chirish tugmalari bilan).
- Premium emoji: hamma tugma uchun joy bor (67 ta). ID kiritilmasa oddiy emoji ko'rinadi.

## Multi-akkaunt himoyasi (battle)
Bir qurilmadan (qurilma tasdiqlash orqali aniqlanadi) 3 ta akkaunt ovoz bermoqchi bo'lsa → hammasi kanaldan 1 soatga ban, ovozlari o'chadi.
Ban tugagach yana urinishsa → battledan chetlatiladi, ovozlari o'chadi va kanalda battle postiga reply bilan e'lon qilinadi.
WEBAPP_URL (yoki Render URL) bo'lishi shart: qurilma tekshiruvi shunga bog'liq.

## Emoji
Bot premium/custom emoji ID'larini ishlatmaydi; xabar va tugmalarda oddiy Unicode emojilar ko'rsatiladi.
Shuning uchun kanal postlari va ularning tugmalari oddiy emoji bilan chiqadi. Botda Fragment username bo'lsa, Render'da CHANNEL_PREMIUM=1 qo'ying.

## Majburiy kanallar: turlari
- **Oddiy kanal** — ochiq (@username) yoki yopiq (ID: -100…) bo'lishi mumkin; yopiq bo'lsa bot oddiy taklif havolasini o'zi yaratadi.
- **Zayafka kanal** — ariza (join request) bilan kiriladi; ochiq yoki yopiq (ID: -100…) bo'ladi. Bot kanalda admin bo'lishi va «Foydalanuvchilarni taklif qilish» huquqiga ega bo'lishi kerak.
  Ariza yuborgan foydalanuvchi obuna hisoblanadi; arizalarni web paneldan tasdiqlash/rad etish mumkin.
- Web panel → Boshqa → Majburiy kanallar → kanalni bosing: obunachilar, botdan kirganlar, foizlar, zayafkalar, o'chirish.
- «Botdan kirganlar» = bot orqali obuna tekshiruvidan o'tgan foydalanuvchilar (shu funksiya yoqilgandan keyin hisoblanadi).

## Multi-akkaunt hisoboti
Battle egasiga (bot admini bo'lmasa ham) va adminlarga: battle havolasi, shu odam va barcha akkauntlari (@username yoki profil havolasi).
- Botni kanalga admin qilsangiz, bot adminlarga shu kanalning ID sini yuboradi (yopiq kanalni qo'shish uchun kerak).

## Yopiq kanalni qo'shish (havola bor, username yo'q)
Telegram Bot API taklif havolasidan kanalni o'zi aniqlay olmaydi, shuning uchun:
1. Botni kanalga admin qiling (yoki mavjud kanalga biror xabar yozing): bot kanalni eslab qoladi.
2. Web panel → Majburiy kanallar → ➕ → «Bot admin bo'lgan kanallar» ro'yxatidan tanlang (yoki taklif havolasini yopishtiring).
