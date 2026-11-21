"""
Uy Savat bot — OLX va Joymee'dagi uy egalarining yangi e'lonlarini kuzatadi.

Ko'p foydalanuvchili:
  /start -> til tanlash (o'zbek / rus) -> telefon raqam orqali ro'yxatdan o'tish
  Har bir foydalanuvchining filtri va yuborilgan e'lonlari alohida saqlanadi.
  Bot har bir bo'limni bir marta tekshiradi va yangi e'lonni filtri mos kelgan
  barcha foydalanuvchilarga yuboradi.
"""
import os
import re
import json
import time
import html
import sqlite3
import logging
import threading
from logging.handlers import RotatingFileHandler
import subprocess

from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = str(os.getenv("ADMIN_ID") or os.getenv("CHAT_ID") or "")
CITY = os.getenv("CITY", "tashkent")
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "240"))
MAX_SELLER_ADS = int(os.getenv("MAX_SELLER_ADS", "4"))
LATEST_N = int(os.getenv("LATEST_N", "5"))
LATEST_DAYS = int(os.getenv("LATEST_DAYS", "10"))
SHOW_SELLER_PHONE = os.getenv("SHOW_SELLER_PHONE", "1") == "1"
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()          # e'lonlar joylanadigan kanal (-100... yoki @nom)
CHANNEL_PHONE = os.getenv("CHANNEL_PHONE", "").strip()    # kanalda ko'rsatiladigan murojaat raqami
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))            # bepul sinov muddati
SUB_DAYS = int(os.getenv("SUB_DAYS", "30"))               # bitta to'lov necha kunlik
PRICE = int(os.getenv("PRICE", "49000"))                  # 1 oylik obuna narxi, so'm
PRICE_3 = int(os.getenv("PRICE_3", "129000"))             # 3 oylik obuna narxi, so'm
PLANS = {1: (SUB_DAYS, PRICE), 3: (SUB_DAYS * 3, PRICE_3)}   # tarif: (kun, narx)
PAY_CARD = os.getenv("PAY_CARD", "").strip()              # to'lov qabul qilinadigan karta
PAY_NAME = os.getenv("PAY_NAME", "").strip()              # karta egasining ismi

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
API = "https://www.olx.uz/api/v1"
# OLX server (hosting) IP manzillarini bloklaydi. Bot serverda turganda OLX so'rovlari
# uydagi kompyuter orqali o'tadi: u yerda SSH "ko'prik" (ssh -R 1080) ishlaydi.
OLX_PROXY = os.getenv("OLX_PROXY", "").strip()      # masalan socks5h://127.0.0.1:1080
OLX_PROXIES = {"http": OLX_PROXY, "https": OLX_PROXY} if OLX_PROXY else None
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "ru,uz;q=0.9"}
TZ = timezone(timedelta(hours=5))   # Toshkent vaqti

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              RotatingFileHandler("bot.log", maxBytes=2_000_000, backupCount=3,
                                                  encoding="utf-8")])
log = logging.getLogger("bot")

# ======================= MATNLAR (uz / ru) =======================

T = {
    "choose_lang": {"uz": "🇺🇿 Tilni tanlang\n🇷🇺 Выберите язык", "ru": "🇺🇿 Tilni tanlang\n🇷🇺 Выберите язык"},
    "ask_phone": {
        "uz": "📱 Ro'yxatdan o'tish uchun telefon raqamingizni yuboring.\nPastdagi tugmani bosing 👇",
        "ru": "📱 Для регистрации отправьте свой номер телефона.\nНажмите кнопку ниже 👇"},
    "btn_phone": {"uz": "📱 Raqamni yuborish", "ru": "📱 Отправить номер"},
    "own_phone": {"uz": "Iltimos, o'zingizning raqamingizni pastdagi tugma orqali yuboring.",
                  "ru": "Пожалуйста, отправьте свой номер через кнопку ниже."},
    "registered": {
        "uz": "✅ Ro'yxatdan o'tdingiz!\n\nEndi filtrlarni sozlang — bot OLX va Joymee'dagi "
              "uy egalarining sizga mos yangi e'lonlarini darhol yuboradi.",
        "ru": "✅ Вы зарегистрированы!\n\nНастройте фильтры — бот будет сразу присылать новые "
              "объявления от собственников с OLX и Joymee, которые вам подходят."},
    "lang_set": {"uz": "✅ Til: O'zbekcha", "ru": "✅ Язык: Русский"},
    "lang_page": {"uz": "🌐 <b>Til</b>\n\nBot tilini tanlang:", "ru": "🌐 <b>Язык</b>\n\nВыберите язык бота:"},
    "use_menu": {"uz": "Filtrlarni sozlash uchun /filtr ni bosing.",
                 "ru": "Чтобы настроить фильтры, нажмите /filtr."},
    "settings": {"uz": "⚙️ <b>Filtr sozlamalari</b>", "ru": "⚙️ <b>Настройки фильтра</b>"},
    "f_sources": {"uz": "🌐 <b>Saytlar:</b>", "ru": "🌐 <b>Сайты:</b>"},
    "f_deals": {"uz": "🏷 <b>Turi:</b>", "ru": "🏷 <b>Сделка:</b>"},
    "f_ptypes": {"uz": "🏠 <b>Mulk:</b>", "ru": "🏠 <b>Недвижимость:</b>"},
    "f_repairs": {"uz": "🛠 <b>Ta'mir:</b>", "ru": "🛠 <b>Ремонт:</b>"},
    "f_rooms": {"uz": "🚪 <b>Xonalar:</b>", "ru": "🚪 <b>Комнаты:</b>"},
    "f_districts": {"uz": "📍 <b>Tumanlar:</b>", "ru": "📍 <b>Районы:</b>"},
    "f_price_rent": {"uz": "💰 <b>Ijara narxi:</b>", "ru": "💰 <b>Цена аренды:</b>"},
    "f_price_sale": {"uz": "💰 <b>Sotuv narxi:</b>", "ru": "💰 <b>Цена продажи:</b>"},
    "status": {"uz": "Holat:", "ru": "Статус:"},
    "running": {"uz": "▶️ Ishlayapti", "ru": "▶️ Работает"},
    "paused": {"uz": "⏸ To'xtatilgan", "ru": "⏸ На паузе"},
    "all": {"uz": "hammasi", "ru": "все"},
    "any_price": {"uz": "farqi yo'q", "ru": "любая"},
    "from": {"uz": "${n} dan", "ru": "от ${n}"},
    "to": {"uz": "${n} gacha", "ru": "до ${n}"},
    "b_sources": {"uz": "🌐 Saytlar", "ru": "🌐 Сайты"},
    "b_deals": {"uz": "🏷 Turi", "ru": "🏷 Сделка"},
    "b_repairs": {"uz": "🛠 Ta'mir", "ru": "🛠 Ремонт"},
    "b_rooms": {"uz": "🚪 Xonalar", "ru": "🚪 Комнаты"},
    "b_districts": {"uz": "📍 Tumanlar", "ru": "📍 Районы"},
    "b_price": {"uz": "💰 Narx", "ru": "💰 Цена"},
    "b_last1": {"uz": "🆕 Oxirgi 24 soat", "ru": "🆕 За 24 часа"},
    "b_lastN": {"uz": "📅 Oxirgi {d} kunlik", "ru": "📅 За {d} дней"},
    "b_pause": {"uz": "⏸ To'xtatish", "ru": "⏸ Пауза"},
    "b_resume": {"uz": "▶️ Davom ettirish", "ru": "▶️ Возобновить"},
    "b_lang": {"uz": "🌐 Til / Язык", "ru": "🌐 Til / Язык"},
    "b_all": {"uz": "🔄 Hammasi", "ru": "🔄 Все"},
    "b_back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад"},
    "b_ptype_hdr": {"uz": "— 🏠 Mulk turi —", "ru": "— 🏠 Тип недвижимости —"},
    "t_sources": {"uz": "🌐 Qaysi saytlardan kelsin?", "ru": "🌐 С каких сайтов присылать?"},
    "t_deals": {"uz": "🏷 Ijara yoki sotuv?", "ru": "🏷 Аренда или продажа?"},
    "t_ptypes": {"uz": "🏠 Qaysi mulk turi kerak?", "ru": "🏠 Какой тип недвижимости?"},
    "l_ptype": {"uz": "Mulk", "ru": "Тип"},
    "t_repairs": {"uz": "🛠 Qaysi ta'mir turlari kelsin?\n(hech biri belgilanmasa, hammasi keladi)",
                  "ru": "🛠 Какой ремонт?\n(если ничего не выбрано — любой)"},
    "t_rooms": {"uz": "🚪 Necha xonali?\n(hech biri belgilanmasa, hammasi keladi)",
                "ru": "🚪 Сколько комнат?\n(если ничего не выбрано — любое)"},
    "t_districts": {"uz": "📍 Qaysi tumanlar?\n(hech biri belgilanmasa, hammasi keladi)",
                    "ru": "📍 Какие районы?\n(если ничего не выбрано — все)"},
    "t_price": {"uz": "💰 Qaysi narxni o'zgartirasiz? (dollarda)",
                "ru": "💰 Какую цену изменить? (в долларах)"},
    "p_rent": {"uz": "Ijara", "ru": "Аренда"},
    "p_sale": {"uz": "Sotuv", "ru": "Продажа"},
    "ask_lo": {"uz": "💰 <b>{name}</b>: eng <b>kam</b> narxni yozing ($)\n\nFaqat raqam, masalan: <code>300</code>\n"
                     "Chegara kerak bo'lmasa: <code>0</code>",
               "ru": "💰 <b>{name}</b>: напишите <b>минимальную</b> цену ($)\n\nТолько число, например: <code>300</code>\n"
                     "Без ограничения: <code>0</code>"},
    "ask_hi": {"uz": "💰 Endi eng <b>ko'p</b> narxni yozing ($)\n\nFaqat raqam, masalan: <code>700</code>\n"
                     "Chegara kerak bo'lmasa: <code>0</code>",
               "ru": "💰 Теперь <b>максимальную</b> цену ($)\n\nТолько число, например: <code>700</code>\n"
                     "Без ограничения: <code>0</code>"},
    "only_num": {"uz": "Faqat raqam yozing, masalan: 500 (chegara kerak bo'lmasa 0)",
                 "ru": "Напишите только число, например: 500 (без ограничения — 0)"},
    "saved": {"uz": "✅ Saqlandi: {v}", "ru": "✅ Сохранено: {v}"},
    "searching": {"uz": "🔎 {label} e'lonlar filtringiz bo'yicha qidirilmoqda... ({wait})",
                  "ru": "🔎 Ищу объявления {label} по вашему фильтру... ({wait})"},
    "lbl_1": {"uz": "Oxirgi 24 soatlik", "ru": "за последние 24 часа"},
    "lbl_n": {"uz": "Oxirgi {d} kunlik", "ru": "за последние {d} дней"},
    "wait_1": {"uz": "20–60 soniya", "ru": "20–60 секунд"},
    "wait_n": {"uz": "1–2 daqiqa", "ru": "1–2 минуты"},
    "busy": {"uz": "⏳ Hozir boshqa qidiruv ketyapti. Bir daqiqadan keyin qaytadan bosing.",
             "ru": "⏳ Сейчас идёт другой поиск. Попробуйте через минуту."},
    "none": {"uz": "{when} filtringizga mos yangi e'lon topilmadi (avval yuborilganlari qayta "
                   "yuborilmaydi). /filtr orqali filtrni kengaytirib ko'ring.",
             "ru": "{when} новых объявлений по вашему фильтру не найдено (уже отправленные не "
                   "повторяются). Попробуйте расширить фильтр через /filtr."},
    "when_1": {"uz": "Oxirgi 24 soatda", "ru": "За последние 24 часа"},
    "when_n": {"uz": "Oxirgi {d} kunda", "ru": "За последние {d} дней"},
    "done": {"uz": "✅ {when} {n} ta yangi e'lon yuborildi.", "ru": "✅ {when} отправлено новых объявлений: {n}."},
    "search_err": {"uz": "⚠️ Qidiruvda xato:", "ru": "⚠️ Ошибка при поиске:"},
    # pastki doimiy tugmalar
    "kb_filter": {"uz": "⚙️ Filtr", "ru": "⚙️ Фильтр"},
    "kb_last1": {"uz": "🆕 Oxirgi 24 soat", "ru": "🆕 За 24 часа"},
    "kb_lastN": {"uz": "📅 Oxirgi {d} kun", "ru": "📅 За {d} дней"},
    "kb_pause": {"uz": "⏸ To'xtatish", "ru": "⏸ Пауза"},
    "kb_resume": {"uz": "▶️ Davom ettirish", "ru": "▶️ Возобновить"},
    "kb_lang": {"uz": "🌐 Til", "ru": "🌐 Язык"},
    "kb_help": {"uz": "ℹ️ Yordam", "ru": "ℹ️ Помощь"},
    "b_done": {"uz": "✅ Tayyor", "ru": "✅ Готово"},
    "b_reset": {"uz": "🔄 Tozalash", "ru": "🔄 Сбросить"},
    "reset_done": {"uz": "🔄 Filtr tozalandi", "ru": "🔄 Фильтр сброшен"},
    "n_items": {"uz": "{n} ta", "ru": "{n} шт."},
    "st_on": {"uz": "🟢 <b>Faol</b> — yangi e'lonlar keladi", "ru": "🟢 <b>Активен</b> — новые объявления приходят"},
    "st_off": {"uz": "🔴 <b>To'xtatilgan</b> — e'lonlar kelmaydi", "ru": "🔴 <b>На паузе</b> — объявления не приходят"},
    "hint": {"uz": "<i>O'zgartirish uchun tugmani bosing 👇</i>", "ru": "<i>Нажмите кнопку, чтобы изменить 👇</i>"},
    "l_sources": {"uz": "Saytlar", "ru": "Сайты"},
    "l_deal": {"uz": "Turi", "ru": "Сделка"},
    "l_repairs": {"uz": "Ta'mir", "ru": "Ремонт"},
    "l_rooms": {"uz": "Xonalar", "ru": "Комнаты"},
    "l_districts": {"uz": "Tumanlar", "ru": "Районы"},
    "l_price": {"uz": "Narx", "ru": "Цена"},
    "filter_saved": {"uz": "✅ Filtr saqlandi.\nFiltringizga mos yangi e'lon chiqishi bilan sizga yuboraman.",
                     "ru": "✅ Фильтр сохранён.\nКак только появится подходящее новое объявление — пришлю."},
    "paused_msg": {"uz": "⏸ E'lon yuborish to'xtatildi. Qayta yoqish uchun «▶️ Davom ettirish» ni bosing.",
                   "ru": "⏸ Рассылка приостановлена. Чтобы включить, нажмите «▶️ Возобновить»."},
    "resumed_msg": {"uz": "▶️ E'lon yuborish yoqildi.", "ru": "▶️ Рассылка включена."},
    "main_menu": {"uz": "👇 Asosiy menyu", "ru": "👇 Главное меню"},
    "home": {"uz": "🏠 <b>Asosiy menyu</b>\nKerakli bo'limni tanlang:", "ru": "🏠 <b>Главное меню</b>\nВыберите раздел:"},
    "b_home": {"uz": "🏠 Asosiy menyu", "ru": "🏠 Главное меню"},
    "help": {
        "uz": "ℹ️ <b>Bot qanday ishlaydi</b>\n\n"
              "Bot OLX va Joymee'dagi <b>uy egalarining</b> yangi e'lonlarini kuzatadi va filtringizga "
              "mos kelganini darhol rasmlari, narxi va manzili bilan yuboradi.\n\n"
              "⚙️ <b>Filtr</b> — sayt, ijara/sotuv, mulk turi, ta'mir, xonalar, tuman va narxni tanlash\n"
              "🆕 <b>Oxirgi 24 soat</b> — bugungi mos e'lonlar\n"
              "📅 <b>Oxirgi {d} kun</b> — oxirgi {d} kundagi mos e'lonlar\n"
              "📢 <b>Kanal filtri</b> — yangi e'lonlarni o'z kanalingizga sizning raqamingiz bilan joylash\n"
              "⏸ <b>To'xtatish</b> — e'lon yuborishni vaqtincha o'chirish\n"
              "🌐 <b>Til</b> — tilni almashtirish\n\n"
              "Bitta e'lon sizga faqat bir marta yuboriladi.",
        "ru": "ℹ️ <b>Как работает бот</b>\n\n"
              "Бот следит за новыми объявлениями <b>от собственников</b> на OLX и Joymee и сразу присылает "
              "подходящие под ваш фильтр — с фото, ценой и адресом.\n\n"
              "⚙️ <b>Фильтр</b> — сайт, аренда/продажа, тип, ремонт, комнаты, район и цена\n"
              "🆕 <b>За 24 часа</b> — подходящие объявления за сутки\n"
              "📅 <b>За {d} дней</b> — подходящие объявления за {d} дней\n"
              "📢 <b>Фильтр канала</b> — публиковать новые объявления в ваш канал с вашим номером\n"
              "⏸ <b>Пауза</b> — временно отключить рассылку\n"
              "🌐 <b>Язык</b> — сменить язык\n\n"
              "Каждое объявление присылается только один раз."},
    # obuna
    "b_sub": {"uz": "💎 Tariflar", "ru": "💎 Тарифы"},
    "left_days": {"uz": "{d} gacha ({n} kun qoldi)", "ru": "до {d} (осталось {n} дн.)"},
    "left_hours": {"uz": "{d} gacha ({n} soat qoldi)", "ru": "до {d} (осталось {n} ч.)"},
    "sub_expired_short": {"uz": "tugagan", "ru": "закончилась"},
    "st_trial": {"uz": "🎁 Bepul sinov: {u}", "ru": "🎁 Пробный период: {u}"},
    "st_paid": {"uz": "✅ Obuna: {u}", "ru": "✅ Подписка: {u}"},
    "st_admin": {"uz": "👑 Admin — cheklovsiz", "ru": "👑 Админ — без ограничений"},
    "st_expired": {"uz": "⛔️ Obuna muddati tugagan — e'lonlar kelmayapti", "ru": "⛔️ Подписка закончилась — объявления не приходят"},
    "sub_page": {
        "uz": "💎 <b>Tariflar</b>\n\n{status}\n\n<b>Tariflar:</b>\n🚀 <b>Start</b> — 1 oy, <b>{p1} so'm</b>\n"
              "🏆 <b>Pro</b> — 3 oy, <b>{p3} so'm</b> <i>({save} so'm tejaysiz)</i>\n\nTarifni tanlang 👇",
        "ru": "💎 <b>Тарифы</b>\n\n{status}\n\n<b>Тарифы:</b>\n🚀 <b>Start</b> — 1 месяц, <b>{p1} сум</b>\n"
              "🏆 <b>Pro</b> — 3 месяца, <b>{p3} сум</b> <i>(экономия {save} сум)</i>\n\nВыберите тариф 👇"},
    "b_plan1": {"uz": "🚀 Start · 1 oy — {p} so'm", "ru": "🚀 Start · 1 месяц — {p} сум"},
    "b_plan3": {"uz": "🏆 Pro · 3 oy — {p} so'm 🔥", "ru": "🏆 Pro · 3 месяца — {p} сум 🔥"},
    "plan_name1": {"uz": "🚀 Start (1 oy)", "ru": "🚀 Start (1 месяц)"},
    "plan_name3": {"uz": "🏆 Pro (3 oy)", "ru": "🏆 Pro (3 месяца)"},
    "pay_page": {
        "uz": "💳 <b>{plan} — {price} so'm</b>\n\n<b>To'lov qilish:</b>\n"
              "1️⃣ Quyidagi kartaga <b>{price} so'm</b> o'tkazing:\n<code>{card}</code>\n{name}\n"
              "2️⃣ «📸 Chekni yuborish» tugmasini bosib, to'lov chekining rasmini yuboring.\n"
              "3️⃣ Admin tekshirgach, obunangiz darhol yoqiladi (odatda 1 soat ichida).",
        "ru": "💳 <b>{plan} — {price} сум</b>\n\n<b>Как оплатить:</b>\n"
              "1️⃣ Переведите <b>{price} сум</b> на карту:\n<code>{card}</code>\n{name}\n"
              "2️⃣ Нажмите «📸 Отправить чек» и пришлите фото чека.\n"
              "3️⃣ После проверки админом подписка включится сразу (обычно в течение часа)."},
    "b_plans": {"uz": "⬅️ Tariflar", "ru": "⬅️ Тарифы"},
    "no_card": {"uz": "(karta hali kiritilmagan — admin bilan bog'laning)", "ru": "(карта ещё не указана — свяжитесь с админом)"},
    "b_send_check": {"uz": "📸 Chekni yuborish", "ru": "📸 Отправить чек"},
    "ask_check": {"uz": "📸 To'lov chekining rasmini (skrinshot) shu yerga yuboring.",
                  "ru": "📸 Отправьте сюда фото (скриншот) чека об оплате."},
    "check_need_photo": {"uz": "Iltimos, chekni rasm ko'rinishida yuboring.", "ru": "Пожалуйста, отправьте чек в виде фото."},
    "check_sent": {"uz": "✅ Chek adminga yuborildi. Tasdiqlangach, sizga xabar keladi.",
                   "ru": "✅ Чек отправлен админу. После подтверждения вам придёт сообщение."},
    "sub_ok": {"uz": "🎉 To'lov tasdiqlandi! Obuna {u} faol.", "ru": "🎉 Оплата подтверждена! Подписка активна {u}."},
    "sub_no": {"uz": "❌ To'lov tasdiqlanmadi. Savol bo'lsa, admin bilan bog'laning yoki chekni qayta yuboring.",
               "ru": "❌ Оплата не подтверждена. Если есть вопросы, свяжитесь с админом или отправьте чек снова."},
    "sub_warn": {"uz": "⏳ {what} ertaga tugaydi ({d}). E'lonlar kelib turishi uchun obunani uzaytiring: 💎 Tariflar.",
                 "ru": "⏳ {what} заканчивается завтра ({d}). Чтобы объявления продолжали приходить, продлите подписку: 💎 Тарифы."},
    "sub_end": {"uz": "⛔️ {what} tugadi. Yangi e'lonlar va kanalga postlar to'xtatildi.\n\nDavom ettirish uchun obuna bo'ling 👇",
                "ru": "⛔️ {what} закончилась. Новые объявления и посты в канал остановлены.\n\nЧтобы продолжить, оформите подписку 👇"},
    "w_trial": {"uz": "Bepul sinov muddati", "ru": "Пробный период"},
    "w_sub": {"uz": "Obuna", "ru": "Подписка"},
    "need_sub": {"uz": "⛔️ Obuna muddati tugagan. Bu imkoniyatdan foydalanish uchun obuna bo'ling.",
                 "ru": "⛔️ Подписка закончилась. Чтобы пользоваться этой функцией, оформите подписку."},
    "trial_hello": {"uz": "🎁 Sizga <b>{n} kunlik bepul sinov</b> berildi — barcha imkoniyatlar ochiq.",
                    "ru": "🎁 Вам открыт <b>бесплатный пробный период на {n} дня</b> — все функции доступны."},
    # kanal
    "b_channel": {"uz": "📢 Kanal filtri", "ru": "📢 Фильтр канала"},
    "b_publish": {"uz": "📢 Kanalga joylash", "ru": "📢 Опубликовать в канал"},
    "b_publish_to": {"uz": "📢 {title}", "ru": "📢 {title}"},
    "b_published": {"uz": "✅ Kanalga joylandi", "ru": "✅ Опубликовано"},
    "pub_hint": {"uz": "👆 Shu e'lonni kanalingizga joylash:", "ru": "👆 Опубликовать это объявление в канал:"},
    "pub_nochan": {"uz": "Avval kanal ulang: menyudagi «📢 Kanal filtri» tugmasi orqali.",
                   "ru": "Сначала подключите канал: кнопка «📢 Фильтр канала» в меню."},
    "pub_pick": {"uz": "Qaysi kanalga joylaymiz?", "ru": "В какой канал опубликовать?"},
    "pub_done": {"uz": "✅ E'lon «{title}» kanaliga joylandi.", "ru": "✅ Объявление опубликовано в канале «{title}»."},
    "pub_already": {"uz": "ℹ️ Bu e'lon «{title}» kanaliga avval joylangan.", "ru": "ℹ️ Это объявление уже было в канале «{title}»."},
    "pub_gone": {"uz": "⚠️ E'lon ma'lumoti eskirgan (30 kundan oshgan). Uni qayta topib joylang.",
                 "ru": "⚠️ Данные объявления устарели (старше 30 дней)."},
    "pub_fail": {"uz": "❌ «{title}» kanaliga joylab bo'lmadi. Bot kanalda admin va post joylash huquqi borligini tekshiring.",
                 "ru": "❌ Не удалось опубликовать в «{title}». Проверьте, что бот — админ канала с правом публикации."},
    "ch_list": {"uz": "📢 <b>Kanal filtri</b>\n\nBot yangi e'lonlarni sizning Telegram kanalingizga ham joylaydi — "
                      "telefon o'rnida <b>sizning raqamingiz</b> bilan.\n\nKanalni tanlang yoki yangisini qo'shing:",
                "ru": "📢 <b>Фильтр канала</b>\n\nБот будет публиковать новые объявления и в ваш Telegram-канал — "
                      "с <b>вашим номером</b> вместо номера владельца.\n\nВыберите канал или добавьте новый:"},
    "ch_add_btn": {"uz": "➕ Kanal qo'shish", "ru": "➕ Добавить канал"},
    "ch_add_help": {"uz": "➕ <b>Kanal qo'shish</b>\n\n1️⃣ @{bot} ni kanalingizga <b>admin</b> qilib qo'shing va "
                          "<b>«Post messages»</b> ruxsatini bering.\n2️⃣ Shu yerga kanal havolasini yuboring "
                          "(masalan <code>https://t.me/kanalim</code> yoki <code>@kanalim</code>) yoki kanaldan "
                          "istalgan postni <b>forward</b> qiling.",
                    "ru": "➕ <b>Добавить канал</b>\n\n1️⃣ Добавьте @{bot} в ваш канал <b>администратором</b> с правом "
                          "<b>«Публикация сообщений»</b>.\n2️⃣ Отправьте сюда ссылку на канал "
                          "(например <code>https://t.me/mychannel</code> или <code>@mychannel</code>) или "
                          "<b>перешлите</b> любой пост из канала."},
    "ch_bad": {"uz": "Kanal topilmadi. Kanal havolasini yoki @nomini yuboring, yoki kanaldan postni forward qiling.",
               "ru": "Канал не найден. Отправьте ссылку или @имя канала, либо перешлите пост из канала."},
    "ch_no_bot": {"uz": "⚠️ Bot bu kanalda admin emas yoki unda «Post messages» ruxsati yo'q. Ruxsat bering va qaytadan yuboring.",
                  "ru": "⚠️ Бот не администратор канала или у него нет права публикации. Дайте права и отправьте снова."},
    "ch_not_owner": {"uz": "⚠️ Siz bu kanalning admini emassiz. Faqat o'z kanalingizni ulay olasiz.",
                     "ru": "⚠️ Вы не администратор этого канала. Подключить можно только свой канал."},
    "ch_taken": {"uz": "⚠️ Bu kanal boshqa foydalanuvchiga ulangan.", "ru": "⚠️ Этот канал уже подключён другим пользователем."},
    "ch_max": {"uz": "Ko'pi bilan {n} ta kanal ulash mumkin.", "ru": "Можно подключить не более {n} каналов."},
    "ch_added": {"uz": "✅ Kanal ulandi: <b>{title}</b>\n\nEndi filtrni sozlang, telefon raqam qo'shing va yuborishni yoqing.",
                 "ru": "✅ Канал подключён: <b>{title}</b>\n\nНастройте фильтр, добавьте номер и включите публикацию."},
    "ch_title": {"uz": "📢 <b>Kanal filtri:</b> {title}", "ru": "📢 <b>Фильтр канала:</b> {title}"},
    "ch_on": {"uz": "🟢 Kanalga yuborilmoqda", "ru": "🟢 Публикуется в канал"},
    "ch_off": {"uz": "🔴 Kanalga yuborish o'chirilgan", "ru": "🔴 Публикация в канал выключена"},
    "ch_b_on": {"uz": "▶️ Kanalga yuborishni yoqish", "ru": "▶️ Включить публикацию"},
    "ch_b_off": {"uz": "⏸ Kanalga yuborishni to'xtatish", "ru": "⏸ Остановить публикацию"},
    "ch_saved": {"uz": "✅ Kanal filtri saqlandi.", "ru": "✅ Фильтр канала сохранён."},
    "b_phones": {"uz": "📞 Telefonlar ({n}/{m})", "ru": "📞 Телефоны ({n}/{m})"},
    "ph_title": {"uz": "📞 <b>Kanal postlaridagi raqamlar</b> ({n}/{m})\n\n{list}\n\nRaqamni o'chirish uchun ❌ tugmasini bosing.",
                 "ru": "📞 <b>Номера в постах канала</b> ({n}/{m})\n\n{list}\n\nЧтобы удалить номер, нажмите ❌."},
    "ph_none": {"uz": "Hali raqam qo'shilmagan.", "ru": "Номера ещё не добавлены."},
    "ph_add": {"uz": "➕ Raqam qo'shish", "ru": "➕ Добавить номер"},
    "ph_ask": {"uz": "📞 Telefon raqamini yozing, masalan: <code>+998 90 123 45 67</code>",
               "ru": "📞 Напишите номер телефона, например: <code>+998 90 123 45 67</code>"},
    "ph_bad": {"uz": "Raqam noto'g'ri. Masalan: +998 90 123 45 67", "ru": "Неверный номер. Например: +998 90 123 45 67"},
    "ph_full": {"uz": "Ko'pi bilan {m} ta raqam qo'shish mumkin.", "ru": "Можно добавить не более {m} номеров."},
    "ph_added": {"uz": "✅ Raqam qo'shildi: {p}", "ru": "✅ Номер добавлен: {p}"},
    "ph_need": {"uz": "⚠️ Avval kamida bitta telefon raqam qo'shing — u kanal postlarida ko'rsatiladi.",
                "ru": "⚠️ Сначала добавьте хотя бы один номер — он будет в постах канала."},
    "b_ch_del": {"uz": "🗑 Kanalni uzish", "ru": "🗑 Отключить канал"},
    "ch_del_q": {"uz": "«{title}» kanali uzilsinmi? Uning filtri va raqamlari o'chiriladi.",
                 "ru": "Отключить канал «{title}»? Его фильтр и номера будут удалены."},
    "b_yes_del": {"uz": "🗑 Ha, uzish", "ru": "🗑 Да, отключить"},
    "b_no": {"uz": "Yo'q", "ru": "Нет"},
    "ch_deleted": {"uz": "Kanal uzildi.", "ru": "Канал отключён."},
    "ch_lost": {"uz": "⚠️ Bot «{title}» kanaliga post joylay olmadi (bot admin emas yoki ruxsati olingan). "
                      "Kanalga yuborish to'xtatildi. Ruxsatni tiklab, 📢 Kanal filtri'dan qayta yoqing.",
                "ru": "⚠️ Бот не смог опубликовать пост в канале «{title}» (нет прав администратора). "
                      "Публикация остановлена. Верните права и включите её снова в 📢 Фильтр канала."},
    "b_channels": {"uz": "⬅️ Kanallar", "ru": "⬅️ Каналы"},
    "b_header": {"uz": "📝 Post andozasi: {name}", "ru": "📝 Шаблон поста: {name}"},
    "tpl_title": {"uz": "📝 <b>Post andozasi</b> — kanalingizdagi postlar shu ko'rinishda chiqadi.\n"
                        "Har bir foydalanuvchi o'z andozasini tanlaydi, shuning uchun kanallar bir-biriga o'xshamaydi.\n\n"
                        "Tanlangan: <b>{n}. {name}</b> — namuna 👇",
                  "ru": "📝 <b>Шаблон поста</b> — так будут выглядеть посты в вашем канале.\n"
                        "Каждый выбирает свой шаблон, поэтому каналы не похожи друг на друга.\n\n"
                        "Выбран: <b>{n}. {name}</b> — пример 👇"},
    "tpl_names": {"uz": "Klassik|Ixcham|Heshteg|Blok|Jadval|Tavsiya|Ramka",
                  "ru": "Классика|Компакт|Хештеги|Блок|Таблица|Рекомендация|Рамка"},
    "district_l": {"uz": "Tuman", "ru": "Район"},
    "new_short": {"uz": "YANGI!", "ru": "НОВОЕ!"},
    "c_bog": {"uz": "Bog'lanish", "ru": "Связь"},
    "c_aloqa": {"uz": "Aloqa", "ru": "Контакты"},
    "c_view": {"uz": "Ko'rish va kelishish uchun", "ru": "Для просмотра и договорённости"},
    "floor_n": {"uz": "{n}-qavat", "ru": "{n}-й этаж"},
    "hd_title": {"uz": "📝 <b>Post sarlavhasini tanlang</b>\n\nSarlavha har bir postning eng tepasida turadi. "
                       "Tuman, xonalar soni va narx har bir e'londan avtomatik olinadi. Namuna:\n\n{list}",
                 "ru": "📝 <b>Выберите заголовок поста</b>\n\nЗаголовок стоит в самом начале каждого поста. "
                       "Район, комнаты и цена подставляются из каждого объявления автоматически. Пример:\n\n{list}"},
    "hd_saved": {"uz": "✅ Sarlavha tanlandi", "ru": "✅ Заголовок выбран"},
    "verb_rent": {"uz": "ijaraga beriladi", "ru": "сдаётся"},
    "verb_sale": {"uz": "sotiladi", "ru": "продаётся"},
    "rooms_adj": {"uz": "{n} xonali", "ru": "{n}-комнатная"},
    "rooms_short": {"uz": "{n} xona", "ru": "{n} комн."},
    "new_caps": {"uz": "YANGI E'LON!", "ru": "НОВОЕ ОБЪЯВЛЕНИЕ!"},
    "recommend": {"uz": "Tavsiya etamiz", "ru": "Рекомендуем"},
    "contact": {"uz": "Murojaat uchun", "ru": "Для связи"},
    # e'lon xabari
    "new_ad": {"uz": "{src}'da yangi e'lon joylandi!", "ru": "Новое объявление на {src}!"},
    "price": {"uz": "Narxi", "ru": "Цена"},
    "posted": {"uz": "Joylangan", "ru": "Опубликовано"},
    "phone": {"uz": "Telefon", "ru": "Телефон"},
    "see_ad": {"uz": "e'londa ko'ring", "ru": "см. в объявлении"},
    "rooms": {"uz": "Xonalar", "ru": "Комнат"},
    "area": {"uz": "Maydoni", "ru": "Площадь"},
    "floor": {"uz": "Qavat", "ru": "Этаж"},
    "repair": {"uz": "Ta'mir", "ru": "Ремонт"},
    "address": {"uz": "Manzil", "ru": "Адрес"},
    "no_address": {"uz": "ko'rsatilmagan", "ru": "не указан"},
    "street": {"uz": "Ko'cha", "ru": "Улица"},
    "landmark": {"uz": "Mo'ljal", "ru": "Ориентир"},
    "map": {"uz": "Xaritada ko'rish", "ru": "Посмотреть на карте"},
    "open": {"uz": "E'lonni ochish", "ru": "Открыть объявление"},
    "negotiable": {"uz": "kelishiladi", "ru": "договорная"},
    "sum": {"uz": "so'm", "ru": "сум"},
    "ago_now": {"uz": "hozirgina", "ru": "только что"},
    "ago_min": {"uz": "{n} daqiqa oldin", "ru": "{n} мин. назад"},
    "ago_hour": {"uz": "{n} soat oldin", "ru": "{n} ч. назад"},
    "ago_day": {"uz": "{n} kun oldin", "ru": "{n} дн. назад"},
    # buyruqlar menyusi
    "cmd_filtr": {"uz": "Filtrlarni sozlash", "ru": "Настроить фильтры"},
    "cmd_oxirgi": {"uz": "Oxirgi 24 soatlik e'lonlar", "ru": "Объявления за 24 часа"},
    "cmd_on_kun": {"uz": "Oxirgi {d} kunlik e'lonlar", "ru": "Объявления за {d} дней"},
    "cmd_til": {"uz": "Tilni o'zgartirish", "ru": "Сменить язык"},
    "cmd_start": {"uz": "Botni boshlash", "ru": "Запустить бота"},
    "cmd_menu": {"uz": "Asosiy menyu", "ru": "Главное меню"},
}


