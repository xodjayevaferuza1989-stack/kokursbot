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

Deploy tartibi:
  1. Yangi fayllarni GitHub ga push qiling, Render avtomatik qayta deploy qiladi.
  2. Telegramda /start yuboring, keyin /admin.
  3. Botni kanallarga ADMIN qilib qo'shing (post yuborish + xabarlarni o'chirish huquqi bilan).
