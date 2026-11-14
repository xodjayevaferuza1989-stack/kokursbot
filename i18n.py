"""O'zbekcha matnni ruschaga o'giradi (bo'laklar bo'yicha almashtirish).

Bot matnlari o'zbekcha yoziladi. Foydalanuvchi tili «ru» bo'lsa, yuborishdan oldin
shu yerdagi lug'at bo'yicha o'giriladi. Lug'atda yo'q matn o'zgarishsiz (o'zbekcha) ketadi.
"""
import re

# To'liq mos kelsa almashadigan qisqa tugma/so'zlar (emoji prefiksi bilan ham ishlaydi)
RU_EXACT = {
    "Til": "Язык", "Profil": "Профиль", "Tayyor": "Готово", "Yo'q": "Нет",
    "O'tkazib yuborish": "Пропустить", "Qo'lda yakunlayman": "Завершу вручную",
    "Murojaat": "Обращение", "Qo'llanma": "Руководство", "Bekor qilish": "Отмена",
    "Admin panel": "Админ-панель", "Avto konkurs": "Авто-конкурс",
    "Battle yaratish": "Создать баттл", "KONKURS yaratish": "Создать КОНКУРС",
    "Mening battlelarim": "Мои баттлы", "Mening konkurslarim": "Мои конкурсы",
}