def t(lang, key, **kw):
    s = T[key].get(lang or "uz") or T[key]["uz"]
    return s.format(**kw) if kw else s


# ======================= FILTR VARIANTLARI =======================

DEALS = {"rent": {"uz": "Ijara", "ru": "Аренда"}, "sale": {"uz": "Sotuv", "ru": "Продажа"}}
PTYPES = {"apt": {"uz": "Kvartira", "ru": "Квартира"},
          "house": {"uz": "Hovli/dacha", "ru": "Дом/дача"},
          "kom": {"uz": "Tijorat binolari", "ru": "Коммерческая"},
          "land": {"uz": "Yer", "ru": "Земля"}}
SOURCES = {"olx": {"uz": "OLX", "ru": "OLX"}, "joymee": {"uz": "Joymee", "ru": "Joymee"}}
ROOMS = {"1": {"uz": "1", "ru": "1"}, "2": {"uz": "2", "ru": "2"},
         "3": {"uz": "3", "ru": "3"}, "4": {"uz": "4+", "ru": "4+"}}
REPAIRS = {
    "evro": {"uz": "Evroremont", "ru": "Евроремонт"},
    "dizn": {"uz": "Dizaynerlik", "ru": "Дизайнерский"},
    "orta": {"uz": "O'rtacha", "ru": "Средний"},
    "talab": {"uz": "Ta'mir talab", "ru": "Требует ремонта"},
    "qora": {"uz": "Qora suvoq / korobka", "ru": "Черновая / коробка"},
}
REPAIR_WORDS = {
    "evro": ["евроремонт", "евро ремонт", "evroremont", "evro remont", "yevroremont"],
    "dizn": ["авторск", "дизайнер", "dizayner", "dizaynerlik"],
    "orta": ["средний", "o'rtacha", "ortacha", "kosmetik", "yaxshi holatda"],
    "talab": ["требует ремонта", "ta'mir talab", "tamir talab"],
    "qora": ["черновая", "предчистов", "коробка", "korobka", "qora suvoq"],
}
DISTRICTS = {
    "bektemir": {"uz": "Bektemir", "ru": "Бектемир"},
    "chilonzor": {"uz": "Chilonzor", "ru": "Чиланзар"},
    "mirobod": {"uz": "Mirobod", "ru": "Мирабад"},
    "mirzo": {"uz": "Mirzo Ulug'bek", "ru": "Мирзо-Улугбек"},
    "olmazor": {"uz": "Olmazor", "ru": "Алмазар"},
    "sergeli": {"uz": "Sergeli", "ru": "Сергели"},
    "shayx": {"uz": "Shayxontohur", "ru": "Шайхантахур"},
    "uchtepa": {"uz": "Uchtepa", "ru": "Учтепа"},
    "yakka": {"uz": "Yakkasaroy", "ru": "Яккасарай"},
    "yashnobod": {"uz": "Yashnobod", "ru": "Яшнабад"},
    "yunusobod": {"uz": "Yunusobod", "ru": "Юнусабад"},
    "yangihayot": {"uz": "Yangihayot", "ru": "Янгихаёт"},
}
DISTRICT_WORDS = {
    "bektemir": ["бектемир", "bektemir"],
    "chilonzor": ["чиланзар", "chilonzor"],
    "mirobod": ["мирабад", "mirobod"],
    "mirzo": ["улугбек", "ulug'bek", "ulugbek", "ulug‘bek", "ulug’bek"],
    "olmazor": ["алмазар", "olmazor"],
    "sergeli": ["сергели", "sergeli"],
    "shayx": ["шайхантахур", "shayxontohur", "shayxontoxur"],
    "uchtepa": ["учтепин", "uchtepa"],
    "yakka": ["яккасарай", "yakkasaroy"],
    "yashnobod": ["яшнабад", "yashnobod"],
    "yunusobod": ["юнусабад", "yunusobod"],
    "yangihayot": ["янгихаёт", "yangihayot"],
}
# Ta'mirni e'lon matnidan topish: bo'sh joy / chiziqcha / turli yozilishlarni hisobga oladi
_SEP = r"[\s\-_.]*"
_TAMIR = r"(?:remont|ремонт|ta['ʻ’`]?mir|та['ъ’]?мир|tamir)"
REPAIR_RE = {
    "evro": re.compile(rf"(?:y?evro|euro|евро|йевро|еvro){_SEP}{_TAMIR}|evroremont|евроремонт", re.I),
    "dizn": re.compile(rf"dizayner\w*|дизайнерск\w*|авторск\w*|avtorsk\w*|"
                       rf"(?:dizayn|dizain|design|дизайн)\w*{_SEP}(?:{_TAMIR}|проект|loyiha)", re.I),
    "orta": re.compile(rf"средн\w*{_SEP}{_TAMIR}|o['ʻ’`]?rtacha{_SEP}{_TAMIR}|kosmetik|косметич|yaxshi holatda|хорош\w* состоян", re.I),
    "talab": re.compile(rf"(?:требует|нужен|без){_SEP}{_TAMIR}|{_TAMIR}{_SEP}(?:talab|kerak|qilinmagan)|"
                        rf"{_TAMIR}siz|ta['ʻ’`]?mirtalab", re.I),
    "qora": re.compile(r"черн\w*|предчист\w*|коробк\w*|korobka|qora\s*suvoq|qora\s*karobka|karobka|"
                       r"белая\s*коробка|oq\s*suvoq", re.I),
}


