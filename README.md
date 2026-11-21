# Uy Savat bot (@UySavat_bot)

OLX.uz va Joymee.uz'dagi uy egalarining yangi e'lonlarini kuzatadi va foydalanuvchilarga
Telegramda rasmlari, narxi, telefoni va manzili bilan yuboradi.

## Ishga tushirish (Windows)

```powershell
cd E:\project\uy-bot
pip install requests python-dotenv
.\start.bat
```

Botni doim `.\start.bat` orqali ishga tushiring. Shunda Telegramdagi /restart ishlaydi.
To'xtatish: Ctrl+C, keyin "Terminate batch job (Y/N)?" ga Y.

## .env sozlamalari

| Nomi | Ma'nosi |
|---|---|
| BOT_TOKEN | @BotFather bergan token |
| ADMIN_ID | Sizning Telegram ID'ingiz (admin buyruqlari: /restart, /stats). Bo'sh bo'lsa CHAT_ID olinadi |
| CITY | OLX shahri (standart: tashkent) |
| INTERVAL_SECONDS | Tekshirish oralig'i, soniya (standart: 240) |
| MAX_SELLER_ADS | Sotuvchida bundan ko'p e'lon bo'lsa — rieltor (standart: 4) |
| LATEST_N | /oxirgi va /on_kun nechta e'lon yuborsin (standart: 5) |
| LATEST_DAYS | /on_kun necha kunlik qidirsin (standart: 10) |
| SHOW_SELLER_PHONE | 1 — sotuvchi telefonini ko'rsatish, 0 — ko'rsatmaslik |

## Foydalanuvchi uchun

1. /start → til tanlash (O'zbekcha / Русский)
2. "Raqamni yuborish" tugmasi orqali telefon raqamini yuborish (ro'yxatdan o'tish)
3. /filtr — saytlar, ijara/sotuv, mulk turi, ta'mir, xonalar, tumanlar, narx
4. /oxirgi — oxirgi 24 soatlik e'lonlar, /on_kun — oxirgi 10 kunlik, /til — tilni almashtirish

Har bir foydalanuvchining filtri va yuborilgan e'lonlari alohida saqlanadi (seen.db).
Bitta e'lon bitta foydalanuvchiga faqat bir marta yuboriladi.

## Admin buyruqlari
- /restart — botni qayta ishga tushirish
- /stats — foydalanuvchilar soni