RU = {
    # --- yaratish ---
    "Battle nomini kiriting": "Введите название баттла",
    "Konkurs nomini kiriting": "Введите название конкурса",
    "Misol:": "Пример:", "• Yozgi batl": "• Летний баттл", "• iPhone yutib oling": "• Выиграйте iPhone",
    "Battle yaratish": "Создать баттл", "Konkurs yaratish": "Создать конкурс",
    "Battle posti uchun matn yuboring (shartlar, sovrinlar, o'rinlar). Xohlasangiz 1 tadan 10 tagacha rasm/video yoki bitta GIF ham biriktiring.\n<i>Albom bo'lsa, ko'rinishi kerak bo'lgan tartibda yuboring.</i>\n\nTugatgach «Tayyor» tugmasini bosing.":
        "Отправьте текст для поста баттла (условия, призы, места). При желании добавьте от 1 до 10 фото/видео или один GIF.\n<i>Если это альбом, отправляйте в нужном порядке.</i>\n\nКогда закончите, нажмите «Готово».",
    "Konkurs posti uchun matn yuboring (shartlar, sovrinlar). Xohlasangiz 1 tadan 10 tagacha rasm/video yoki bitta GIF ham biriktiring.\n<i>Agar fayllar bittadan ko'p bo'lsa, post karusel (albom) bo'ladi.</i>\n\nTugatgach «Tayyor» tugmasini bosing.":
        "Отправьте текст для поста конкурса (условия, призы). При желании добавьте от 1 до 10 фото/видео или один GIF.\n<i>Если файлов больше одного, пост будет каруселью (альбомом).</i>\n\nКогда закончите, нажмите «Готово».",
    "Avval matn yoki media yuboring.": "Сначала отправьте текст или медиа.",
    "Kanalni yuboring (masalan <code>@kanal</code>).\nPost shu kanalga chiqadi va ovoz berish ham shu yerda bo'ladi. Bot kanalda admin bo'lishi kerak.":
        "Отправьте канал (например <code>@kanal</code>).\nПост выйдет в этом канале, голосование тоже будет здесь. Бот должен быть администратором канала.",
    "Kanalni yuboring (masalan <code>@kanal</code>).\nPost shu kanalga chiqadi, ishtirokchilar kanalga obuna bo'lishi shart bo'ladi, boost ham shu kanal uchun hisoblanadi. Bot kanalda admin bo'lishi kerak.":
        "Отправьте канал (например <code>@kanal</code>).\nПост выйдет в этом канале, участники должны быть подписаны на канал, буст тоже считается для него. Бот должен быть администратором канала.",
    "Maksimum 10 ta fayl.": "Максимум 10 файлов.",
    "GIF bilan boshqa media qo'shib bo'lmaydi.": "К GIF нельзя добавить другие медиа.",
    "Faqat matn, rasm, video yoki GIF yuboring.": "Отправьте только текст, фото, видео или GIF.",
    "Qabul qilindi. Yana yuborishingiz yoki «Tayyor» ni bosishingiz mumkin.":
        "Принято. Можно отправить ещё или нажать «Готово».",
    "Battle uchun kanal shart. Kanalni yuboring.": "Для баттла нужен канал. Отправьте канал.",
    "Qayta yuboring yoki bekor qiling.": "Отправьте снова или отмените.",
    "🏆 Nechta o'rin g'olib bo'lsin? (eng ko'p ovoz to'plagan top-N, masalan <code>5</code>)":
        "🏆 Сколько мест-победителей? (топ-N по голосам, например <code>5</code>)",
    "🏆 Nechta g'olib bo'lsin? (raqam yuboring, masalan <code>3</code>)":
        "🏆 Сколько будет победителей? (отправьте число, например <code>3</code>)",
    "1 dan 100 gacha raqam yuboring.": "Отправьте число от 1 до 100.",
    "Har bir o'rin uchun minimal ovozni vergul bilan yuboring.\nMisol: <code>99,50,25</code> (1-o'rin min 99, 2-o'rin min 50, 3-o'rin min 25)\nKerak bo'lmasa «Yo'q» ni bosing.":
        "Отправьте минимум голосов для каждого места через запятую.\nПример: <code>99,50,25</code> (1-е место мин. 99, 2-е мин. 50, 3-е мин. 25)\nЕсли не нужно, нажмите «Нет».",
    "Format: <code>99,50,25</code> yoki «Yo'q».": "Формат: <code>99,50,25</code> или «Нет».",
    "⏰ Tugash vaqtini yuboring (O'zbekiston vaqti):\n<code>": "⏰ Отправьте время окончания (по времени Узбекистана):\n<code>",
    "</code>\n\nYoki «Qo'lda yakunlayman» ni bosing.": "</code>\n\nИли нажмите «Завершу вручную».",
    "Format: <code>25.11.2026 20:00</code> (kelajakdagi vaqt bo'lsin).": "Формат: <code>25.11.2026 20:00</code> (время в будущем).",
    " Post ": " Пост в канал ", " kanaliga yuborildi.": " отправлен.",
    "\n⚠️ Kanalga yuborib bo'lmadi (bot adminligini tekshiring).": "\n⚠️ Не удалось отправить в канал (проверьте, что бот админ).",
    "Qatnashish havolasi": "Ссылка для участия", "Ishtirokchilar uchun havola": "Ссылка для участников", "Tayyor!": "Готово!",
    # --- kanal ulash / majburiy obuna ---
    "❌ <b>Ulanmadi</b>\nSabab: <b>": "❌ <b>Не удалось подключить</b>\nПричина: <b>",
    "user topilmadi": "пользователь не найден", "bu kanal emas": "это не канал", "kanal ochiq (public) emas": "канал не публичный",
    "admin emas": "не администратор", "botda xabar yuborish huquqi yo'q": "у бота нет права публиковать",
    "siz kanal admini emassiz": "вы не администратор канала", "kanalga post yuborib bo'lmadi": "не удалось отправить пост в канал",
    "Xatolik, keyinroq urinib ko'ring.": "Ошибка, попробуйте позже.", "Bosh menyu": "Главное меню",
    "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng «Tekshirish» ni bosing.":
        "🔒 Чтобы пользоваться ботом, подпишитесь на каналы ниже, затем нажмите «Проверить».",
    "✅ Tekshirish": "✅ Проверить", "⛔ Siz bloklangansiz.": "⛔ Вы заблокированы.",
    "Avval majburiy kanallarga obuna bo'ling.": "Сначала подпишитесь на обязательные каналы.",
    "Hali hamma kanalga obuna bo'lmagansiz.": "Вы ещё не подписались на все каналы.", "Rahmat! ✅": "Спасибо! ✅",
    # --- avto konkurs ---
    "Battle yaratildi": "Баттл создан", "Post shunday ko'rinadi:": "Пост будет выглядеть так:", "Kanal qo'shish": "Добавить канал",
    "Bu battle allaqachon ishga tushgan yoki topilmadi.": "Этот баттл уже запущен или не найден.",
    "Kanalingizni yuboring (masalan <code>@kanal</code>).\nBot kanalda admin bo'lishi kerak.":
        "Отправьте ваш канал (например <code>@kanal</code>).\nБот должен быть администратором канала.",
    "Boshqa kanal yuboring yoki bekor qiling.": "Отправьте другой канал или отмените.", "Ulandi:": "Подключено:",
    "Battle posti kanalga yuborildi.": "Пост баттла отправлен в канал.",
    "</code>\n\nBattleni «Mening battlelarim» bo'limidan yakunlaysiz.": "</code>\n\nЗавершить баттл можно в разделе «Мои баттлы».",
    "Battle @": "Баттл в канале @", "kanalida boshlandi!": "начался!",
    "🛑 Siz ": "🛑 Вы вышли из канала ", " kanalidan chiqib ketdingiz, shuning uchun bergan ovozingiz bekor qilindi.": ", поэтому ваш голос отменён.",
    "BATTLE BOSHLANADI": "БАТТЛ НАЧИНАЕТСЯ", "ENG KO'P OVOZ YIG'GAN ODAM G'OLIB BO'LADI": "ПОБЕЖДАЕТ ТОТ, КТО НАБЕРЁТ БОЛЬШЕ ВСЕГО ГОЛОСОВ",
    "AGAR KANALDAN CHIQIB KETSANGIZ, BERGAN OVOZINGIZ BEKOR QILINADI": "ЕСЛИ ВЫЙДЕТЕ ИЗ КАНАЛА, ВАШ ГОЛОС БУДЕТ ОТМЕНЁН",
    "BATTLEGA QO'YILGAN YUTUQLAR:": "ПРИЗЫ БАТТЛА:", "HOZIRCHA SIR": "ПОКА СЕКРЕТ",
    # --- post matni va tugmalar ---
    "G'oliblar soni:": "Количество победителей:", "Eng ko'p ovoz to'plagan": "Победителями станут",
    "</b> ta ishtirokchi g'olib bo'ladi.": "</b> участника(ов) с наибольшим числом голосов.", "-o'rin: min ": "-е место: мин. ",
    "Kanalga boost bergan ishtirokchining yutish imkoni 30% ga oshadi.": "У участника, отправившего буст каналу, шансы на победу выше на 30%.",
    "</b> da stop": "</b> — завершение", "Yakunlangan": "Завершено", "Qatnashish": "Участвовать", "QATNASHISH": "УЧАСТВОВАТЬ",
    "Ovoz berish uchun postga o'tish": "Перейти к посту для голосования", "Kanalga o'tish": "Перейти в канал",
    "Jonli reyting": "Живой рейтинг",
    # --- qurilma / ovoz / qatnashish ---
    "✅ Qurilmani tasdiqlash": "✅ Подтвердить устройство",
    "Ovoz berish / qatnashish uchun avval qurilmangizni tasdiqlang.\nPastdagi tugmani bosing, keyin kanalga qaytib, tugmani qayta bosing.":
        "Чтобы голосовать / участвовать, сначала подтвердите своё устройство.\nНажмите кнопку ниже, затем вернитесь в канал и нажмите кнопку снова.",
    "Botga o'ting va qurilmani tasdiqlang, so'ng qayta bosing.": "Перейдите в бота и подтвердите устройство, затем нажмите снова.",
    "Bu tadbir yakunlangan.": "Это мероприятие завершено.", "Avval ": "Сначала подпишитесь на канал ",
    " kanaliga obuna bo'ling, so'ng qayta bosing.": ", затем нажмите снова.",
    "Siz allaqachon ovoz bergansiz.": "Вы уже голосовали.", "O'zingizga ovoz bera olmaysiz.": "Нельзя голосовать за себя.",
    "Ishtirokchi topilmadi.": "Участник не найден.", "Ovozingiz qabul qilindi ✅": "Ваш голос принят ✅",
    "Siz allaqachon qatnashyapsiz.": "Вы уже участвуете.",
    "Qatnashish uchun Telegram sozlamalarida username o'rnating, keyin qayta bosing.":
        "Чтобы участвовать, установите username в настройках Telegram, затем нажмите снова.",
    "Siz battlega qo'shildingiz ✅": "Вы присоединились к баттлу ✅", "Siz «": "Вы «", "» battlega qo'shildingiz!": "» присоединились к баттлу!",
    "Ovoz to'plash uchun shu postni do'stlaringizga yuboring:": "Чтобы набрать голоса, отправьте этот пост друзьям:",
    "Siz konkursga qatnashdingiz!": "Вы участвуете в конкурсе!", "Sizda Telegram Premium bor-ku!": "У вас есть Telegram Premium!",
    "</b> kanaliga boost bering, shunda yutish imkoniyatingiz <b>30% ga</b> oshadi.":
        "</b>: отправьте ему буст — и ваши шансы на победу вырастут на <b>30%</b>.",
    "Kanalga boost berish": "Отправить буст каналу", "Boost berdim, tekshirish": "Я отправил буст, проверить",
    "Siz allaqachon qatnashgansiz.": "Вы уже участвуете.", "Siz qatnashdingiz ✅": "Вы участвуете ✅", "Topilmadi.": "Не найдено.",
    "Boost topildi! Yutish imkoniyatingiz 30% ga oshdi ✅": "Буст найден! Ваши шансы на победу выросли на 30% ✅",
    "Boost topilmadi. Avval kanalga boost bering, keyin qayta tekshiring.": "Буст не найден. Сначала отправьте буст каналу, затем проверьте снова.",
    # --- yakunlash ---
    "yakunlandi": "завершён", "Hech kim qatnashmadi.": "Никто не участвовал.", "Ishtirokchilar:": "Участники:", "Jami ovozlar:": "Всего голосов:",
    "🛑 Kanaldan chiqib ketgani uchun bekor qilingan ovozlar:": "🛑 Голосов отменено из-за выхода из канала:", "Natijalar:": "Результаты:",
    "❌ minimal ovoz yetmadi": "❌ не хватило минимума голосов", " (min ": " (мин. ", "Kim kimga ovoz berdi": "Кто за кого голосовал",
    "Qatnashchilar:": "Участники:", "Boost berganlar:": "Отправили буст:", "G'oliblar:": "Победители:",
    "Tabriklaymiz! Siz «": "Поздравляем! Вы «", "» konkursida g'olib bo'ldingiz!": "» стали победителем конкурса!",
    # --- mening tadbirlarim ---
    "Sizda hozircha battle yo'q.": "У вас пока нет баттлов.", "Sizda hozircha konkurs yo'q.": "У вас пока нет конкурсов.",
    "«Battle yaratish»": "«Создать баттл»", "«Konkurs yaratish»": "«Создать конкурс»",
    "tugmasi orqali yangisini yarating.": "— создайте новый через эту кнопку.", "Tanlang:": "Выберите:",
    "Holati: faol": "Статус: активен", "Holati: yakunlangan": "Статус: завершён", "ovozlar:": "голосов:", "Havola:": "Ссылка:",
    "🏁 Hozir yakunlash": "🏁 Завершить сейчас", "Bajarib bo'lmadi.": "Не удалось выполнить.", "Yakunlanmoqda...": "Завершаем...",
    # --- profil / til / qo'llanma / murojaat ---
    "Mening profilim": "Мой профиль", " Til: ": " Язык: ", " Ro'yxatdan o'tgan: ": " Регистрация: ",
    " Yaratgan battlelar: ": " Создано баттлов: ", " Qatnashgan battlelar: ": " Участие в баттлах: ",
    " Bergan ovozlar: ": " Отданные голоса: ", " Olgan ovozlar: ": " Полученные голоса: ", " Ballar: ": " Баллы: ",
    "Tilni tanlang:": "Выберите язык:", "Saqlandi ✅": "Сохранено ✅", "Murojaatingizni yozing:": "Напишите ваше обращение:",
    "Yuborildi ✅ Tez orada javob beramiz.": "Отправлено ✅ Скоро ответим.",
    "Qo'llanma": "Руководство",
    "<b>Battle:</b> post kanalga chiqadi. Ishtirokchilar bot havolasi orqali qo'shiladi (usernamesi bo'lishi shart), ularning tugmalari postda paydo bo'ladi. Odamlar kanalning o'zida tugmani bosib ovoz beradi. Tugagach top-N g'olib e'lon qilinadi, sizga esa kim kimga ovoz bergani yuboriladi.":
        "<b>Баттл:</b> пост выходит в канале. Участники добавляются по ссылке бота (нужен username), их кнопки появляются в посте. Люди голосуют, нажимая кнопку прямо в канале. По окончании объявляются топ-N победителей, а вам отправляется список «кто за кого голосовал».",
    "<b>Konkurs:</b> postdagi «Qatnashish» tugmasi botga o'tkazadi. Tugagach bot g'oliblarni tasodifiy tanlaydi. Kanalga boost bergan ishtirokchining yutish imkoni 30% ga oshadi.":
        "<b>Конкурс:</b> кнопка «Участвовать» в посте ведёт в бота. По окончании бот случайно выбирает победителей. У участника, отправившего буст каналу, шансы на победу выше на 30%.",
    "Bot kanalda admin bo'lishi shart.": "Бот обязательно должен быть администратором канала.",
}