def repair_matches(ad, keys):
    """Ta'mir filtri: avval e'londagi 'Ремонт' maydoni, bo'lmasa sarlavha va tavsif."""
    label = (repair_label(ad) or "").lower()
    text = re.sub(r"<[^>]+>", " ", ad_text(ad))
    for k in keys:
        if any(w in label for w in REPAIR_WORDS[k]) or REPAIR_RE[k].search(label):
            return True
        if any(w in text for w in REPAIR_WORDS[k]) or REPAIR_RE[k].search(text):
            return True
    return False


TABLES = {"sources": SOURCES, "deals": DEALS, "ptypes": PTYPES, "repairs": REPAIRS,
          "rooms": ROOMS, "districts": DISTRICTS}

OLX_PATHS = {
    ("rent", "apt"): "nedvizhimost/kvartiry/arenda-dolgosrochnaya",
    ("sale", "apt"): "nedvizhimost/kvartiry/prodazha",
    ("rent", "house"): "nedvizhimost/doma/arenda-dolgosrochnaya",
    ("sale", "house"): "nedvizhimost/doma/prodazha",
    ("rent", "kom"): "nedvizhimost/kommercheskie-pomeshcheniya/arenda",
    ("sale", "kom"): "nedvizhimost/kommercheskie-pomeshcheniya/prodazha",
    ("rent", "land"): "nedvizhimost/zemlja/arenda",
    ("sale", "land"): "nedvizhimost/zemlja/prodazha",
}

AGENT_WORDS = ["риелтор", "риэлтор", "агентств", "комисси", "rieltor", "agentlik",
               "komissiya", "услуги агента"]
OWNER_WORDS = ["vositachisiz", "без посредников", "от хозяина", "от собственника", "uy egasidan"]
NAME_AGENT_WORDS = ["rieltor", "riyeltor", "риелтор", "риэлтор", "realtor", "agent", "агент",
                    "makler", "маклер", "estate", "недвижим", "ko'chmas", "kochmas", "uy-joy", "uyjoy"]

DEFAULT_SETTINGS = {"sources": ["olx", "joymee"], "deals": ["rent"], "ptypes": ["apt"],
                    "repairs": [], "rooms": [], "districts": [],
                    "price": {"rent": [None, None], "sale": [None, None]}, "paused": False}


# ======================= BAZA =======================

class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _DB:
    """Bir nechta oqimdan xavfsiz foydalanish uchun qulf bilan o'ralgan sqlite."""
    def __init__(self, path):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.l = threading.RLock()

    def execute(self, sql, args=()):
        with self.l:
            return _Rows(self.c.execute(sql, args).fetchall())

    def commit(self):
        with self.l:
            self.c.commit()


db = _DB("seen.db")


def init_db():
    db.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, ts INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS sellers (uid TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS primed (deal TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, days INTEGER, amount INTEGER,
        plan TEXT, ts INTEGER, source TEXT)""")
    db.execute("CREATE TABLE IF NOT EXISTS activity (chat_id TEXT PRIMARY KEY, last_seen INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS menus (chat_id TEXT PRIMARY KEY, msg_id INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS ad_cache (ad_id TEXT PRIMARY KEY, deal TEXT, data TEXT, ts INTEGER)")
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        chat_id TEXT PRIMARY KEY, lang TEXT, phone TEXT, first_name TEXT, username TEXT,
        settings TEXT, created INTEGER, active INTEGER DEFAULT 1)""")
    # eski (bir foydalanuvchili) "sent" jadvalini yangisiga ko'chiramiz
    cols = [r[1] for r in db.execute("PRAGMA table_info(sent)").fetchall()]
    if cols and "chat_id" not in cols:
        db.execute("ALTER TABLE sent RENAME TO sent_old")
    db.execute("""CREATE TABLE IF NOT EXISTS sent (
        chat_id TEXT, ad_id TEXT, ts INTEGER, PRIMARY KEY (chat_id, ad_id))""")
    db.commit()
    migrate_single_user()


def migrate_single_user():
    """Eski versiyadagi settings.json va yuborilganlarni admin hisobiga o'tkazamiz."""
    if not ADMIN_ID or db.execute("SELECT 1 FROM users WHERE chat_id=?", (ADMIN_ID,)).fetchone():
        return
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        with open("settings.json", encoding="utf-8") as f:
            settings.update(json.load(f))
    except Exception:
        pass
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,1)",
               (ADMIN_ID, "uz", "", "Admin", "", json.dumps(settings), int(time.time())))
    if db.execute("SELECT name FROM sqlite_master WHERE name='sent_old'").fetchone():
        for (ad_id, ts) in db.execute("SELECT id, ts FROM sent_old").fetchall():
            db.execute("INSERT OR IGNORE INTO sent VALUES (?,?,?)", (ADMIN_ID, ad_id, ts))
    db.commit()
    log.info("Eski sozlamalar admin (%s) hisobiga ko'chirildi", ADMIN_ID)


def cfg_get(key, default=""):
    r = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return r[0] if r and r[0] is not None else default


def cfg_set(key, value):
    db.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, value))
    db.commit()


def pay_card():
    return cfg_get("pay_card", PAY_CARD)


def pay_name():
    return cfg_get("pay_name", PAY_NAME)


def fmt_card(raw):
    d = re.sub(r"\D", "", raw)
    return " ".join(d[i:i + 4] for i in range(0, len(d), 4))


def get_user(chat_id):
    r = db.execute("SELECT chat_id, lang, phone, first_name, username, settings, active, created "
                   "FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
    if not r:
        return None
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        s.update(json.loads(r[5] or "{}"))
    except Exception:
        pass
    return {"chat_id": r[0], "lang": r[1], "phone": r[2], "first_name": r[3],
            "username": r[4], "s": s, "active": r[6], "created": r[7] or int(time.time())}


def ensure_user(chat_id, frm):
    if not get_user(chat_id):
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,1)",
                   (str(chat_id), None, None, frm.get("first_name", ""), frm.get("username", ""),
                    json.dumps(DEFAULT_SETTINGS), int(time.time())))
        db.commit()
    return get_user(chat_id)


def set_user(chat_id, **fields):
    for k, v in fields.items():
        if k == "s":
            k, v = "settings", json.dumps(v, ensure_ascii=False)
        db.execute(f"UPDATE users SET {k}=? WHERE chat_id=?", (v, str(chat_id)))
    db.commit()


def registered(u):
    return bool(u and u["lang"] and u["phone"] is not None)


MAX_CHANNELS = int(os.getenv("MAX_CHANNELS", "3"))
MAX_PHONES = 5
BOT_ID = (BOT_TOKEN or "0:").split(":")[0]
BOT_USERNAME = os.getenv("BOT_USERNAME", "UySavat_bot")


def is_channel(u):
    return str(u["chat_id"]).startswith("-100")


def channels_of(owner):
    out = []
    for (cid,) in db.execute("SELECT chat_id FROM users WHERE chat_id LIKE '-100%'").fetchall():
        c = get_user(cid)
        if c and str(c["s"].get("owner")) == str(owner):
            out.append(c)
    return out


def create_channel(cid, owner, title, lang, phones):
    st = json.loads(json.dumps(DEFAULT_SETTINGS))
    st.update(paused=True, owner=str(owner), title=title, phones=phones)
    db.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?,?,1)",
               (str(cid), lang, "", title, "", json.dumps(st, ensure_ascii=False), int(time.time())))
    db.commit()


def ensure_channel():
    """.env dagi eski CHANNEL_ID ni admin kanaliga aylantiramiz (bir marta)."""
    if not CHANNEL_ID or not ADMIN_ID:
        return
    cid = CHANNEL_ID
    if cid.startswith("@"):
        r = tg("getChat", chat_id=cid)
        if r is None or not r.ok:
            return
        cid = str(r.json()["result"]["id"])
    c = get_user(cid)
    phones = [fmt_phone(CHANNEL_PHONE)] if CHANNEL_PHONE else []
    title = "Kanal"
    r = tg("getChat", chat_id=cid)
    if r is not None and r.ok:
        title = r.json()["result"].get("title") or title
    if not c:
        create_channel(cid, ADMIN_ID, title, "uz", phones)
        log.info("Kanal %s admin hisobiga qo'shildi", cid)
    elif str(c["s"].get("owner")) != ADMIN_ID:   # .env dagi kanal doim admin'niki
        c["s"].update(owner=ADMIN_ID, phones=c["s"].get("phones") or phones, title=c["s"].get("title") or title)
        set_user(cid, s=c["s"])
        log.info("Kanal %s egasi admin (%s) qilib belgilandi", cid, ADMIN_ID)


# ---- obuna ----

def access_until(u):
    """Foydalanuvchi qachongacha botdan foydalana oladi (sinov yoki to'langan obuna)."""
    if not u:
        return 0
    if str(u["chat_id"]).startswith("-100"):          # kanal — egasining obunasi bo'yicha
        return access_until(get_user(u["s"].get("owner")))
    if str(u["chat_id"]) == ADMIN_ID:
        return 4102444800                               # admin uchun cheksiz (2100-yil)
    created = u.get("created")
    trial = int(created if created is not None else time.time()) + TRIAL_DAYS * 86400
    return max(trial, int(u["s"].get("sub_until") or 0))


def has_access(u):
    return access_until(u) > time.time()


def on_trial(u):
    return not u["s"].get("sub_until") and str(u["chat_id"]) != ADMIN_ID


