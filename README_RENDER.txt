KONKURSBOT - RENDER DEPLOYMENT (v2)

GitHub repozitoriyda aynan shu tuzilma bo'lsin:
  bot.py
  antimulti.py
  requirements.txt
  render.yaml
  .gitignore
  webapp/index.html

Render Web Service:
  Build Command:     pip install -r requirements.txt
  Start Command:     python bot.py
  Health Check Path: /

Environment variables:
  BOT_TOKEN        = BotFather bergan token (GitHub ga yozmang!)
  ADMIN_ID         = o'zingizning Telegram ID raqamingiz
  WEBAPP_URL       = https://SERVIS-NOMI.onrender.com   (Render bergan yakuniy HTTPS manzil)
  DB_PATH          = /var/data/bot.db                   (Disk mount: /var/data)
  MULTI_REPORT_MIN = 3   (bir qurilmadan nechta akkaunt kirsa adminga "multi akkaunt" xabari boradi)
  PYTHON_VERSION   = 3.12.8

Muhim:
- Disk (/var/data) bo'lmasa baza har deploy da o'chadi. Free plan uxlab qoladi, shuning uchun Starter plan kerak.
- WEBAPP_URL xizmatning o'zining HTTPS manzili bo'lishi shart.

YANGI IMKONIYATLAR
1) Admin panel: /admin yoki menyudagi "Admin panel" tugmasi (faqat ADMIN_ID uchun)
   - Foydalanuvchilar (ro'yxat, statistika, CSV yuklab olish)
   - ID / @username / ism orqali qidirish
   - Majburiy kanallar (qo'shish, o'chirish). Bot kanalda admin bo'lishi kerak.
   - Xabar yuborish: foydalanuvchilarga / ulangan kanallarga / ikkalasiga
2) Avto konkurs:
   - Botga "#konkurs" yozing (yoki "Avto konkurs" tugmasi), keyin "Kanal qo'shish".
     "#konkurs 3" desangiz 3 ta g'olib bo'ladi.
   - Kanalning o'zida (bot admin bo'lsa) "#konkurs" deb post yozsangiz, bot uni o'chirib,
     tayyor battle postini chiqaradi.
   - Kanal ulanmasa sabab ko'rsatiladi: "user topilmadi" / "admin emas" / ...
   - Kanaldan chiqib ketgan odamning ovozi bekor qilinadi (bot kanalda admin bo'lishi shart).
3) Multi akkaunt: bitta qurilmadan MULTI_REPORT_MIN ta va undan ko'p akkaunt Mini App
   orqali tekshirilsa, adminga akkauntlar ro'yxati bilan xabar boradi.
4) Mini App (webapp/index.html) yangi dizayn: animatsiya, konfetti, tema (qorong'i/yorug').

5) WEB ADMIN PANEL: WEBAPP_URL/admin (botdagi /admin ichidagi "🌐 Web panel" tugmasi orqali ochiladi)
   - Bosh (statistika), Odamlar (qidirish, karta, bloklash), Kanallar, Xabar, Multi-akkaunt, Adminlar
   - "Adminlar" bo'limi faqat EGA (ADMIN_ID) uchun: ID kiritib admin beradi va imkoniyatlarni tanlaydi:
     Foydalanuvchilar / Majburiy kanallar / Xabar yuborish / Multi-akkaunt / Bloklash
   - Admin berilgan odam avval botga /start yuborgan bo'lishi kerak (unga xabar boradi).
   - Bloklangan foydalanuvchi botdan ham, kanaldagi ovoz tugmalaridan ham foydalana olmaydi.
   - Xavfsizlik: har so'rov Telegram initData imzosi bilan tekshiriladi, ruxsatlar serverda tekshiriladi.

6) NATIJA RASMI: battle yakunlanganda kanalga va egasiga g'oliblar bilan chiroyli rasm (PNG) chiqadi.
   Pillow va assets/ papkasidagi shrift kerak (zip ichida bor). Rasm yasalmasa, oddiy matn yuboriladi.
7) JONLI REYTING: kanal postidagi va botdagi "📊 Jonli reyting" tugmasi WEBAPP_URL/rank?e=ID sahifasini ochadi
   (har 5 soniyada yangilanadi, o'rinlar almashganda animatsiya, g'oliblar chizig'i, qolgan vaqt, UZ/RU).
8) ADMIN JURNALI: kim kimni bloklagan, kanal qo'shgan/o'chirgan, xabar yuborgan, admin bergan - hammasi yoziladi.
   Faqat ega ko'radi: botda /admin -> "📜 Jurnal", webda "Jurnal" bo'limi.
9) TIL (uz/ru): "Til" tugmasi orqali tanlanadi. Menyu, xabarlar, tugmalar va Mini App tanlangan tilda chiqadi.
   Tarjimalar i18n.py ichida (o'zbekcha matn -> ruscha). Yangi matn qo'shsangiz, shu fayldagi lug'atga ham qo'shing,
   aks holda u o'zbekcha ketadi. Kanal postlari (ommaviy) o'zbekcha qoladi.

Deploy tartibi:
  1. Yangi fayllarni GitHub ga push qiling, Render avtomatik qayta deploy qiladi.
  2. Telegramda /start yuboring, keyin /admin.
  3. Botni kanallarga ADMIN qilib qo'shing (post yuborish + xabarlarni o'chirish huquqi bilan).