# \bso'z\b ko'rinishidagi (regex) almashtirishlar
RU_RE = [(re.compile(r"\bovoz\b"), "голос(ов)")]

_SORTED = sorted(RU.items(), key=lambda kv: -len(kv[0]))


def ru(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if t in RU_EXACT:
        return text.replace(t, RU_EXACT[t])
    if " " in t:                       # "🌐 Til" kabi: emoji + matn
        head, rest = t.split(" ", 1)
        if rest in RU_EXACT and not head.isalnum():
            return text.replace(t, f"{head} {RU_EXACT[rest]}")
    for uz, r in _SORTED:
        if uz in text:
            text = text.replace(uz, r)
    for rx, r in RU_RE:
        text = rx.sub(r, text)
    return text


def ru_markup(rm):
    """Tugmalar matnini o'giradi (aiogram obyektlari o'zgarmas, shuning uchun nusxa olinadi)."""
    from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
    if isinstance(rm, InlineKeyboardMarkup):
        return rm.model_copy(update={"inline_keyboard": [
            [b.model_copy(update={"text": ru(b.text)}) for b in row] for row in rm.inline_keyboard]})
    if isinstance(rm, ReplyKeyboardMarkup):
        return rm.model_copy(update={"keyboard": [
            [b.model_copy(update={"text": ru(b.text)}) if hasattr(b, "text") else b for b in row]
            for row in rm.keyboard]})
    return rm