def until_text(ts, L):
    left = ts - time.time()
    d = datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")
    if left <= 0:
        return t(L, "sub_expired_short")
    if left < 86400:
        return t(L, "left_hours", d=d, n=max(1, -int(-left // 3600)))
    return t(L, "left_days", d=d, n=-int(-left // 86400))   # yuqoriga yaxlitlash: 2.9 kun -> 3 kun


def active_users():
    out = []
    for (cid,) in db.execute("SELECT chat_id FROM users WHERE active=1 AND phone IS NOT NULL "
                             "AND lang IS NOT NULL").fetchall():
        u = get_user(cid)
        if u and not u["s"].get("paused") and has_access(u):
            out.append(u)
    return out


def was_sent(chat_id, ad_id):
    return db.execute("SELECT 1 FROM sent WHERE chat_id=? AND ad_id=?",
                      (str(chat_id), str(ad_id))).fetchone() is not None


def mark_sent(chat_id, ad_id):
    db.execute("INSERT OR IGNORE INTO sent VALUES (?,?,?)", (str(chat_id), str(ad_id), int(time.time())))
    db.commit()


def is_seen(ad_id):
    return db.execute("SELECT 1 FROM seen WHERE id=?", (str(ad_id),)).fetchone() is not None


def mark_seen(ad_id):
    db.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", (str(ad_id), int(time.time())))
    db.commit()


# ======================= TELEGRAM =======================

def esc(x):
    return html.escape(str(x).strip(), quote=False)


_tls = threading.local()


def tg_session():
    """Har bir oqim uchun bitta doimiy ulanish: har so'rovda qayta ulanish (TLS) vaqti tejaladi."""
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8))
        _tls.s = s
    return s


def tg(method, **data):
    """Telegram API chaqiruvi. Tarmoq uzilsa bir marta qayta urinadi, 429 (juda tez) bo'lsa kutib turadi."""
    r = None
    for attempt in range(3):
        try:
            r = tg_session().post(f"{TG}/{method}", json=data, timeout=60 if method == "sendMediaGroup" else 20)
        except Exception as e:
            if attempt == 0 and method != "answerCallbackQuery":
                time.sleep(2)
                continue
            log.warning("Telegram ulanish xato (%s): %s", method, e)
            return None
        if r.status_code == 429 and attempt < 2:
            try:
                wait = int(r.json().get("parameters", {}).get("retry_after", 3))
            except Exception:
                wait = 3
            log.info("Telegram cheklovi (%s): %s s kutamiz", method, wait)
            time.sleep(min(wait, 60) + 1)
            continue
        break
    try:
        if not r.ok:
            log.warning("Telegram xato (%s): %s", method, r.text[:200])
            if r.status_code == 403 and data.get("chat_id") and not str(data["chat_id"]).startswith("-100"):
                set_user(data["chat_id"], active=0)   # foydalanuvchi botni bloklagan
        return r
    except Exception as e:
        log.warning("Telegram xato: %s", e)
        return r


def btn(text, data):
    return {"text": text, "callback_data": data}


def mark(on):
    return "✅ " if on else "▫️ "


def fmt_num(n):
    return f"{n:,.0f}".replace(",", " ")


def price_str(rng, lang):
    lo, hi = rng
    if lo is None and hi is None:
        return t(lang, "any_price")
    if lo is None:
        return t(lang, "to", n=fmt_num(hi))
    if hi is None:
        return t(lang, "from", n=fmt_num(lo))
    return f"${fmt_num(lo)} – ${fmt_num(hi)}"


def names(selected, table, lang):
    if not selected:
        return t(lang, "all")
    return ", ".join(table[k][lang] for k in selected if k in table)


def short(selected, table, L, maxn=2):
    """Tugma uchun qisqa qiymat: 'OLX, Joymee' yoki '3 ta'."""
    if not selected:
        return t(L, "all")
    if len(selected) > maxn:
        return t(L, "n_items", n=len(selected))
    return ", ".join(table[k][L] for k in selected if k in table)


def price_lines(s, L):
    out = []
    for deal in ("rent", "sale"):
        if deal in s["deals"]:
            label = DEALS[deal][L] if len(s["deals"]) > 1 else ""
            out.append((label + ": " if label else "") + price_str(s["price"][deal], L))
    return out


def summary(u):
    s, L = u["s"], u["lang"]
    rows = [
        f"🌐 <b>{t(L, 'l_sources')}:</b> {names(s['sources'], SOURCES, L)}",
        f"🏷 <b>{t(L, 'l_deal')}:</b> {names(s['deals'], DEALS, L)}",
        f"🏠 <b>{t(L, 'l_ptype')}:</b> {names(s['ptypes'], PTYPES, L)}",
        f"🛠 <b>{t(L, 'l_repairs')}:</b> {names(s['repairs'], REPAIRS, L)}",
        f"🚪 <b>{t(L, 'l_rooms')}:</b> {names(s['rooms'], ROOMS, L)}",
        f"📍 <b>{t(L, 'l_districts')}:</b> {names(s['districts'], DISTRICTS, L)}",
        f"💰 <b>{t(L, 'l_price')}:</b> {'; '.join(price_lines(s, L))}",
    ]
    return "\n".join([
        t(L, "settings"), "",
        "<blockquote>" + "\n".join(rows) + "</blockquote>",
        t(L, "hint"),
    ])


def fbtn(text, data, active):
    """Filtr tugmasi: o'zgartirilgan bo'lsa ko'k rangda."""
    b = btn(text, data)
    if active:
        b["style"] = "primary"
    return b


def main_kb(u):
    """Filtr oynasi: tugmalarda joriy qiymat ko'rinadi."""
    L, s = u["lang"], u["s"]
    d = DEFAULT_SETTINGS
    price_set = any(v is not None for deal in s["deals"] for v in s["price"][deal])
    if len(s["deals"]) == 1:
        price_short = price_str(s["price"][s["deals"][0]], L)
    else:
        price_short = t(L, "l_price") + (" ✓" if price_set else ": " + t(L, "any_price"))
    return {"inline_keyboard": [
        [fbtn(f"🌐 {short(s['sources'], SOURCES, L)}",
              "m:sources", sorted(s["sources"]) != sorted(d["sources"])),
         fbtn(f"🏷 {short(s['deals'], DEALS, L)}", "m:deals", s["deals"] != d["deals"])],
        [fbtn(f"🏠 {t(L, 'l_ptype')}: {short(s['ptypes'], PTYPES, L, 1)}", "m:ptypes", s["ptypes"] != d["ptypes"]),
         fbtn(f"🛠 {t(L, 'l_repairs')}: {short(s['repairs'], REPAIRS, L, 1)}", "m:repairs", bool(s["repairs"]))],
        [fbtn(f"🚪 {t(L, 'l_rooms')}: {short(s['rooms'], ROOMS, L, 3)}", "m:rooms", bool(s["rooms"])),
         fbtn(f"📍 {t(L, 'l_districts')}: {short(s['districts'], DISTRICTS, L, 1)}", "m:districts", bool(s["districts"]))],
        [fbtn(f"💰 {price_short}", "m:price", price_set)],
        [{**btn(t(L, "b_reset"), "reset"), "style": "danger"},
         {**btn(t(L, "b_done"), "done"), "style": "success"}],
    ]}


def home_kb(u):
    """Asosiy menyu — chat ichidagi tugmalar."""
    L = u["lang"]
    return {"inline_keyboard": [
        [btn(t(L, "kb_filter"), "m:main"), btn(t(L, "b_channel"), "chpage")],
        [btn(t(L, "kb_lang"), "lang"), btn(t(L, "kb_help"), "help")],
        [{**btn(t(L, "b_sub"), "sub"), "style": "primary" if has_access(u) else "danger"}],   # muddati tugasa qizil
        [btn(t(L, "kb_last1"), "last:1"), btn(t(L, "kb_lastN", d=LATEST_DAYS), f"last:{LATEST_DAYS}")],
        [{**btn(t(L, "kb_resume"), "pause"), "style": "success"} if u["s"]["paused"]   # yashil
         else {**btn(t(L, "kb_pause"), "pause"), "style": "danger"}],                # qizil
    ]}


def kb_action(text):
    """Eski pastki tugmalar matnini (ikkala tilda) amalga aylantiradi."""
    for L in ("uz", "ru"):
        table = {t(L, "kb_filter"): "filter", t(L, "kb_last1"): "last1",
                 t(L, "kb_lastN", d=LATEST_DAYS): "lastN", t(L, "kb_pause"): "pause",
                 t(L, "kb_resume"): "pause", t(L, "kb_lang"): "lang", t(L, "kb_help"): "help"}
        if text in table:
            return table[text]
    return None


def sub_status(u):
    L = u["lang"]
    if str(u["chat_id"]) == ADMIN_ID:
        return t(L, "st_admin")
    if not has_access(u):
        return t(L, "st_expired")
    u_txt = until_text(access_until(u), L)
    return t(L, "st_trial", u=u_txt) if on_trial(u) else t(L, "st_paid", u=u_txt)


def home_text(u, note_key=None):
    L = u["lang"]
    text = t(L, "home") + "\n\n" + sub_status(u)
    if note_key:
        note = t(L, note_key, d=LATEST_DAYS) if note_key == "help" else t(L, note_key)
        text = note + "\n\n" + text
    return text


def send_main(u, note_key=None, msg_id=None):
    """Asosiy menyuni yuboradi (yoki msg_id bo'lsa, o'sha xabarni almashtiradi)."""
    if not u["s"].get("kb_removed"):     # eski pastki klaviaturani bir marta olib tashlaymiz
        with ulock:
            fresh = get_user(u["chat_id"])
            fresh["s"]["kb_removed"] = True
            set_user(u["chat_id"], s=fresh["s"])
        u["s"]["kb_removed"] = True
        tg("sendMessage", chat_id=u["chat_id"], text="✅", reply_markup={"remove_keyboard": True})
    cid = str(u["chat_id"])
    if msg_id:
        tg("editMessageText", chat_id=cid, message_id=msg_id, parse_mode="HTML",
           text=home_text(u, note_key), reply_markup=home_kb(u))
        new_id = msg_id
    else:
        # chatda bitta menyu tursin: eskisini o'chirib, yangisini eng pastga qo'yamiz
        old = db.execute("SELECT msg_id FROM menus WHERE chat_id=?", (cid,)).fetchone()
        if old:
            tg("deleteMessage", chat_id=cid, message_id=old[0])
        r = tg("sendMessage", chat_id=cid, parse_mode="HTML",
               text=home_text(u, note_key), reply_markup=home_kb(u))
        try:
            new_id = r.json()["result"]["message_id"]
        except Exception:
            return
    db.execute("INSERT OR REPLACE INTO menus VALUES (?,?)", (cid, new_id))
    db.commit()


_menu_due = set()
_menu_due_lock = threading.Lock()


def menu_after_ads(chat_ids=None):
    """E'lonlar yuborilgandan keyin menyuni chat oxiriga qaytaradi."""
    with _menu_due_lock:
        due = set(chat_ids) if chat_ids is not None else set(_menu_due)
        _menu_due.difference_update(due)
    for cid in due:
        if cid in awaiting:          # foydalanuvchi hozir narx yozayotgan bo'lsa, xalaqit bermaymiz
            continue
        u = get_user(cid)
        if u and registered(u):
            send_main(u)


def toggle_pause(chat_id, msg_id=None):
    with ulock:
        u = get_user(chat_id)
        u["s"]["paused"] = not u["s"]["paused"]
        set_user(chat_id, s=u["s"])
    send_main(u, "paused_msg" if u["s"]["paused"] else "resumed_msg", msg_id)
    return u


def list_kb(u, field, per_row=2):
    L, rows, row = u["lang"], [], []
    for k, v in TABLES[field].items():
        on = k in u["s"][field]
        row.append(fbtn(mark(on) + v[L], f"t:{field}:{k}", on))   # tanlangani ko'k
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn(t(L, "b_all"), f"clr:{field}"), btn(t(L, "b_back"), "m:main")])
    return {"inline_keyboard": rows}


def deals_kb(u):
    L, s = u["lang"], u["s"]
    rows = [[fbtn(mark(k in s["deals"]) + v[L], f"t:deals:{k}", k in s["deals"]) for k, v in DEALS.items()],
            [btn(t(L, "b_ptype_hdr"), "noop")]]
    items = [fbtn(mark(k in s["ptypes"]) + v[L], f"t:ptypes:{k}", k in s["ptypes"]) for k, v in PTYPES.items()]
    rows += [items[i:i + 2] for i in range(0, len(items), 2)]
    rows.append([btn(t(L, "b_back"), "m:main")])
    return {"inline_keyboard": rows}


def price_kb(u):
    L, s = u["lang"], u["s"]
    return {"inline_keyboard": [
        [btn(f"{t(L, 'p_rent')}: {price_str(s['price']['rent'], L)}", "p:rent")],
        [btn(f"{t(L, 'p_sale')}: {price_str(s['price']['sale'], L)}", "p:sale")],
        [btn(t(L, "b_back"), "m:main")],
    ]}


def prefix_kb(kb, p):
    if p:
        for row in kb["inline_keyboard"]:
            for b in row:
                if "callback_data" in b and b["callback_data"] != "noop":
                    b["callback_data"] = p + b["callback_data"]
    return kb


def channel_extra_rows(u):
    L, s = u["lang"], u["s"]
    rows = [[btn(t(L, "b_header", name=tpl_name(L, int(s.get("header") or 1))), "header")],
            [btn(t(L, "b_phones", n=len(s.get("phones") or []), m=MAX_PHONES), "phones")]]
    if s["paused"]:
        rows.append([{**btn(t(L, "ch_b_on"), "pause"), "style": "success"}])
    else:
        rows.append([{**btn(t(L, "ch_b_off"), "pause"), "style": "danger"}])
    rows.append([btn(t(L, "b_ch_del"), "chdel")])
    return rows


def show_menu(u, msg_id, menu):
    L = u["lang"]
    ui_chat = u.get("ui_chat", u["chat_id"])
    if menu == "main":
        text, kb = summary(u), main_kb(u)
        if u.get("ui_chat"):   # kanal filtri
            text = text.replace(t(L, "settings"), t(L, "ch_title", title=esc(u["s"].get("title", ""))), 1)
            text += "\n\n" + (t(L, "ch_off") if u["s"]["paused"] else t(L, "ch_on"))
            kb["inline_keyboard"] = kb["inline_keyboard"][:-1] + channel_extra_rows(u) + kb["inline_keyboard"][-1:]
    elif menu == "price":
        text, kb = t(L, "t_price"), price_kb(u)
    else:
        text, kb = t(L, f"t_{menu}"), list_kb(u, menu, 4 if menu == "rooms" else 2)
    kb = prefix_kb(kb, u.get("prefix", ""))
    if msg_id:
        tg("editMessageText", chat_id=ui_chat, message_id=msg_id, text=text,
           parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=ui_chat, text=text, parse_mode="HTML", reply_markup=kb)


def channel_user(cid, owner_chat):
    """Kanal sozlamalari egasining chatida, egasining tilida tahrirlanadi."""
    u = get_user(cid)
    if u:
        owner = get_user(owner_chat)
        u["ui_chat"], u["prefix"] = str(owner_chat), f"C{cid}|"
        if owner and owner["lang"]:
            u["lang"] = owner["lang"]
    return u


def channels_page(u, msg_id=None):
    L = u["lang"]
    rows = [[btn(f"📢 {c['s'].get('title', '')} {'🔴' if c['s']['paused'] else '🟢'}", f"C{c['chat_id']}|m:main")]
            for c in channels_of(u["chat_id"])]
    rows.append([{**btn(t(L, "ch_add_btn"), "chadd"), "style": "primary"}])
    rows.append([btn(t(L, "b_home"), "home")])
    kb = {"inline_keyboard": rows}
    if msg_id:
        tg("editMessageText", chat_id=u["chat_id"], message_id=msg_id, text=t(L, "ch_list"),
           parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=u["chat_id"], text=t(L, "ch_list"), parse_mode="HTML", reply_markup=kb)


def phones_page(cu, msg_id=None):
    L, phones = cu["lang"], cu["s"].get("phones") or []
    text = t(L, "ph_title", n=len(phones), m=MAX_PHONES,
             list="\n".join(f"{i + 1}. {p}" for i, p in enumerate(phones)) or t(L, "ph_none"))
    rows = [[btn(f"❌ {p}", f"phdel:{i}")] for i, p in enumerate(phones)]
    if len(phones) < MAX_PHONES:
        rows.append([{**btn(t(L, "ph_add"), "phadd"), "style": "primary"}])
    rows.append([btn(t(L, "b_back"), "m:main")])
    kb = prefix_kb({"inline_keyboard": rows}, cu["prefix"])
    if msg_id:
        tg("editMessageText", chat_id=cu["ui_chat"], message_id=msg_id, text=text, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=cu["ui_chat"], text=text, parse_mode="HTML", reply_markup=kb)


SAMPLE_AD = {
    "id": "sample", "ptype": "apt", "title": "2 xonali kvartira, Chilonzor 9-kvartal",
    "description": "Yangi ta'mirlangan, mebel va texnika bor. Metroga 5 daqiqa.<br />\nMo'ljal: Novza metro",
    "params": [{"key": "price", "value": {"value": 450, "currency": "UYE"}},
               {"key": "number_of_rooms", "value": {"label": "2"}}, {"key": "total_area", "value": {"label": "56"}},
               {"key": "floor", "value": {"label": "3"}}, {"key": "total_floors", "value": {"label": "9"}},
               {"key": "repairs", "name": "Ремонт", "value": {"label": "Евроремонт"}}],
    "location": {"city": {"name": "Ташкент"}, "district": {"name": "Чиланзарский район"}},
    "map": {"lat": 41.28, "lon": 69.2},
}


def header_page(cu, msg_id=None):
    L, cur = cu["lang"], int(cu["s"].get("header") or 1)
    sample = render_channel(json.loads(json.dumps(SAMPLE_AD)), "rent", L, cu["s"].get("phones") or ["+998 90 123 45 67"], cur)
    text = t(L, "tpl_title", n=cur, name=tpl_name(L, cur)) + "\n\n" + sample
    nums = [fbtn(f"{'✅ ' if i == cur else ''}{i}. {tpl_name(L, i)}", f"hd:{i}", i == cur) for i in range(1, TPL_COUNT + 1)]
    rows = [nums[i:i + 2] for i in range(0, len(nums), 2)]
    kb = prefix_kb({"inline_keyboard": rows + [[btn(t(L, "b_back"), "m:main")]]}, cu["prefix"])
    if msg_id:
        tg("editMessageText", chat_id=cu["ui_chat"], message_id=msg_id, text=text, parse_mode="HTML",
           reply_markup=kb, disable_web_page_preview=True)
    else:
        tg("sendMessage", chat_id=cu["ui_chat"], text=text, parse_mode="HTML", reply_markup=kb,
           disable_web_page_preview=True)


def resolve_channel(msg):
    """Forward qilingan post yoki matndagi havola/@nom/-100 id bo'yicha kanalni topadi."""
    origin = msg.get("forward_origin") or {}
    ch = origin.get("chat") or msg.get("forward_from_chat")
    if ch and ch.get("type") == "channel":
        return str(ch["id"]), ch.get("title") or ""
    text = (msg.get("text") or "").strip()
    m = re.search(r"(?:t\.me/|@)([A-Za-z0-9_]{4,})", text) or re.fullmatch(r"(-100\d+)", text)
    if not m:
        return None, None
    ref = m.group(1)
    r = tg("getChat", chat_id=ref if ref.startswith("-100") else "@" + ref)
    if r is None or not r.ok:
        return None, None
    res = r.json()["result"]
    if res.get("type") != "channel":
        return None, None
    return str(res["id"]), res.get("title") or ""


def member_status(cid, user_id):
    r = tg("getChatMember", chat_id=cid, user_id=int(user_id))
    if r is None or not r.ok:
        return None
    return r.json()["result"]


def add_channel(u, msg):
    L, owner = u["lang"], u["chat_id"]
    cid, title = resolve_channel(msg)
    if not cid:
        tg("sendMessage", chat_id=owner, text=t(L, "ch_bad"))
        return False
    me = member_status(cid, BOT_ID)
    if not me or me.get("status") != "administrator" or not me.get("can_post_messages"):
        tg("sendMessage", chat_id=owner, text=t(L, "ch_no_bot"))
        return False
    him = member_status(cid, (msg.get("from") or {}).get("id", owner))
    if not him or him.get("status") not in ("creator", "administrator"):
        tg("sendMessage", chat_id=owner, text=t(L, "ch_not_owner"))
        return True
    existing = get_user(cid)
    if existing and str(existing["s"].get("owner")) not in ("", "None", str(owner)):
        tg("sendMessage", chat_id=owner, text=t(L, "ch_taken"))
        return True
    if not existing:
        if len(channels_of(owner)) >= MAX_CHANNELS:
            tg("sendMessage", chat_id=owner, text=t(L, "ch_max", n=MAX_CHANNELS))
            return True
        my_phone = fmt_phone(u["phone"]) if u.get("phone") else ""
        create_channel(cid, owner, title, L, [my_phone] if my_phone else [])
        log.info("Kanal ulandi: %s (%s) egasi %s", title, cid, owner)
    tg("sendMessage", chat_id=owner, parse_mode="HTML", text=t(L, "ch_added", title=esc(title)))
    show_menu(channel_user(cid, owner), None, "main")
    return True


def _edit_or_send(u, msg_id, text, kb):
    if msg_id:
        tg("editMessageText", chat_id=u["chat_id"], message_id=msg_id, text=text, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=u["chat_id"], text=text, parse_mode="HTML", reply_markup=kb)


def sub_page(u, msg_id=None):
    """1-qadam: tarif tanlash."""
    L = u["lang"]
    text = t(L, "sub_page", status=sub_status(u), p1=fmt_num(PRICE), p3=fmt_num(PRICE_3),
             save=fmt_num(max(0, PRICE * 3 - PRICE_3)))
    kb = {"inline_keyboard": [[btn(t(L, "b_plan1", p=fmt_num(PRICE)), "plan:1")],
                              [{**btn(t(L, "b_plan3", p=fmt_num(PRICE_3)), "plan:3"), "style": "success"}],
                              [btn(t(L, "b_home"), "home")]]}
    _edit_or_send(u, msg_id, text, kb)


def pay_page(u, plan, msg_id=None):
    """2-qadam: tanlangan tarif bo'yicha karta va chek yuborish."""
    L = u["lang"]
    days, price = PLANS[plan]
    text = t(L, "pay_page", plan=t(L, f"plan_name{plan}"), price=fmt_num(price),
             card=esc(pay_card()) if pay_card() else t(L, "no_card"), name=esc(pay_name()))
    kb = {"inline_keyboard": [[{**btn(t(L, "b_send_check"), f"paycheck:{plan}"), "style": "success"}],
                              [btn(t(L, "b_plans"), "sub")]]}
    _edit_or_send(u, msg_id, text, kb)


def forward_check(u, msg, plan=None):
    """Chekni adminga yuboradi: rasm + tasdiqlash tugmalari (tanlangan tarif birinchi turadi)."""
    tg("copyMessage", chat_id=ADMIN_ID, from_chat_id=u["chat_id"], message_id=msg["message_id"])
    who = f"{esc(u.get('first_name') or '')} @{esc(u.get('username') or '-')}\n📱 {esc(u.get('phone') or '')}\n🆔 {u['chat_id']}"
    status = sub_status(get_user(u["chat_id"]) | {"lang": "uz"})
    cid = u["chat_id"]
    b1 = {**btn(f"✅ Start (+{PLANS[1][0]} kun)", f"pay:ok:{cid}:{PLANS[1][0]}"), "style": "success"}
    b3 = {**btn(f"✅ Pro (+{PLANS[3][0]} kun)", f"pay:ok:{cid}:{PLANS[3][0]}"), "style": "success"}
    kb = {"inline_keyboard": [[b3, b1] if plan == 3 else [b1, b3],
                              [{**btn("❌ Rad etish", f"pay:no:{cid}"), "style": "danger"}]]}
    if plan in PLANS:
        what = f"Tarif: <b>{'🏆 Pro, 3 oy' if plan == 3 else '🚀 Start, 1 oy'} — {fmt_num(PLANS[plan][1])} so'm</b>"
    else:
        what = "Tarif: <b>tanlanmagan</b> (chekdagi summaga qarang)"
    tg("sendMessage", chat_id=ADMIN_ID, parse_mode="HTML", reply_markup=kb,
       text=f"💳 <b>Yangi to'lov cheki</b>\n{what}\n\n{who}\n{status}")


def extend_sub(chat_id, days):
    with ulock:
        u = get_user(chat_id)
        start = max(time.time(), access_until(u))
        u["s"]["sub_until"] = int(start + days * 86400)
        u["s"].pop("warned", None)
        set_user(chat_id, s=u["s"])
    return get_user(chat_id)


def card_page(admin_chat, msg_id=None, note=""):
    card, name = pay_card(), pay_name()
    text = ((note + "\n\n") if note else "") + (
        "💳 <b>To'lov kartasi</b>\n\nMijozlar «💎 Tariflar» bo'limida shu ma'lumotlarni ko'radi.\n\n"
        f"Karta raqami: <code>{esc(card) if card else '— kiritilmagan —'}</code>\n"
        f"Karta egasi: <b>{esc(name) if name else '— kiritilmagan —'}</b>")
    kb = {"inline_keyboard": [[{**btn("✏️ Karta raqamini o'zgartirish", "cfg:card"), "style": "primary"}],
                              [{**btn("✏️ Karta egasining ismini o'zgartirish", "cfg:name"), "style": "primary"}],
                              [btn("🏠 Asosiy menyu", "home")]]}
    if msg_id:
        tg("editMessageText", chat_id=admin_chat, message_id=msg_id, text=text, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=admin_chat, text=text, parse_mode="HTML", reply_markup=kb)


# ======================= ADMIN: FOYDALANUVCHILAR BAZASI =======================

USERS_PAGE = 10


def record_payment(chat_id, days, source):
    plan = "Pro" if days == PLANS[3][0] else "Start" if days == PLANS[1][0] else f"{days} kun"
    amount = PLANS[3][1] if days == PLANS[3][0] else PLANS[1][1] if days == PLANS[1][0] else 0
    db.execute("INSERT INTO payments (chat_id, days, amount, plan, ts, source) VALUES (?,?,?,?,?,?)",
               (str(chat_id), days, amount, plan, int(time.time()), source))
    db.commit()


def dt(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%d.%m.%Y %H:%M") if ts else "—"


def last_seen(chat_id):
    r = db.execute("SELECT last_seen FROM activity WHERE chat_id=?", (str(chat_id),)).fetchone()
    return r[0] if r else None


def all_people(query=""):
    """Kanallardan tashqari barcha foydalanuvchilar, yangilari birinchi."""
    rows = db.execute("SELECT chat_id FROM users WHERE chat_id NOT LIKE '-100%' ORDER BY created DESC").fetchall()
    people = [get_user(c) for (c,) in rows]
    q = query.strip().lower().lstrip("@")
    if q:
        qd = re.sub(r"\D", "", q)
        people = [p for p in people if q == str(p["chat_id"]) or q in str(p.get("username") or "").lower()
                  or q in str(p.get("first_name") or "").lower() or (len(qd) >= 4 and qd in re.sub(r"\D", "", p.get("phone") or ""))]
    return people


def status_icon(p):
    if str(p["chat_id"]) == ADMIN_ID:
        return "👑"
    if not p["lang"] or p["phone"] is None:
        return "⏳"          # ro'yxatdan o'tishni tugatmagan
    if not p["active"]:
        return "🚫"          # botni bloklagan
    if not has_access(p):
        return "⛔️"
    return "🎁" if on_trial(p) else "✅"


def users_page(admin_chat, page=0, msg_id=None, query=""):
    people = all_people(query)
    total = len(people)
    pages = max(1, -(-total // USERS_PAGE))
    page = max(0, min(page, pages - 1))
    chunk = people[page * USERS_PAGE:(page + 1) * USERS_PAGE]
    paid = sum(1 for p in people if p["s"].get("sub_until", 0) > time.time())
    trial = sum(1 for p in people if p["phone"] is not None and on_trial(p) and has_access(p))
    exp = sum(1 for p in people if p["phone"] is not None and not has_access(p))
    income = db.execute("SELECT COALESCE(SUM(amount),0), COUNT(*) FROM payments").fetchone()
    head = ("👥 <b>Foydalanuvchilar</b>" + (f" — qidiruv: «{esc(query)}»" if query else "") + f"\n\n"
            f"Jami: <b>{total}</b> · ✅ To'lagan: {paid} · 🎁 Sinovda: {trial} · ⛔️ Tugagan: {exp}\n"
            f"💰 Jami tushum: <b>{fmt_num(income[0])} so'm</b> ({income[1]} ta to'lov)\n\n"
            "✅ to'lagan · 🎁 sinovda · ⛔️ muddati tugagan · ⏳ ro'yxatdan o'tmagan · 🚫 botni bloklagan\n"
            f"Sahifa {page + 1}/{pages}")
    rows = []
    for p in chunk:
        name = (p.get("first_name") or "").strip() or "—"
        uname = f" @{p['username']}" if p.get("username") else ""
        rows.append([btn(f"{status_icon(p)} {name}{uname}"[:60], f"adm:u:{p['chat_id']}")])
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"adm:list:{page - 1}"))
    if page < pages - 1:
        nav.append(btn("▶️", f"adm:list:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([{**btn("🔍 Qidirish", "adm:find"), "style": "primary"},
                 {**btn("📥 Excel'ga yuklab olish", "adm:csv"), "style": "success"}])
    if query:
        rows.append([btn("❌ Qidiruvni bekor qilish", "adm:list:0")])
    kb = {"inline_keyboard": rows}
    if msg_id:
        tg("editMessageText", chat_id=admin_chat, message_id=msg_id, text=head, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=admin_chat, text=head, parse_mode="HTML", reply_markup=kb)


def user_card(admin_chat, uid, msg_id=None):
    p = get_user(uid)
    if not p:
        tg("sendMessage", chat_id=admin_chat, text="Foydalanuvchi topilmadi.")
        return
    s = p["s"]
    if str(uid) == ADMIN_ID:
        sub = "👑 Admin — cheklovsiz"
    elif p["phone"] is None:
        sub = "⏳ Ro'yxatdan o'tishni tugatmagan"
    else:
        sub = sub_status(dict(p, lang="uz"))
    pays = db.execute("SELECT ts, plan, amount, days, source FROM payments WHERE chat_id=? ORDER BY ts DESC",
                      (str(uid),)).fetchall()
    pay_lines = "\n".join(f"  • {dt(ts)} — {esc(plan)} ({days} kun), {fmt_num(amount)} so'm"
                           + (" [qo'lda]" if src != "chek" else "") for ts, plan, amount, days, src in pays) or "  —"
    chs = channels_of(uid)
    ch_lines = "\n".join(f"  • {esc(c['s'].get('title', ''))} {'🟢' if not c['s']['paused'] else '🔴'}" for c in chs) or "  —"
    flt = (f"{names(s['sources'], SOURCES, 'uz')} · {names(s['deals'], DEALS, 'uz')} · "
           f"{names(s['ptypes'], PTYPES, 'uz')} · tumanlar: {names(s['districts'], DISTRICTS, 'uz')}")
    text = (f"👤 <b>{esc(p.get('first_name') or '—')}</b>\n\n"
            f"🔗 Username: {('@' + esc(p['username'])) if p.get('username') else '—'}\n"
            f"📱 Telefon: <code>{esc(p.get('phone') or '—')}</code>\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"🌐 Til: {'O‘zbekcha' if p['lang'] == 'uz' else 'Русский' if p['lang'] == 'ru' else '—'}\n"
            f"📅 Botga kirgan: {dt(p.get('created'))}\n"
            f"🕒 Oxirgi faollik: {dt(last_seen(uid))}\n"
            f"{'🚫 Botni bloklagan' if not p['active'] else '🔔 Xabarlar: ' + ('⏸ to‘xtatilgan' if s.get('paused') else 'yoqilgan')}\n\n"
            f"💎 <b>Tarif:</b> {sub}\n"
            f"💳 <b>To'lovlar:</b>\n{pay_lines}\n\n"
            f"📢 <b>Kanallari:</b>\n{ch_lines}\n\n"
            f"⚙️ <b>Filtr:</b> {esc(flt)}")
    kb = {"inline_keyboard": [
        [{**btn(f"➕ Start (+{PLANS[1][0]} kun)", f"adm:add:{uid}:{PLANS[1][0]}"), "style": "success"},
         {**btn(f"➕ Pro (+{PLANS[3][0]} kun)", f"adm:add:{uid}:{PLANS[3][0]}"), "style": "success"}],
        [btn("⬅️ Ro'yxat", "adm:list:0")]]}
    if msg_id:
        tg("editMessageText", chat_id=admin_chat, message_id=msg_id, text=text, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=admin_chat, text=text, parse_mode="HTML", reply_markup=kb)


def send_users_csv(admin_chat):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ID", "Ism", "Username", "Telefon", "Til", "Botga kirgan", "Oxirgi faollik", "Holat",
                "Tarif tugash sanasi", "To'lovlar soni", "To'langan summa (so'm)", "Oxirgi to'lov",
                "Kanallar", "Botni bloklagan"])
    for p in all_people():
        pays = db.execute("SELECT COUNT(*), COALESCE(SUM(amount),0), MAX(ts) FROM payments WHERE chat_id=?",
                          (str(p["chat_id"]),)).fetchone()
        icon = status_icon(p)
        state = {"👑": "Admin", "⏳": "Ro'yxatdan o'tmagan", "🚫": "Bloklagan", "⛔️": "Muddati tugagan",
                 "🎁": "Sinovda", "✅": "To'lagan"}.get(icon, "")
        w.writerow([p["chat_id"], p.get("first_name") or "", ("@" + p["username"]) if p.get("username") else "",
                    p.get("phone") or "", p["lang"] or "", dt(p.get("created")), dt(last_seen(p["chat_id"])), state,
                    dt(access_until(p)) if p["phone"] is not None and icon != "👑" else "",
                    pays[0], pays[1], dt(pays[2]) if pays[2] else "",
                    ", ".join(c["s"].get("title", "") for c in channels_of(p["chat_id"])),
                    "ha" if not p["active"] else "yo'q"])
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM — Excel o'zbekcha harflarni to'g'ri ochadi
    name = f"foydalanuvchilar_{datetime.now(TZ):%Y-%m-%d}.csv"
    try:
        requests.post(f"{TG}/sendDocument", data={"chat_id": admin_chat, "caption": f"📥 {len(all_people())} ta foydalanuvchi"},
                      files={"document": (name, data, "text/csv")}, timeout=60)
    except Exception as e:
        log.warning("CSV yuborilmadi: %s", e)


def handle_admin_cb(admin_chat, msg_id, data):
    parts = data.split(":")
    if parts[1] == "list":
        users_page(admin_chat, int(parts[2]), msg_id)
    elif parts[1] == "u":
        user_card(admin_chat, parts[2], msg_id)
    elif parts[1] == "add":
        uid, days = parts[2], int(parts[3])
        nu = extend_sub(uid, days)
        record_payment(uid, days, "qo'lda")
        tg("sendMessage", chat_id=uid, text=t(nu["lang"] or "uz", "sub_ok", u=until_text(access_until(nu), nu["lang"] or "uz")))
        user_card(admin_chat, uid, msg_id)
    elif parts[1] == "find":
        awaiting[admin_chat] = {"step": "adm_find"}
        tg("sendMessage", chat_id=admin_chat, text="🔍 Ism, @username, telefon yoki ID yozing:")
    elif parts[1] == "csv":
        send_users_csv(admin_chat)


def handle_pay_cb(admin_chat, msg_id, data, q):
    parts = data.split(":")
    uid = parts[2]
    u = get_user(uid)
    if not u:
        return
    if parts[1] == "ok":
        days = int(parts[3])
        u = extend_sub(uid, days)
        record_payment(uid, days, "chek")
        tg("sendMessage", chat_id=uid, text=t(u["lang"], "sub_ok", u=until_text(access_until(u), u["lang"])))
        res = f"✅ Tasdiqlandi: +{days} kun → {datetime.fromtimestamp(access_until(u), TZ):%d.%m.%Y}"
        log.info("Obuna: %s +%s kun", uid, days)
    else:
        tg("sendMessage", chat_id=uid, text=t(u["lang"], "sub_no"))
        res = "❌ Rad etildi"
    old = (q.get("message") or {}).get("text") or ""
    tg("editMessageText", chat_id=admin_chat, message_id=msg_id, text=old + "\n\n" + res)


def check_subscriptions():
    """Muddat tugashidan 1 kun oldin va tugaganda bir marta ogohlantiradi."""
    now = time.time()
    for (cid,) in db.execute("SELECT chat_id FROM users WHERE active=1 AND phone IS NOT NULL AND lang IS NOT NULL "
                             "AND chat_id NOT LIKE '-100%'").fetchall():
        if str(cid) == ADMIN_ID:
            continue
        u = get_user(cid)
        until = access_until(u)
        what = t(u["lang"], "w_trial" if on_trial(u) else "w_sub")
        stage = u["s"].get("warned")
        if until <= now and stage != f"end:{until}":
            tg("sendMessage", chat_id=cid, text=t(u["lang"], "sub_end", what=what),
               reply_markup={"inline_keyboard": [[{**btn(t(u["lang"], "b_sub"), "sub"), "style": "success"}]]})
            new = f"end:{until}"
        elif 0 < until - now <= 86400 and stage not in (f"warn:{until}", f"end:{until}"):
            d = datetime.fromtimestamp(until, TZ).strftime("%d.%m.%Y %H:%M")
            tg("sendMessage", chat_id=cid, text=t(u["lang"], "sub_warn", what=what, d=d))
            new = f"warn:{until}"
        else:
            continue
        with ulock:
            fresh = get_user(cid)
            fresh["s"]["warned"] = new
            set_user(cid, s=fresh["s"])


def lang_page(u, msg_id=None):
    """Asosiy menyudan ochiladigan til sahifasi (alohida xabar emas, o'sha xabar o'zgaradi)."""
    L = u["lang"]
    kb = {"inline_keyboard": [
        [fbtn(("✅ " if L == "uz" else "") + "🇺🇿 O'zbekcha", "ulang:uz", L == "uz"),
         fbtn(("✅ " if L == "ru" else "") + "🇷🇺 Русский", "ulang:ru", L == "ru")],
        [btn(t(L, "b_back"), "home")]]}
    text = t(L, "lang_page")
    if msg_id:
        tg("editMessageText", chat_id=u["chat_id"], message_id=msg_id, text=text, parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=u["chat_id"], text=text, parse_mode="HTML", reply_markup=kb)


def set_commands_for(chat_id, lang):
    """Меню buyruqlari tavsifini shu foydalanuvchi uchun tanlangan tilda ko'rsatadi."""
    if str(chat_id) == ADMIN_ID:
        return
    tg("setMyCommands", scope={"type": "chat", "chat_id": int(chat_id)}, commands=[
        {"command": "start", "description": t(lang, "cmd_start")},
        {"command": "menu", "description": t(lang, "cmd_menu")},])


def ask_lang(chat_id):
    tg("sendMessage", chat_id=chat_id, text=t("uz", "choose_lang"),
       reply_markup={"inline_keyboard": [[btn("🇺🇿 O'zbekcha", "setlang:uz"),
                                          btn("🇷🇺 Русский", "setlang:ru")]]})


def ask_phone(u):
    tg("sendMessage", chat_id=u["chat_id"], text=t(u["lang"], "ask_phone"),
       reply_markup={"keyboard": [[{"text": t(u["lang"], "btn_phone"), "request_contact": True}]],
                     "resize_keyboard": True, "one_time_keyboard": True})


awaiting = {}   # chat_id -> {"deal": "rent", "step": "lo"/"hi", "lo": n}
ulock = threading.Lock()


def publish_ad(u, msg_id, ad_id, cid=None):
    """Foydalanuvchi ko'rgan e'lonni bitta tugma bilan o'z kanaliga joylaydi."""
    chat_id, L = u["chat_id"], u["lang"]
    if not has_access(u):
        tg("sendMessage", chat_id=chat_id, text=t(L, "need_sub"))
        sub_page(u)
        return
    chans = channels_of(chat_id)
    if not chans:
        tg("sendMessage", chat_id=chat_id, text=t(L, "pub_nochan"))
        return
    if cid is None and len(chans) > 1:
        rows = [[btn(t(L, "b_publish_to", title=(c["s"].get("title") or c["chat_id"])[:40]), f"pub:{ad_id}:{c['chat_id']}")]
                for c in chans]
        tg("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id, reply_markup={"inline_keyboard": rows})
        return
    ch = next((c for c in chans if c["chat_id"] == cid), None) if cid else chans[0]
    if not ch:
        return
    title = ch["s"].get("title") or ch["chat_id"]
    row = db.execute("SELECT deal, data FROM ad_cache WHERE ad_id=?", (str(ad_id),)).fetchone()
    if not row:
        tg("sendMessage", chat_id=chat_id, text=t(L, "pub_gone"))
        return
    if was_sent(ch["chat_id"], ad_id):
        tg("sendMessage", chat_id=chat_id, text=t(L, "pub_already", title=title))
        return
    deal, ad = row[0], json.loads(row[1])
    ad.pop("phone_text", None)   # kanalda sotuvchi raqami emas, kanal raqamlari chiqadi
    if send_ad(ad, deal, ch):
        tg("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
           reply_markup={"inline_keyboard": [[{**btn(t(L, "b_published"), "noop"), "style": "success"}]]})
        log.info("Qo'lda kanalga: %s -> %s", ad_id, ch["chat_id"])
    else:
        tg("sendMessage", chat_id=chat_id, text=t(L, "pub_fail", title=title))


def handle_callback(q):
    chat_id = str(q["message"]["chat"]["id"])
    msg_id = q["message"]["message_id"]
    data = q.get("data", "")
    threading.Thread(target=tg, args=("answerCallbackQuery",), kwargs={"callback_query_id": q["id"]},
                     daemon=True).start()
    if data.startswith("pay:"):
        if chat_id == ADMIN_ID:
            handle_pay_cb(chat_id, msg_id, data, q)
        return
    if data.startswith("adm:"):
        if chat_id == ADMIN_ID:
            handle_admin_cb(chat_id, msg_id, data)
        return
    if data.startswith("cfg:"):
        if chat_id == ADMIN_ID:
            what = data[4:]
            awaiting[chat_id] = {"step": f"cfg_{what}"}
            tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=(
                "💳 Karta raqamini yozing (16 ta raqam), masalan: <code>8600 1234 5678 9012</code>"
                if what == "card" else "👤 Karta egasining ismini yozing, masalan: <code>Sardor T.</code>"))
        return
    m = re.match(r"^C(-\d+)\|(.*)$", data)
    if m:
        cid = m.group(1)
        c = get_user(cid)
        if c and str(c["s"].get("owner")) == chat_id:   # faqat kanal egasi
            handle_channel_cb(chat_id, msg_id, cid, m.group(2))
        return
    u = ensure_user(chat_id, q.get("from") or {})

    if data.startswith("setlang:"):
        lang = data.split(":")[1]
        set_user(chat_id, lang=lang, active=1)
        u = get_user(chat_id)
        tg("editMessageText", chat_id=chat_id, message_id=msg_id, text=t(lang, "lang_set"))
        if not u["phone"]:   # raqam hali yuborilmagan (admin ko'chirilganda ham bo'sh)
            ask_phone(u)
        else:
            send_main(u)
        return
    if not registered(u):
        if not u["lang"]:
            ask_lang(chat_id)
        else:
            ask_phone(u)
        return
    if data == "noop":
        return
    if data.startswith("pub:"):
        m2 = re.match(r"^pub:(.+?)(?::(-100\d+))?$", data)
        if m2:
            publish_ad(u, msg_id, m2.group(1), m2.group(2))
        return
    if data == "done":
        send_main(u, "filter_saved", msg_id)
        return
    if data == "home":
        send_main(u, None, msg_id)
        return
    if data == "help":
        send_main(u, "help", msg_id)
        return
    if data == "lang":           # menyu ichida: shu xabar til sahifasiga aylanadi
        lang_page(u, msg_id)
        return
    if data.startswith("ulang:"):
        lang = data.split(":")[1]
        if lang in ("uz", "ru"):
            set_user(chat_id, lang=lang)
            set_commands_for(chat_id, lang)
        lang_page(get_user(chat_id), msg_id)
        return
    if data == "sub":
        awaiting.pop(chat_id, None)
        sub_page(u, msg_id)
        return
    if data.startswith("plan:"):
        plan = int(data.split(":")[1])
        if plan in PLANS:
            pay_page(u, plan, msg_id)
        return
    if data.startswith("paycheck"):
        plan = int(data.split(":")[1]) if ":" in data else None
        awaiting[chat_id] = {"step": "check", "plan": plan}
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "ask_check"))
        return
    if data.startswith("last") and not has_access(u):
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "need_sub"))
        sub_page(u)
        return
    if data == "chpage":
        awaiting.pop(chat_id, None)
        channels_page(u, msg_id)
        return
    if data == "chadd":
        awaiting[chat_id] = {"step": "channel"}
        tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=t(u["lang"], "ch_add_help", bot=BOT_USERNAME))
        return
    if data.startswith("m:"):
        show_menu(u, msg_id, data[2:])
        return
    if data.startswith("t:"):
        _, field, key = data.split(":", 2)
        with ulock:
            u = get_user(chat_id)
            lst = u["s"][field]
            if key in lst:
                lst.remove(key)
            else:
                lst.append(key)
            if field in ("deals", "sources", "ptypes") and not lst:   # kamida bittasi qolsin
                lst.append(key)
            set_user(chat_id, s=u["s"])
        show_menu(u, msg_id, field)
        return
    if data == "reset":
        with ulock:
            u = get_user(chat_id)
            keep = {k: u["s"][k] for k in ("paused", "kb_removed") if k in u["s"]}
            u["s"] = {**json.loads(json.dumps(DEFAULT_SETTINGS)), **keep}
            set_user(chat_id, s=u["s"])
        show_menu(u, msg_id, "main")
        return
    if data.startswith("clr:"):
        field = data[4:]
        with ulock:
            u = get_user(chat_id)
            u["s"][field] = list(TABLES[field]) if field in ("deals", "sources", "ptypes") else []
            set_user(chat_id, s=u["s"])
        show_menu(u, msg_id, field)
        return
    if data.startswith("p:"):
        deal = data[2:]
        awaiting[chat_id] = {"deal": deal, "step": "lo"}
        tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
           text=t(u["lang"], "ask_lo", name=t(u["lang"], f"p_{deal}")))
        return
    if data.startswith("last"):
        days = int(data.split(":")[1]) if ":" in data else LATEST_DAYS
        threading.Thread(target=send_latest, args=(chat_id, days), daemon=True).start()
        return
    if data == "pause":
        toggle_pause(chat_id, msg_id)


def handle_channel_cb(owner_chat, msg_id, cid, data):
    def cu():
        return channel_user(cid, owner_chat)
    u = cu()
    L = u["lang"]
    if data.startswith("m:"):
        show_menu(u, msg_id, data[2:])
    elif data.startswith("t:"):
        _, field, key = data.split(":", 2)
        with ulock:
            u = cu()
            lst = u["s"][field]
            lst.remove(key) if key in lst else lst.append(key)
            if field in ("deals", "sources", "ptypes") and not lst:
                lst.append(key)
            set_user(cid, s=u["s"])
        show_menu(u, msg_id, field)
    elif data.startswith("clr:"):
        field = data[4:]
        with ulock:
            u = cu()
            u["s"][field] = list(TABLES[field]) if field in ("deals", "sources", "ptypes") else []
            set_user(cid, s=u["s"])
        show_menu(u, msg_id, field)
    elif data == "reset":
        with ulock:
            u = cu()
            keep = {k: u["s"][k] for k in ("paused", "owner", "title", "phones", "header") if k in u["s"]}
            u["s"] = {**json.loads(json.dumps(DEFAULT_SETTINGS)), **keep}
            set_user(cid, s=u["s"])
        show_menu(u, msg_id, "main")
    elif data == "pause":
        if u["s"]["paused"] and not u["s"].get("phones"):
            tg("sendMessage", chat_id=owner_chat, text=t(L, "ph_need"))
            phones_page(u)
            return
        with ulock:
            u = cu()
            u["s"]["paused"] = not u["s"]["paused"]
            set_user(cid, s=u["s"])
        show_menu(u, msg_id, "main")
    elif data == "header":
        header_page(u, msg_id)
    elif data.startswith("hd:"):
        n = int(data[3:])
        if 1 <= n <= TPL_COUNT:
            with ulock:
                u = cu()
                u["s"]["header"] = n
                set_user(cid, s=u["s"])
        header_page(u, msg_id)
    elif data == "phones":
        phones_page(u, msg_id)
    elif data == "phadd":
        if len(u["s"].get("phones") or []) >= MAX_PHONES:
            tg("sendMessage", chat_id=owner_chat, text=t(L, "ph_full", m=MAX_PHONES))
            return
        awaiting[owner_chat] = {"step": "phone", "target": cid}
        tg("sendMessage", chat_id=owner_chat, parse_mode="HTML", text=t(L, "ph_ask"))
    elif data.startswith("phdel:"):
        i = int(data.split(":")[1])
        with ulock:
            u = cu()
            phones = u["s"].get("phones") or []
            if 0 <= i < len(phones):
                phones.pop(i)
            u["s"]["phones"] = phones
            if not phones:
                u["s"]["paused"] = True     # raqamsiz kanalga yuborilmaydi
            set_user(cid, s=u["s"])
        phones_page(u, msg_id)
    elif data.startswith("p:"):
        deal = data[2:]
        awaiting[owner_chat] = {"deal": deal, "step": "lo", "target": cid}
        tg("sendMessage", chat_id=owner_chat, parse_mode="HTML",
           text=t(L, "ask_lo", name="📢 " + t(L, f"p_{deal}")))
    elif data == "chdel":
        kb = prefix_kb({"inline_keyboard": [[{**btn(t(L, "b_yes_del"), "chdelok"), "style": "danger"},
                                             btn(t(L, "b_no"), "m:main")]]}, u["prefix"])
        tg("editMessageText", chat_id=owner_chat, message_id=msg_id,
           text=t(L, "ch_del_q", title=u["s"].get("title", "")), reply_markup=kb)
    elif data == "chdelok":
        db.execute("DELETE FROM users WHERE chat_id=?", (cid,))
        db.commit()
        log.info("Kanal uzildi: %s", cid)
        owner = get_user(owner_chat)
        tg("sendMessage", chat_id=owner_chat, text=t(L, "ch_deleted"))
        channels_page(owner, msg_id)
    elif data == "done":
        owner = get_user(owner_chat)
        channels_page(owner, msg_id)


def handle_message(msg):
    chat_id = str(msg["chat"]["id"])
    frm = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    u = ensure_user(chat_id, frm)

    # ro'yxatdan o'tish: kontakt
    if "contact" in msg:
        c = msg["contact"]
        if str(c.get("user_id")) != str(frm.get("id")):
            tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "own_phone"))
            return
        set_user(chat_id, phone=c.get("phone_number", ""), first_name=frm.get("first_name", ""),
                 username=frm.get("username", ""), active=1)
        u = get_user(chat_id)
        log.info("Yangi foydalanuvchi: %s %s (%s)", u["first_name"], u["phone"], chat_id)
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "registered"), reply_markup={"remove_keyboard": True})
        tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=t(u["lang"], "trial_hello", n=TRIAL_DAYS))
        with ulock:
            fresh = get_user(chat_id)
            fresh["s"]["kb_removed"] = True
            set_user(chat_id, s=fresh["s"])
        u = get_user(chat_id)
        show_menu(u, None, "main")
        return

    if text.startswith("/start") or text.startswith("/til"):
        set_user(chat_id, active=1)
        awaiting.pop(chat_id, None)
        ask_lang(chat_id)          # /start da har doim avval til tanlanadi
        return
    if not u["lang"]:
        ask_lang(chat_id)
        return
    if u["phone"] is None:
        ask_phone(u)
        return

    if text.startswith("/menu"):
        awaiting.pop(chat_id, None)
        send_main(u)
        return
    action = kb_action(text)
    if action:
        awaiting.pop(chat_id, None)
        if action == "filter":
            show_menu(u, None, "main")
        elif action == "last1":
            threading.Thread(target=send_latest, args=(chat_id, 1), daemon=True).start()
        elif action == "lastN":
            threading.Thread(target=send_latest, args=(chat_id, LATEST_DAYS), daemon=True).start()
        elif action == "pause":
            toggle_pause(chat_id)
        elif action == "lang":
            lang_page(u)
        elif action == "help":
            send_main(u, "help")
        return
    st0 = awaiting.get(chat_id)
    if st0 and st0.get("step") == "check":
        if "photo" in msg or ("document" in msg and str(msg["document"].get("mime_type", "")).startswith(("image", "application/pdf"))):
            awaiting.pop(chat_id, None)
            forward_check(u, msg, st0.get("plan"))
            tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "check_sent"))
        else:
            tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "check_need_photo"))
        return
    if ("photo" in msg and chat_id != ADMIN_ID and not st0     # chek tugmasini bosmay rasm yuborsa ham qabul qilamiz
            and not msg.get("forward_origin") and not msg.get("forward_from_chat")):
        forward_check(u, msg)
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "check_sent"))
        return
    if chat_id == ADMIN_ID and text.startswith("/users"):
        awaiting.pop(chat_id, None)
        users_page(chat_id)
        return
    if chat_id == ADMIN_ID and st0 and st0.get("step") == "adm_find":
        awaiting.pop(chat_id, None)
        found = all_people(text)
        if len(found) == 1:
            user_card(chat_id, found[0]["chat_id"])
        else:
            users_page(chat_id, 0, None, text)
        return
    if chat_id == ADMIN_ID and text.startswith("/karta"):
        awaiting.pop(chat_id, None)
        card_page(chat_id)
        return
    if chat_id == ADMIN_ID and st0 and st0.get("step") in ("cfg_card", "cfg_name"):
        if st0["step"] == "cfg_card":
            d = re.sub(r"\D", "", text)
            if len(d) != 16:
                tg("sendMessage", chat_id=chat_id, text="Karta raqami 16 ta raqamdan iborat bo'lishi kerak. Qaytadan yozing.")
                return
            cfg_set("pay_card", fmt_card(d))
            note = "✅ Karta raqami saqlandi."
        else:
            if not (2 <= len(text) <= 40):
                tg("sendMessage", chat_id=chat_id, text="Ism 2–40 belgidan iborat bo'lsin. Qaytadan yozing.")
                return
            cfg_set("pay_name", text)
            note = "✅ Karta egasining ismi saqlandi."
        awaiting.pop(chat_id, None)
        log.info("Admin to'lov ma'lumotini o'zgartirdi: %s", st0["step"])
        card_page(chat_id, note=note)
        return
    if chat_id == ADMIN_ID and text.startswith("/obuna"):
        p = text.split()
        if len(p) == 3 and p[2].lstrip("-").isdigit() and get_user(p[1]):
            nu = extend_sub(p[1], int(p[2]))
            if int(p[2]) > 0:
                record_payment(p[1], int(p[2]), "qo'lda")
            tg("sendMessage", chat_id=chat_id, text=f"✅ {p[1]}: {until_text(access_until(nu), 'uz')}")
            if int(p[2]) > 0:
                tg("sendMessage", chat_id=p[1], text=t(nu["lang"], "sub_ok", u=until_text(access_until(nu), nu["lang"])))
        else:
            tg("sendMessage", chat_id=chat_id, text="Foydalanish: /obuna <ID> <kun>\nMasalan: /obuna 881963945 30")
        return
    if (text.startswith("/oxirgi") or text.startswith("/on_kun")) and not has_access(u):
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "need_sub"))
        sub_page(u)
        return
    if text.startswith("/kanal"):
        awaiting.pop(chat_id, None)
        channels_page(u)
        return
    st = awaiting.get(chat_id)
    if st and st.get("step") == "channel":
        if add_channel(u, msg):
            awaiting.pop(chat_id, None)
        return
    if st and st.get("step") == "phone":
        digits = re.sub(r"\D", "", text)
        if not (9 <= len(digits) <= 15):
            tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "ph_bad"))
            return
        awaiting.pop(chat_id, None)
        p = fmt_phone(text)
        with ulock:
            cu = get_user(st["target"])
            phones = cu["s"].get("phones") or []
            if p not in phones and len(phones) < MAX_PHONES:
                phones.append(p)
            cu["s"]["phones"] = phones
            set_user(st["target"], s=cu["s"])
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "ph_added", p=p))
        phones_page(channel_user(st["target"], chat_id))
        return
    if chat_id == ADMIN_ID and text.startswith("/stats"):
        tot = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        reg = db.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
        act = len(active_users())
        chs = db.execute("SELECT COUNT(*) FROM users WHERE chat_id LIKE '-100%'").fetchone()[0]
        allu = [get_user(c) for (c,) in db.execute("SELECT chat_id FROM users WHERE chat_id NOT LIKE '-100%' "
                                                   "AND phone IS NOT NULL").fetchall()]
        paid = sum(1 for x in allu if x["s"].get("sub_until", 0) > time.time())
        trial = sum(1 for x in allu if on_trial(x) and has_access(x))
        exp = sum(1 for x in allu if not has_access(x))
        tg("sendMessage", chat_id=chat_id,
           text=f"👥 Jami: {tot - chs}\n✅ Ro'yxatdan o'tgan: {reg - chs}\n📢 Ulangan kanallar: {chs}\n"
                f"▶️ Faol (pauzada emas, kanallar bilan): {act}\n"
                f"💳 To'lagan: {paid} · 🎁 Sinovda: {trial} · ⛔️ Muddati tugagan: {exp}")
        return
    if text.startswith("/oxirgi"):
        threading.Thread(target=send_latest, args=(chat_id, 1), daemon=True).start()
        return
    if text.startswith("/on_kun") or text.startswith("/uch_kun"):
        threading.Thread(target=send_latest, args=(chat_id, LATEST_DAYS), daemon=True).start()
        return
    if text.startswith("/filtr"):
        awaiting.pop(chat_id, None)
        show_menu(u, None, "main")
        return
    if chat_id in awaiting and awaiting[chat_id].get("step") in ("lo", "hi"):
        digits = re.sub(r"[\s$,.']", "", text)
        if not digits.isdigit():
            tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "only_num"))
            return
        num = int(digits) or None
        st = awaiting[chat_id]
        if st["step"] == "lo":
            st.update(step="hi", lo=num)
            tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=t(u["lang"], "ask_hi"))
            return
        lo, hi = st["lo"], num
        if lo and hi and lo > hi:
            lo, hi = hi, lo
        awaiting.pop(chat_id)
        target = st.get("target", chat_id)
        with ulock:
            tu = get_user(target)
            tu["s"]["price"][st["deal"]] = [lo, hi]
            set_user(target, s=tu["s"])
        tg("sendMessage", chat_id=chat_id, text=t(u["lang"], "saved", v=price_str([lo, hi], u["lang"])))
        show_menu(channel_user(target, chat_id) if target != chat_id else get_user(chat_id), None, "main")
        return
    send_main(u)


_last_touch = {}


def touch(chat_id):
    """Foydalanuvchining oxirgi faolligini yozib boradi (har daqiqada ko'pi bilan bir marta)."""
    now = int(time.time())
    if now - _last_touch.get(chat_id, 0) < 60:
        return
    _last_touch[chat_id] = now
    db.execute("INSERT OR REPLACE INTO activity VALUES (?,?)", (str(chat_id), now))
    db.commit()


def handle_update(u):
    try:
        src = u.get("callback_query") or u.get("message") or {}
        cid = ((src.get("message") or src).get("chat") or {}).get("id")
        if cid and not str(cid).startswith("-"):
            touch(str(cid))
    except Exception:
        pass
    if "callback_query" in u:
        handle_callback(u["callback_query"])
    elif "message" in u:
        handle_message(u["message"])


def set_commands():
    """Меню tugmasida faqat /start va /til. Qolgan amallar pastki tugmalarda."""
    for lang in ("uz", "ru"):
        cmds = [{"command": "start", "description": t(lang, "cmd_start")},
                {"command": "menu", "description": t(lang, "cmd_menu")},]
        args = {"commands": cmds}
        if lang == "ru":
            args["language_code"] = "ru"
        tg("setMyCommands", **args)
    if ADMIN_ID:   # admin uchun qo'shimcha buyruqlar
        tg("setMyCommands", scope={"type": "chat", "chat_id": int(ADMIN_ID)}, commands=[
            {"command": "start", "description": t("uz", "cmd_start")},
            {"command": "menu", "description": t("uz", "cmd_menu")},
            {"command": "restart", "description": "Botni qayta ishga tushirish"},
            {"command": "stats", "description": "Foydalanuvchilar statistikasi"},
            {"command": "kanal", "description": "Kanalga yuboriladigan e'lonlar filtri"},
            {"command": "users", "description": "Foydalanuvchilar bazasi"},
            {"command": "karta", "description": "To'lov kartasini sozlash"},
            {"command": "obuna", "description": "Obunani qo'lda berish: /obuna ID kun"},
        ])


def is_restart(upd):
    m = upd.get("message") or {}
    return (str((m.get("from") or {}).get("id")) == ADMIN_ID
            and (m.get("text") or "").strip().startswith("/restart"))


def do_restart(upd, offset):
    chat_id = upd["message"]["chat"]["id"]
    try:   # buyruq bajarilganini Telegramga bildiramiz, aks holda qayta ishga tushgach yana keladi
        requests.get(f"{TG}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=15)
    except Exception:
        pass
    if not os.getenv("UYBOT_LAUNCHER"):
        tg("sendMessage", chat_id=chat_id, text=(
            "⚠️ /restart faqat bot start.bat orqali ishga tushirilganda ishlaydi.\n"
            "PowerShell'da Ctrl+C bosing va .\\start.bat deb yozing."))
        return
    tg("sendMessage", chat_id=chat_id, text="♻️ Bot qayta ishga tushmoqda... (5 soniya)")
    log.info("Qayta ishga tushirilmoqda...")
    with open("restart_chat.txt", "w") as f:
        f.write(str(chat_id))
    os._exit(3)   # start.bat 3-kodni ko'rib, botni shu oynada qayta ishga tushiradi


_chat_locks = {}
_chat_locks_guard = threading.Lock()
_workers = threading.BoundedSemaphore(16)


def _update_chat(upd):
    src = upd.get("callback_query") or upd.get("message") or {}
    return str(((src.get("message") or src).get("chat") or {}).get("id", ""))


def _run_update(upd):
    """Har bir chat o'z navbatida, turli chatlar esa parallel ishlanadi — bitta sekin so'rov hammani to'xtatmaydi."""
    with _chat_locks_guard:
        lock = _chat_locks.setdefault(_update_chat(upd), threading.Lock())
    try:
        with lock:
            handle_update(upd)
    except Exception as e:
        log.exception("Update xato: %s", e)
    finally:
        _workers.release()


def telegram_loop():
    set_commands()
    offset = 0
    while True:
        try:
            r = tg_session().get(f"{TG}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            if r.status_code == 409:
                log.error("DIQQAT: bot boshqa oynada ham ishlab turibdi! "
                          "Eski oynani yoping, aks holda bot sekin javob beradi.")
                time.sleep(3)
                continue
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                if is_restart(upd):
                    do_restart(upd, offset)
                    continue
                _workers.acquire()
                threading.Thread(target=_run_update, args=(upd,), daemon=True).start()
        except Exception as e:
            log.warning("getUpdates xato: %s", e)
            time.sleep(5)


# ======================= OLX =======================

_api_params = {}


def api_params(deal, ptype="apt"):
    if (deal, ptype) not in _api_params:
        path = f"{OLX_PATHS[(deal, ptype)]}/{CITY}".replace("/", ",")  # OLX vergul kutadi
        r = requests.get(f"{API}/friendly-links/query-params/{path}/", headers=HEADERS, proxies=OLX_PROXIES, timeout=20)
        r.raise_for_status()
        p = dict(r.json().get("data", {}))
        p.update(owner_type="private", sort_by="created_at:desc", limit=40, offset=0)
        _api_params[(deal, ptype)] = p
        log.info("%s -> %s", path, p)
    return _api_params[(deal, ptype)]


def fetch_offers(deal, ptype="apt", pages=2):
    """OLX ro'yxatida ko'tarilgan eski e'lonlar aralash turadi, shuning uchun 2 sahifa olamiz."""
    out, ids = [], set()
    params = dict(api_params(deal, ptype))
    for page in range(pages):
        params["offset"] = page * 40
        r = requests.get(f"{API}/offers/", params=params, headers=HEADERS, proxies=OLX_PROXIES, timeout=20)
        r.raise_for_status()
        for ad in r.json().get("data", []):
            if ad["id"] not in ids:
                ids.add(ad["id"])
                ad["ptype"] = ptype
                out.append(ad)
        if page + 1 < pages:
            time.sleep(1)
    return out


def seller_ad_count(uid):
    if not uid:
        return 0
    row = db.execute("SELECT cnt, ts FROM sellers WHERE uid=?", (str(uid),)).fetchone()
    if row and time.time() - row[1] < 86400:
        return row[0]
    try:
        r = requests.get(f"{API}/offers/", params={"user_id": uid, "limit": 1}, headers=HEADERS, proxies=OLX_PROXIES, timeout=20)
        cnt = r.json().get("metadata", {}).get("total_elements", 0)
    except Exception:
        cnt = 0
    db.execute("INSERT OR REPLACE INTO sellers VALUES (?,?,?)", (str(uid), cnt, int(time.time())))
    db.commit()
    return cnt


# ======================= JOYMEE =======================

JM_API = "https://api.joymee.uz/api/v1"
JM_CATS = {("rent", "apt"): 4, ("rent", "house"): 5, ("rent", "kom"): 6, ("rent", "land"): 7,
           ("sale", "apt"): 8, ("sale", "house"): 9, ("sale", "kom"): 10, ("sale", "land"): 11}
JM_DEAL_TYPE = {"rent": 2, "sale": 3}
JM_REGION = os.getenv("JOYMEE_REGION", "59")   # 59 = Toshkent shahri
JM_REPAIR = {1: "Ta'mir talab", 2: "Yaxshi holatda", 3: "Kosmetik", 4: "Yevroremont",
             5: "Dizaynerlik", 6: "Kapital"}
JM_REPAIR_RU = {"Ta'mir talab": "Требует ремонта", "Yaxshi holatda": "Хорошее состояние",
                "Kosmetik": "Косметический", "Yevroremont": "Евроремонт",
                "Dizaynerlik": "Дизайнерский", "Kapital": "Капитальный"}
REPAIR_UZ = {"евроремонт": "Yevroremont", "авторский проект": "Dizaynerlik", "средний": "O'rtacha",
             "требует ремонта": "Ta'mir talab", "черновая отделка": "Qora suvoq", "предчистовая отделка": "Oq suvoq",
             "косметический": "Kosmetik", "капитальный": "Kapital"}


def repair_text(ad, L):
    """Ta'mir nomini foydalanuvchi tiliga o'giradi (OLX ruscha, Joymee o'zbekcha beradi)."""
    r = repair_label(ad) or ""
    if not r:
        return ""
    if L == "ru":
        return JM_REPAIR_RU.get(r, r)
    return REPAIR_UZ.get(r.strip().lower(), r)


JM_HEADERS = {**HEADERS, "Origin": "https://joymee.uz", "Referer": "https://joymee.uz/",
              "Accept": "application/json"}


def jm_page(deal, ptype, page=1):
    p = {"deal_type": JM_DEAL_TYPE[deal], "category": JM_CATS[(deal, ptype)], "region": JM_REGION,
         "advertiser_type": 1, "ordering": "newest", "perPageTop": 0, "perPageRaised": 0,
         "perPagePlain": 40, "page": page}
    r = requests.get(f"{JM_API}/announcement/", params=p, headers=JM_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("results", [])


def jm_detail(ann_id):
    r = requests.get(f"{JM_API}/announcement/{ann_id}/", headers=JM_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def jm_to_ad(d, ptype):
    """Joymee e'lonini OLX ko'rinishiga keltiramiz, shunda filtr va xabar bir xil ishlaydi."""
    det = d.get("detail") or {}
    pr = d.get("pricing") or {}
    params = []
    try:
        params.append({"key": "price", "value": {
            "value": float(pr.get("price")), "currency": "UYE" if pr.get("currency") == 2 else "UZS"}})
    except (TypeError, ValueError):
        pass
    if det.get("room_quantity"):
        params.append({"key": "number_of_rooms", "value": {"label": str(det["room_quantity"])}})
    if det.get("area_m2"):
        params.append({"key": "total_area", "value": {"label": f"{float(det['area_m2']):g}"}})
    if det.get("floor_number"):
        params.append({"key": "floor", "value": {"label": str(det["floor_number"])}})
    if det.get("floors_count"):
        params.append({"key": "total_floors", "value": {"label": str(det["floors_count"])}})
    if det.get("repair") in JM_REPAIR:
        params.append({"key": "repairs", "name": "Ремонт", "value": {"label": JM_REPAIR[det["repair"]]}})
    loc = d.get("location") or {}
    seller = d.get("seller") or {}
    media = sorted(d.get("media") or [], key=lambda m: m.get("order") or 0)
    return {
        "source": "joymee", "ptype": ptype,
        "id": f"jm:{d['id']}",
        "url": f"https://joymee.uz/announcements/{d['id']}",
        "title": d.get("title") or "",
        "created_time": d.get("ads_at"),
        "phone": d.get("phone_number"),
        "seller_name": " ".join(filter(None, [seller.get("first_name"), seller.get("username")])),
        "description": (d.get("description") or "").replace("\n", "<br />\n"),
        "business": d.get("advertiser_type") == 2,
        "user": {"id": seller.get("id")},
        "params": params,
        "location": {"region": d.get("region") or {}, "district": d.get("district") or {}},
        "map": {"lat": loc.get("latitude"), "lon": loc.get("longitude")},
        "photos": [{"link": (m.get("file") or {}).get("url")} for m in media],
    }


# ======================= E'LON MA'LUMOTLARI =======================

def ad_text(ad):
    return f"{ad.get('title', '')} {ad.get('description', '')}".lower()


def param(ad, *keys):
    for p in ad.get("params", []):
        if p.get("key") in keys:
            v = p.get("value") or {}
            return v.get("label") or v.get("value")
    return None


def repair_label(ad):
    for p in ad.get("params", []):
        key = str(p.get("key", "")).lower()
        name = str(p.get("name", "")).lower()
        if "repair" in key or "remont" in key or "ремонт" in name or "ta'mir" in name:
            v = p.get("value") or {}
            return v.get("label") or v.get("key")
    return None


def rooms_count(ad):
    v = param(ad, "number_of_rooms_string", "number_of_rooms", "rooms")
    m = re.search(r"\d+", str(v or ""))
    if m:
        return int(m.group())
    m = re.search(r"(\d+)\s*(xona|комн|-к)", ad_text(ad))
    return int(m.group(1)) if m else None


_rate = {"v": None, "ts": 0}


def usd_rate():
    if _rate["v"] and time.time() - _rate["ts"] < 6 * 3600:
        return _rate["v"]
    try:
        r = requests.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=15)
        _rate["v"] = float(r.json()[0]["Rate"])
        _rate["ts"] = time.time()
    except Exception as e:
        log.warning("Kurs olinmadi: %s", e)
    return _rate["v"]


def price_value(ad):
    for p in ad.get("params", []):
        if p.get("key") == "price":
            return p.get("value") or {}
    return {}


def price_usd(ad):
    pv = price_value(ad)
    try:
        value = float(pv.get("value"))
    except (TypeError, ValueError):
        return None
    if str(pv.get("currency") or "").upper() in ("UYE", "USD"):
        return value
    conv, conv_cur = pv.get("converted_value"), str(pv.get("converted_currency") or "").upper()
    if conv and conv_cur in ("UYE", "USD"):
        return float(conv)
    rate = usd_rate()
    return value / rate if rate else None


def price_text(ad, L):
    pv = price_value(ad)
    if not pv:
        return t(L, "negotiable")
    cur = str(pv.get("currency") or "").upper()
    try:
        value = float(pv.get("value"))
    except (TypeError, ValueError):
        return pv.get("label") or t(L, "negotiable")
    if cur in ("UYE", "USD"):
        text = f"${fmt_num(value)}"
        conv = pv.get("converted_value")
        if conv and str(pv.get("converted_currency") or "").upper() == "UZS":
            text += f" (≈ {fmt_num(float(conv))} {t(L, 'sum')})"
        else:
            rate = usd_rate()
            if rate:
                text += f" (≈ {fmt_num(value * rate)} {t(L, 'sum')})"
    else:
        text = f"{fmt_num(value)} {t(L, 'sum')}"
        usd = price_usd(ad)
        if usd:
            text += f" (≈ ${fmt_num(usd)})"
    if pv.get("negotiable"):
        text += f", {t(L, 'negotiable')}"
    return text


# ======================= FILTRLAR =======================

def filters_match(ad, deal, s):
    """Foydalanuvchi filtri (rieltor tekshiruvisiz — u har e'lon uchun bir marta qilinadi)."""
    ptype = ad.get("ptype", "apt")
    if ad.get("source", "olx") not in s["sources"] or deal not in s["deals"] or ptype not in s["ptypes"]:
        return False
    if s["repairs"] and ptype != "land":
        if not repair_matches(ad, s["repairs"]):
            return False
    if s["rooms"] and ptype in ("apt", "house"):
        n = rooms_count(ad)
        if n is None or not any((n >= 4) if k == "4" else (n == int(k)) for k in s["rooms"]):
            return False
    if s["districts"]:
        loc = ad.get("location") or {}
        place = " ".join(str((loc.get(k) or {}).get("name", "")) for k in ("district", "city")).lower()
        if not any(w in place for k in s["districts"] for w in DISTRICT_WORDS[k]):
            return False
    lo, hi = s["price"][deal]
    if lo is not None or hi is not None:
        usd = price_usd(ad)
        if usd is None or (lo is not None and usd < lo) or (hi is not None and usd > hi):
            return False
    return True


def is_owner(ad):
    if "_owner" in ad:
        return ad["_owner"]
    ad["_owner"] = _is_owner(ad)
    return ad["_owner"]


def _is_owner(ad):
    if ad.get("business"):
        return False
    name = " ".join([str((ad.get("contact") or {}).get("name", "")),
                     str((ad.get("user") or {}).get("name", "")),
                     str(ad.get("seller_name", ""))]).lower()
    if any(w in name for w in NAME_AGENT_WORDS):
        return False
    text = ad_text(ad)
    agent_text = any(w in text for w in AGENT_WORDS) and not any(w in text for w in OWNER_WORDS)
    if ad.get("source") == "joymee":
        return not agent_text
    for p in ad.get("params", []):   # OLX'dagi "Комиссионные: Да" — rieltor
        if p.get("key") in ("comission", "commission") and \
                str((p.get("value") or {}).get("key", "")).lower() == "yes":
            return False
    if agent_text:
        return False
    return seller_ad_count((ad.get("user") or {}).get("id")) <= MAX_SELLER_ADS


# ======================= XABAR =======================

def _ts(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None


def posted_text(iso, L):
    dt = _ts(iso) if iso else None
    if not dt:
        return None
    dt = dt.astimezone(TZ)
    mins = int((datetime.now(TZ) - dt).total_seconds() // 60)
    if mins < 1:
        ago = t(L, "ago_now")
    elif mins < 60:
        ago = t(L, "ago_min", n=mins)
    elif mins < 24 * 60:
        ago = t(L, "ago_hour", n=mins // 60)
    else:
        ago = t(L, "ago_day", n=mins // 1440)
    return f"{dt:%d.%m.%Y, %H:%M} ({ago})"


ADDR_RE = re.compile(
    r"(?im)^(?:[^\w\n]*)("
    r"(?:адрес|manzil|address)\s*[:\-–]\s*.+|"
    r"(?:ул\.|улица|проспект|пр-т|массив|ж/м|квартал|mavze|ko['ʻ’`]?cha|kocha|tor\s?ko['ʻ’`]?cha)\s*.+|"
    r".+\s(?:ул\.|улица|ko['ʻ’`]?chasi|kochasi|mavzesi|kvartal|квартал|massivi)\b.*"
    r")$")
LANDMARK_RE = re.compile(r"(?im)(?:ориентир|orientir|mo['ʻ’`]?ljal)\s*[:\-–]?\s*([^\n]+)")


def address_from_text(desc):
    street = landmark = None
    m = ADDR_RE.search(desc)
    if m:
        street = re.sub(r"(?i)^(адрес|manzil|address)\s*[:\-–]\s*", "", m.group(1)).strip(" .,")
    m = LANDMARK_RE.search(desc)
    if m:
        landmark = m.group(1).strip(" .,")
    return (street[:120] if street else None), (landmark[:100] if landmark else None)


URL_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+|@[A-Za-z0-9_]{4,})")


OWNER_CLAIM_RE = re.compile(
    r"(?i)(от\s+собственника|от\s+хозяина|сда[её]т\s+собственник|без\s+посредник\w*(?:\s+и\s+комисси\w*)?|без\s+маклер\w*|"
    r"без\s+риелтор\w*|без\s+риэлтор\w*|uy\s+egasidan|egasidan|vositachisiz|maklersiz|bezmakler\w*|"
    r"без\s*маклер\w*|rieltorsiz|собственник)")


_LONG_NUM = re.compile(r"\+?\d(?:[\s\-()]*\d){8,}")
_CURRENCY_AFTER = re.compile(r"\s*(?:сум|so['ʻ’]?m|sum|\$|у\.?е|y\.?e|usd|долл|ming|млн|mln)", re.I)
_EMPTY_LABEL = re.compile(r"(?im)\b(tel|тел|телефон|telefon|telegram|телеграм|aloqa|murojaat|звоните|звонить)\b"
                          r"\s*[:.]?[\s,;]*(?=$|\n)")


def clean_for_channel(text):
    """Kanal uchun: uy egasining raqamlari, havolalari va 'uy egasidan' degan iboralarni olib tashlaymiz
    (aks holda o'quvchi kanal egasini uy egasi deb o'ylaydi)."""
    text = OWNER_CLAIM_RE.sub("", text)
    text = URL_RE.sub("", text)

    def drop_phone(m):   # 9+ raqamli son — telefon, agar orqasidan valyuta kelmasa (narx emas)
        return m.group() if _CURRENCY_AFTER.match(text, m.end()) else ""
    text = _LONG_NUM.sub(drop_phone, text)
    text = PHONE_RE.sub("", text)
    for _ in range(3):   # "Tel: , Telegram" kabi ketma-ket bo'sh yozuvlar
        text = _EMPTY_LABEL.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"(?m)^[\s,;:.!]+$", "", text)


HEADER_COUNT = 6
SAMPLE_HEADER = {"deal": "rent", "ptype": "apt", "rooms": 2, "district": {"uz": "Chilonzor", "ru": "Чиланзар"},
                 "price": "$450"}


def district_name(ad, L):
    """E'londagi tuman nomini foydalanuvchi tilida qaytaradi ('Чиланзарский район' -> 'Chilonzor')."""
    name = str(((ad.get("location") or {}).get("district") or {}).get("name", "")).lower()
    for k, words in DISTRICT_WORDS.items():
        if any(w in name for w in words):
            return DISTRICTS[k][L]
    return ""


def short_price(ad):
    usd = price_usd(ad)
    pv = price_value(ad)
    if str(pv.get("currency") or "").upper() in ("UYE", "USD") and usd:
        return f"${fmt_num(usd)}"
    try:
        return f"{fmt_num(float(pv.get('value')))} so'm"
    except (TypeError, ValueError):
        return ""


def build_header(n, L, deal, ptype, rooms=None, district="", price=""):
    """6 xil sarlavha andozasi. Bo'sh ma'lumotlar chiroyli tarzda tushirib qoldiriladi."""
    dl, pt = DEALS[deal][L], PTYPES[ptype][L]
    verb = t(L, f"verb_{deal}")
    pt_l = pt.lower() if L == "uz" else pt.lower()
    rooms_adj = (t(L, "rooms_adj", n=rooms) + " ") if rooms and ptype in ("apt", "house") else ""
    rooms_sh = t(L, "rooms_short", n=rooms) if rooms and ptype in ("apt", "house") else ""
    if n == 2:
        h = f"🔥 {t(L, 'new_caps')} {pt} {verb}"
    elif n == 3:
        h = f"📍 {district} — {pt_l} {verb}" if district else f"📍 {pt} {verb}"
    elif n == 4:
        h = f"🏡 {(rooms_adj + pt_l).strip().capitalize()}" + (f" · {price}" if price else "")
    elif n == 5:
        h = "🏙 " + " | ".join(x for x in (district or pt, rooms_sh, price) if x)
    elif n == 6:
        h = f"💎 {t(L, 'recommend')}: {rooms_adj}{pt_l} {verb}" + (f", {district}" if district else "")
    else:
        h = f"🏠 {dl} · {pt}"
    return h


def ad_header(ad, deal, L, n):
    return build_header(n, L, deal, ad.get("ptype", "apt"), rooms_count(ad), district_name(ad, L), short_price(ad))


TPL_COUNT = 7
TAGS = {"uz": {"rent": "#ijara", "sale": "#sotuv", "apt": "#kvartira", "house": "#hovli", "kom": "#tijorat", "land": "#yer"},
        "ru": {"rent": "#аренда", "sale": "#продажа", "apt": "#квартира", "house": "#дом", "kom": "#коммерция", "land": "#земля"}}


def tpl_name(L, n):
    return t(L, "tpl_names").split("|")[n - 1]


def ad_fields(ad, deal, L):
    """Kanal posti uchun e'lon ma'lumotlarini bir joyga yig'adi."""
    ptype = ad.get("ptype", "apt")
    loc = ad.get("location") or {}
    parts = [(loc.get(k) or {}).get("name") for k in ("region", "city", "district")]
    area = param(ad, "total_area", "area", "m", "land_area")
    area = (str(area) + ("" if re.search(r"[^\d\s.,]", str(area)) else " m²")) if area else ""
    rep_ = repair_text(ad, L)
    desc = re.sub(r"<[^>]+>", "", (ad.get("description") or "").replace("<br />", "\n"))
    desc = clean_for_channel(re.sub(r"\n\s*\n+", "\n", desc)).strip()
    street, landmark = address_from_text(desc)
    m = ad.get("map") or {}
    floor, floors = param(ad, "floor"), param(ad, "total_floors", "floors_in_building")
    return {
        "deal": deal, "ptype": ptype, "pt": PTYPES[ptype][L], "dl": DEALS[deal][L], "verb": t(L, f"verb_{deal}"),
        "title": clean_for_channel(ad.get("title", "")[:150]).strip(" -,.:") or PTYPES[ptype][L],
        "price": price_text(ad, L), "price_s": short_price(ad), "rooms": rooms_count(ad), "area": area,
        "floor": str(floor).strip() if floor else "", "floors": str(floors).strip() if floors else "",
        "repair": rep_, "district": district_name(ad, L),
        "address": ", ".join(dict.fromkeys(p for p in parts if p)) or t(L, "no_address"),
        "street": street or "", "landmark": landmark or "", "desc": desc,
        "map": f"https://maps.google.com/?q={m['lat']},{m['lon']}" if m.get("lat") and m.get("lon") else "",
    }


def fit_desc(head, tail, desc, limit=300):
    """Tavsifni Telegram izohi chegarasiga (1024) sig'diradi; teglar buzilmaydi."""
    room = min(limit, 1000 - len(head) - len(tail) - 2)
    if not desc or room <= 40:
        return ""
    part = desc[:room]
    piece = esc(part)
    while len(piece) > room and part:
        part = part[:-10]
        piece = esc(part)
    return piece + ("…" if len(part) < len(desc) else "")


def render_channel(ad, deal, L, phones, n):
    """6 xil to'liq post andozasi."""
    f = ad_fields(ad, deal, L)
    E = esc
    ph = ", ".join(E(p) for p in phones or [])
    flr = f"{f['floor']}/{f['floors']}" if f["floor"] and f["floors"] else f["floor"]
    rooms_adj = (t(L, "rooms_adj", n=f["rooms"]) + " ") if f["rooms"] and f["ptype"] in ("apt", "house") else ""
    rooms_sh = t(L, "rooms_short", n=f["rooms"]) if f["rooms"] and f["ptype"] in ("apt", "house") else ""
    mapl = f'<a href="{f["map"]}">{t(L, "map")}</a>' if f["map"] else ""
    d = f["district"]

    if n == 2:   # Ixcham — tavsifsiz, bir nechta qator
        head = "\n".join(x for x in [
            f"🔥 <b>{t(L, 'new_short')} {E((rooms_adj + f['pt'].lower()).strip().capitalize())} {f['verb']}</b>",
            " | ".join(x for x in [f"📍 {E(d)}" if d else "", f"🏢 {E(flr)}" if flr else "",
                                   f"📐 {E(f['area'])}" if f["area"] else "", f"🛠 {E(f['repair'])}" if f["repair"] else ""] if x),
            f"💵 <b>{E(f['price'])}</b>",
        ] if x)
        tail = f"\n\n📞 {ph}" if ph else ""
        return head + tail

    if n == 3:   # Heshteg
        tags = [TAGS[L][deal], TAGS[L][f["ptype"]]]
        if d:
            tags.append("#" + re.sub(r"[^\w]", "", d.lower()))
        if f["rooms"] and f["ptype"] in ("apt", "house"):
            tags.append(f"#{f['rooms']}" + ("xonali" if L == "uz" else "комнатная"))
        rows = [" ".join(tags), "",
                f"🏡 <b>{E((rooms_adj + f['pt'].lower()).strip().capitalize())}" + (f" — {E(d)}" if d else "") + "</b>", "",
                f"▫️ {t(L, 'price')}: <b>{E(f['price'])}</b>"]
        for lbl, v in (("area", f["area"]), ("floor", flr), ("repair", f["repair"]), ("street", f["street"])):
            if v:
                rows.append(f"▫️ {t(L, lbl)}: {E(v)}")
        head = "\n".join(rows)
        tail = f"\n\n☎️ {t(L, 'c_aloqa')}: {ph}" if ph else ""
        desc = fit_desc(head, tail, f["desc"], 200)
        return head + (f"\n\n📝 {desc}" if desc else "") + tail

    if n == 4:   # Blok (iqtibos)
        q = [f"💰 <b>{E(f['price'])}</b>"]
        line2 = " · ".join(x for x in [f"🚪 {E(rooms_sh)}" if rooms_sh else "", f"📐 {E(f['area'])}" if f["area"] else "",
                                       f"🏢 {E(flr)}" if flr else ""] if x)
        if line2:
            q.append(line2)
        if f["repair"]:
            q.append(f"🛠 {E(f['repair'])}")
        if f["street"] or f["landmark"]:
            q.append("🏘 " + E(", ".join(x for x in (f["street"], f["landmark"]) if x)))
        head = (f"<b>📍 {E(d) + ' — ' if d else ''}{E(f['pt'].lower() if d else f['pt'])} {f['verb']}</b>\n\n"
                f"<blockquote>" + "\n".join(q) + "</blockquote>" + (f"\n🗺 {mapl}" if mapl else ""))
        tail = f"\n\n📲 <b>{t(L, 'c_bog')}:</b> {ph}" if ph else ""
        desc = fit_desc(head, tail, f["desc"], 250)
        return head + (f"\n\n{desc}" if desc else "") + tail

    if n == 5:   # Jadval
        line = "━━━━━━━━━━━━━━"
        top = " | ".join(x for x in (d or f["pt"], rooms_sh, f["price_s"]) if x)
        rows = [line, f"🏙 <b>{E(top)}</b>", line]
        for lbl, v in (("price", f["price"]), ("rooms", str(f["rooms"]) if rooms_sh else ""), ("area", f["area"]),
                       ("floor", flr), ("repair", f["repair"]), ("address", f["address"]), ("street", f["street"]),
                       ("landmark", f["landmark"])):
            if v:
                rows.append(f"<b>{t(L, lbl)}:</b> {E(v)}")
        rows.append(line)
        head = "\n".join(rows)
        tail = f"\n📞 {ph}" if ph else ""
        return head + tail

    if n == 6:   # Tavsiya
        rows = [f"💎 <b>{t(L, 'recommend')}!</b>",
                f"✨ {E((rooms_adj + f['pt'].lower()).strip().capitalize())} {f['verb']}" + (f", {E(d)}" if d else ""), ""]
        for v in (f["repair"], f["area"] + (f", {t(L, 'floor_n', n=f['floor'])}" if f["floor"] else "") if f["area"] or f["floor"] else "",
                  f"{t(L, 'price')}: {f['price']}"):
            if v:
                rows.append(f"✅ {E(v.strip(', '))}")
        if mapl:
            rows.append(f"🗺 {mapl}")
        head = "\n".join(rows)
        tail = f"\n\n👉 <b>{t(L, 'c_view')}:</b>\n" + "\n".join(E(p) for p in phones) if phones else ""
        desc = fit_desc(head, tail, f["desc"], 220)
        return head + (f"\n\n<i>{desc}</i>" if desc else "") + tail

    if n == 7:   # Ramka — barcha ma'lumot rangli ramka (blockquote) ichida
        q = []
        for emo, lbl, v in (("📍", "district_l", d), ("💰", "price", f["price"]),
                            ("🚪", "rooms", str(f["rooms"]) if rooms_sh else ""), ("📐", "area", f["area"]),
                            ("🏢", "floor", flr), ("🛠", "repair", f["repair"]), ("🏘", "street", f["street"]),
                            ("🎯", "landmark", f["landmark"])):
            if v:
                q.append(f"{emo} <b>{t(L, lbl)}:</b> {E(v)}")
        head = (f"🏠 <b>{E((rooms_adj + f['pt'].lower()).strip().capitalize())} {f['verb']}</b>\n"
                "<blockquote>" + "\n".join(q) + "</blockquote>" + (f"\n🗺 {mapl}" if mapl else ""))
        tail = f"\n\n📞 <b>{t(L, 'contact')}:</b> {ph}" if ph else ""
        desc = fit_desc(head, tail, f["desc"], 250)
        return head + (f"\n\n{desc}" if desc else "") + tail

    # 1 — Klassik
    rows = [f"🏠 <b>{f['dl']} · {f['pt']}</b>", "", f"<b>{E(f['title'])}</b>", "", f"💰 <b>{t(L, 'price')}:</b> {E(f['price'])}"]
    if f["rooms"]:
        rows.append(f"🚪 <b>{t(L, 'rooms')}:</b> {f['rooms']}")
    for emo, lbl, v in (("📐", "area", f["area"]), ("🏢", "floor", flr), ("🛠", "repair", f["repair"]),
                        ("📍", "address", f["address"]), ("🏘", "street", f["street"]), ("🎯", "landmark", f["landmark"])):
        if v:
            rows.append(f"{emo} <b>{t(L, lbl)}:</b> {E(v)}")
    if mapl:
        rows.append(f"🗺 {mapl}")
    head = "\n".join(rows)
    tail = f"\n\n📞 <b>{t(L, 'contact')}:</b> {ph}" if ph else ""
    desc = fit_desc(head, tail, f["desc"])
    return head + (f"\n\n{desc}" if desc else "") + tail


def format_ad(ad, deal, L, channel=False, channel_phones=None, header=1):
    if channel:
        return render_channel(ad, deal, L, channel_phones, header)
    loc = ad.get("location") or {}
    parts = [(loc.get(k) or {}).get("name") for k in ("region", "city", "district")]
    address = ", ".join(dict.fromkeys(p for p in parts if p)) or t(L, "no_address")
    area = param(ad, "total_area", "area", "m", "land_area")
    floor = param(ad, "floor")
    floors = param(ad, "total_floors", "floors_in_building")
    rooms = rooms_count(ad)
    rep = repair_text(ad, L)
    src = SOURCES[ad.get("source", "olx")][L]
    ptype = ad.get("ptype", "apt")
    posted = posted_text(ad.get("created_time"), L)

    title = ad.get("title", "")[:150]
    if channel:
        title = clean_for_channel(title).strip(" -,.") or PTYPES[ptype][L]
        lines = [f"<b>{esc(ad_header(ad, deal, L, header))}</b>", "",
                 f"<b>{esc(title)}</b>", "",
                 f"💰 <b>{t(L, 'price')}:</b> {esc(price_text(ad, L))}"]
    else:
        lines = [f"🏠 <b>{t(L, 'new_ad', src=src)}</b> ({DEALS[deal][L]} · {PTYPES[ptype][L]})", "",
                 f"<b>{esc(title)}</b>", "",
                 f"💰 <b>{t(L, 'price')}:</b> {esc(price_text(ad, L))}"]
    if posted and not channel:
        lines.append(f"🕒 <b>{t(L, 'posted')}:</b> {posted}")
    if SHOW_SELLER_PHONE and not channel:
        lines.append(f"📞 <b>{t(L, 'phone')}:</b> {esc(ad.get('phone_text') or t(L, 'see_ad'))}")
    if rooms:
        lines.append(f"🚪 <b>{t(L, 'rooms')}:</b> {rooms}")
    if area:
        a = str(area)
        unit = "" if re.search(r"[^\d\s.,]", a) else " m²"
        lines.append(f"📐 <b>{t(L, 'area')}:</b> {esc(a)}{unit}")
    if floor:
        lines.append(f"🏢 <b>{t(L, 'floor')}:</b> {esc(floor)}" + (f" / {esc(floors)}" if floors else ""))
    if rep:
        lines.append(f"🛠 <b>{t(L, 'repair')}:</b> {esc(rep)}")
    lines.append(f"📍 <b>{t(L, 'address')}:</b> {esc(address)}")

    desc = re.sub(r"<[^>]+>", "", (ad.get("description") or "").replace("<br />", "\n"))
    desc = re.sub(r"\n\s*\n+", "\n", desc).strip()
    if channel:
        desc = clean_for_channel(desc).strip()
    street, landmark = address_from_text(desc)
    if street:
        lines.append(f"🏘 <b>{t(L, 'street')}:</b> {esc(street)}")
    if landmark:
        lines.append(f"🎯 <b>{t(L, 'landmark')}:</b> {esc(landmark)}")
    m = ad.get("map") or {}
    if m.get("lat") and m.get("lon"):
        lines.append(f'🗺 <a href="https://maps.google.com/?q={m["lat"]},{m["lon"]}">{t(L, "map")}</a>')

    if channel:
        phones = channel_phones or []
        tail = ("\n\n📞 <b>" + t(L, "contact") + ":</b> " + ", ".join(esc(p) for p in phones)) if phones else ""
    else:
        tail = f'\n\n🔗 <a href="{ad.get("url")}">{t(L, "open")}</a>'
    head = "\n".join(lines)
    room = min(300, 1000 - len(head) - len(tail) - 2)   # Telegram izohi 1024 belgigacha
    if desc and room > 40:
        part = desc[:room]
        piece = esc(part)
        while len(piece) > room and part:
            part = part[:-10]
            piece = esc(part)
        head += "\n\n" + piece + ("…" if len(part) < len(desc) else "")
    return head + tail


def photos(ad):
    out = []
    for p in ad.get("photos", [])[:10]:
        link = p.get("link") if isinstance(p, dict) else p
        if link:
            out.append(link.replace("{width}", "1000").replace("{height}", "750"))
    return out


PHONE_RE = re.compile(r"(?:\+?998[\s\-()]*)?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


def fmt_phone(raw):
    d = re.sub(r"\D", "", str(raw))
    if len(d) == 9:
        d = "998" + d
    if len(d) == 12 and d.startswith("998"):
        return f"+998 {d[3:5]} {d[5:8]} {d[8:10]} {d[10:12]}"
    return str(raw).strip()


def get_phone(ad):
    if ad.get("phone"):
        return fmt_phone(ad["phone"])
    if ad.get("source") != "joymee":
        try:
            r = requests.get(f"{API}/offers/{ad['id']}/limited-phones/", headers=HEADERS, proxies=OLX_PROXIES, timeout=15)
            if r.ok:
                phones = (r.json().get("data") or {}).get("phones") or []
                if phones:
                    return ", ".join(fmt_phone(p) for p in phones[:2])
            else:
                log.info("OLX telefon %s: %s", ad["id"], r.status_code)
        except Exception as e:
            log.info("OLX telefon xato: %s", e)
    desc = re.sub(r"<[^>]+>", " ", ad.get("description") or "")
    m = PHONE_RE.search(desc)
    return fmt_phone(m.group()) if m else None


def send_ad(ad, deal, u):
    chat_id, L = u["chat_id"], u["lang"]
    channel = is_channel(u)
    if SHOW_SELLER_PHONE and not channel and "phone_text" not in ad:
        ad["phone_text"] = get_phone(ad)
    caption = format_ad(ad, deal, L, channel=channel,
                        channel_phones=u["s"].get("phones") if channel else None,
                        header=int(u["s"].get("header") or 1))
    pics = photos(ad)
    pub_kb = None
    if not channel and channels_of(chat_id):
        # "Kanalga joylash" tugmasi uchun e'lonni saqlab qo'yamiz
        db.execute("INSERT OR REPLACE INTO ad_cache VALUES (?,?,?,?)",
                   (str(ad["id"]), deal, json.dumps(ad, ensure_ascii=False, default=str), int(time.time())))
        db.commit()
        pub_kb = {"inline_keyboard": [[{**btn(t(L, "b_publish"), f"pub:{ad['id']}"), "style": "primary"}]]}
    r = None
    album = False
    if len(pics) >= 2:
        media = [{"type": "photo", "media": p} for p in pics]
        media[0].update(caption=caption, parse_mode="HTML")
        r = tg("sendMediaGroup", chat_id=chat_id, media=media)
        album = r is not None and r.ok
    extra = {"reply_markup": pub_kb} if pub_kb else {}
    if (r is None or not r.ok) and pics:
        r = tg("sendPhoto", chat_id=chat_id, photo=pics[0], caption=caption, parse_mode="HTML", **extra)
    if r is None or not r.ok:
        r = tg("sendMessage", chat_id=chat_id, text=caption, parse_mode="HTML",
               disable_web_page_preview=True, **extra)
    if r is not None and r.ok:
        mark_sent(chat_id, ad["id"])
        if not channel:
            with _menu_due_lock:
                _menu_due.add(str(chat_id))
        if album and pub_kb:
            # albomga tugma biriktirib bo'lmaydi — ostiga kichik xabar bilan qo'yamiz
            try:
                first_id = r.json()["result"][0]["message_id"]
            except Exception:
                first_id = None
            tg("sendMessage", chat_id=chat_id, text=t(L, "pub_hint"), reply_markup=pub_kb,
               **({"reply_to_message_id": first_id} if first_id else {}))
        return True
    if channel and r is not None and r.status_code in (400, 403):
        channel_lost(u, r)
    return False


def channel_lost(u, r):
    """Bot kanaldan chiqarilgan yoki ruxsati olingan: kanalni to'xtatamiz va egasiga xabar beramiz."""
    try:
        desc = (r.json().get("description") or "").lower()
    except Exception:
        desc = ""
    if r.status_code == 400 and not any(w in desc for w in ("not found", "rights", "not enough", "kicked",
                                                             "not a member", "forbidden")):
        return   # boshqa xato (masalan rasm) — kanalni to'xtatmaymiz
    with ulock:
        c = get_user(u["chat_id"])
        if not c or c["s"]["paused"]:
            return
        c["s"]["paused"] = True
        set_user(u["chat_id"], s=c["s"])
    owner = get_user(c["s"].get("owner"))
    log.warning("Kanal %s ga yuborib bo'lmadi (%s) — to'xtatildi", u["chat_id"], desc)
    if owner:
        tg("sendMessage", chat_id=owner["chat_id"], text=t(owner["lang"], "ch_lost", title=c["s"].get("title", "")))


# ======================= KUZATUV (barcha foydalanuvchilar uchun) =======================

def distribute(ad, deal, users):
    """Yangi e'lonni filtri mos kelgan foydalanuvchilarga yuboradi."""
    targets = [u for u in users if filters_match(ad, deal, u["s"]) and not was_sent(u["chat_id"], ad["id"])]
    if not targets or not is_owner(ad):
        return 0
    n = 0
    for u in targets:
        if send_ad(ad, deal, u):
            n += 1
        time.sleep(3 if is_channel(u) else 0.1)   # kanal uchun Telegram cheklovi qattiqroq
    log.info("Yangi (%s): %s -> %s ta foydalanuvchi", ad.get("source", "olx"), ad.get("title", "")[:50], n)
    return n


def check_olx(deal, ptype, users):
    ads = fetch_offers(deal, ptype)
    pkey = deal if ptype == "apt" else f"{deal}:{ptype}"
    if not db.execute("SELECT 1 FROM primed WHERE deal=?", (pkey,)).fetchone():
        for ad in ads:
            mark_seen(ad["id"])
        db.execute("INSERT INTO primed VALUES (?)", (pkey,))
        db.commit()
        log.info("OLX %s: eski e'lonlar saqlandi, endi faqat yangilari keladi", pkey)
        return
    for ad in reversed(ads):
        if is_seen(ad["id"]):
            continue
        mark_seen(ad["id"])
        distribute(ad, deal, users)


def check_joymee(deal, ptype, users):
    items = jm_page(deal, ptype)
    key = f"jm:{deal}" if ptype == "apt" else f"jm:{deal}:{ptype}"
    if not db.execute("SELECT 1 FROM primed WHERE deal=?", (key,)).fetchone():
        for it in items:
            mark_seen(f"jm:{it['id']}")
        db.execute("INSERT INTO primed VALUES (?)", (key,))
        db.commit()
        log.info("Joymee %s: eski e'lonlar saqlandi, endi faqat yangilari keladi", key)
        return
    for it in reversed(items):
        sid = f"jm:{it['id']}"
        if is_seen(sid):
            continue
        mark_seen(sid)
        try:
            ad = jm_to_ad(jm_detail(it["id"]), ptype)
        except Exception as e:
            log.warning("Joymee e'lon %s xato: %s", it["id"], e)
            continue
        distribute(ad, deal, users)
        time.sleep(1)


_cleanup = {"ts": 0}


def cleanup_db():
    """Kuniga bir marta eski yozuvlarni o'chiradi, baza cheksiz kattalashmasin."""
    if time.time() - _cleanup["ts"] < 86400:
        return
    _cleanup["ts"] = time.time()
    now = int(time.time())
    db.execute("DELETE FROM sent WHERE ts < ?", (now - 60 * 86400,))
    db.execute("DELETE FROM seen WHERE ts < ?", (now - 365 * 86400,))
    db.execute("DELETE FROM ad_cache WHERE ts < ?", (now - 30 * 86400,))
    db.commit()


_olx_state = {"fail_since": 0, "alerted": False}


def olx_health(ok):
    """Ko'prik uzilsa (10 daqiqadan ko'p OLX ishlamasa) adminga bir marta xabar beradi."""
    if not OLX_PROXY or not ADMIN_ID:
        return
    st = _olx_state
    if ok:
        if st["alerted"]:
            tg("sendMessage", chat_id=ADMIN_ID, text="✅ OLX ko'prigi tiklandi, OLX e'lonlari yana kelmoqda.")
        st.update(fail_since=0, alerted=False)
        return
    if not st["fail_since"]:
        st["fail_since"] = time.time()
    elif not st["alerted"] and time.time() - st["fail_since"] > 600:
        st["alerted"] = True
        tg("sendMessage", chat_id=ADMIN_ID, text=(
            "⚠️ OLX ko'prigi 10 daqiqadan beri ishlamayapti — OLX e'lonlari kelmayapti.\n"
            "Uydagi kompyuter yoqilganini, internetga ulanganini va «OLX ko'prigi» oynasi ochiqligini tekshiring.\n"
            "Joymee va bot menyusi ishlashda davom etmoqda."))


def monitor_once():
    try:
        cleanup_db()
    except Exception as e:
        log.warning("Tozalash xato: %s", e)
    try:
        check_subscriptions()
    except Exception as e:
        log.warning("Obuna tekshiruvi xato: %s", e)
    users = active_users()
    combos = sorted({(src, deal, pt) for u in users for src in u["s"]["sources"]
                     for deal in u["s"]["deals"] for pt in u["s"]["ptypes"]})
    olx_ok = None
    for src, deal, ptype in combos:
        try:
            (check_olx if src == "olx" else check_joymee)(deal, ptype, users)
            if src == "olx":
                olx_ok = True
        except Exception as e:
            log.warning("%s xato (%s/%s): %s", src, deal, ptype, e)
            if src == "olx" and olx_ok is None:
                olx_ok = False
    if olx_ok is not None:
        olx_health(olx_ok)
        time.sleep(4)
    try:
        menu_after_ads()
    except Exception as e:
        log.warning("Menyu xato: %s", e)


# ======================= OXIRGI E'LONLAR (/oxirgi, /on_kun) =======================

search_lock = threading.Lock()


def _jm_quick_ok(it, deal, s):
    """Joymee ro'yxatidagi qisqa ma'lumot bo'yicha tez saralash (batafsil so'rovdan oldin)."""
    if s["districts"]:
        place = (it.get("address_line") or "").lower()
        if not any(w in place for k in s["districts"] for w in DISTRICT_WORDS[k]):
            return False
    lo, hi = s["price"][deal]
    if lo is not None or hi is not None:
        pr = it.get("pricing") or {}
        try:
            v = float(pr.get("price"))
        except (TypeError, ValueError):
            return True
        rate = usd_rate()
        usd = v if pr.get("currency") == 2 else (v / rate if rate else None)
        if usd is not None and ((lo is not None and usd < lo) or (hi is not None and usd > hi)):
            return False
    return True


def latest_ads(u, days):
    s, cid = u["s"], u["chat_id"]
    cutoff = datetime.now(TZ) - timedelta(days=days)
    found, errors, scanned = [], [], 0
    for deal in s["deals"]:
        for ptype in s["ptypes"]:
            if "olx" in s["sources"]:
                try:
                    params = dict(api_params(deal, ptype))
                    for page in range(min(25, 4 + days * 2)):
                        params["offset"] = page * 40
                        r = requests.get(f"{API}/offers/", params=params, headers=HEADERS, proxies=OLX_PROXIES, timeout=20)
                        r.raise_for_status()
                        ads = r.json().get("data", [])
                        scanned += len(ads)
                        if not ads:
                            break
                        for ad in ads:   # ro'yxat sana bo'yicha aralash, shuning uchun hammasini ko'ramiz
                            tt = _ts(ad.get("created_time"))
                            if (tt and tt < cutoff) or was_sent(cid, ad["id"]):
                                continue
                            ad["ptype"] = ptype
                            if filters_match(ad, deal, s) and is_owner(ad):
                                found.append((ad.get("created_time") or "", deal, ad))
                        time.sleep(1)
                except Exception as e:
                    log.exception("Oxirgi (OLX) xato: %s", e)
                    errors.append(f"OLX: {e}")
            if "joymee" in s["sources"]:
                try:
                    details = 0
                    for page in range(1, min(16, 3 + days)):
                        items = jm_page(deal, ptype, page)
                        scanned += len(items)
                        if not items:
                            break
                        for it in items:
                            tt = _ts(it.get("ads_at"))
                            if (tt and tt < cutoff) or was_sent(cid, f"jm:{it['id']}"):
                                continue
                            if not _jm_quick_ok(it, deal, s) or details >= 80:
                                continue
                            details += 1
                            ad = jm_to_ad(jm_detail(it["id"]), ptype)
                            if filters_match(ad, deal, s) and is_owner(ad):
                                found.append((it.get("ads_at") or "", deal, ad))
                except Exception as e:
                    log.exception("Oxirgi (Joymee) xato: %s", e)
                    errors.append(f"Joymee: {e}")
    uniq, ids = [], set()
    for item in found:
        if item[2]["id"] not in ids:
            ids.add(item[2]["id"])
            uniq.append(item)
    uniq.sort(key=lambda x: _ts(x[0]) or cutoff, reverse=True)
    log.info("Oxirgi %s kun (%s): %s ko'rildi, %s mos, xatolar: %s", days, cid, scanned, len(uniq), errors)
    return uniq[:LATEST_N], errors


def send_latest(chat_id, days):
    u = get_user(chat_id)
    if not registered(u):
        return
    L = u["lang"]
    if not has_access(u):
        tg("sendMessage", chat_id=chat_id, text=t(L, "need_sub"))
        sub_page(u)
        return
    if not search_lock.acquire(blocking=False):
        tg("sendMessage", chat_id=chat_id, text=t(L, "busy"))
        return
    try:
        label = t(L, "lbl_1") if days == 1 else t(L, "lbl_n", d=days)
        when = t(L, "when_1") if days == 1 else t(L, "when_n", d=days)
        tg("sendMessage", chat_id=chat_id,
           text=t(L, "searching", label=label, wait=t(L, "wait_1" if days == 1 else "wait_n")))
        found, errors = latest_ads(u, days)
        if errors:
            tg("sendMessage", chat_id=chat_id, text=t(L, "search_err") + "\n" + "\n".join(errors)[:1000])
        if not found:
            tg("sendMessage", chat_id=chat_id, text=t(L, "none", when=when))
            send_main(u)
            return
        for _, deal, ad in reversed(found):   # eng yangisi eng pastda
            send_ad(ad, deal, u)
            time.sleep(1.5)
        menu_after_ads([str(chat_id)])
    except Exception as e:
        log.exception("send_latest xato")
        tg("sendMessage", chat_id=chat_id, text=f"{t(L, 'search_err')} {e}")
    finally:
        search_lock.release()


# ======================= ISHGA TUSHIRISH =======================

PID_FILE = "bot.pid"


def kill_old_instance():
    """Avvalgi nusxa hali ishlayotgan bo'lsa, uni to'xtatamiz (ikki nusxa bo'lmasin)."""
    try:
        with open(PID_FILE) as f:
            old = int(f.read().strip())
    except Exception:
        old = None
    if old and old != os.getpid():
        try:
            if os.name == "nt":
                out = subprocess.run(["tasklist", "/FI", f"PID eq {old}", "/FO", "CSV", "/NH"],
                                     capture_output=True, text=True).stdout.lower()
                if "python" in out:
                    subprocess.run(["taskkill", "/PID", str(old), "/F"], capture_output=True)
                    log.info("Eski nusxa (PID %s) to'xtatildi", old)
            else:
                os.kill(old, 15)
                log.info("Eski nusxa (PID %s) to'xtatildi", old)
            time.sleep(2)
        except Exception:
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def main():
    if not BOT_TOKEN:
        raise SystemExit(".env faylida BOT_TOKEN ni to'ldiring")
    global BOT_USERNAME
    kill_old_instance()
    init_db()
    r = tg("getMe")
    if r is not None and r.ok:
        BOT_USERNAME = r.json()["result"].get("username") or BOT_USERNAME
    ensure_channel()
    if os.path.exists("restart_chat.txt"):
        with open("restart_chat.txt") as f:
            rc = f.read().strip()
        os.remove("restart_chat.txt")
        tg("sendMessage", chat_id=rc, text="✅ Bot qayta ishga tushdi.")
    threading.Thread(target=telegram_loop, daemon=True).start()
    log.info("Bot ishga tushdi (ko'p foydalanuvchili).")
    while True:
        monitor_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
