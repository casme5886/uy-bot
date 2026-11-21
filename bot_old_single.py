"""
OLX uy e'lonlari kuzatuvchi bot.
Yangi e'lon chiqsa Telegramga rasmlari, narxi, maydoni, ta'miri va manzili bilan yuboradi.
Faqat uy egasidan (xususiy shaxs) bo'lgan e'lonlar.
Filtrlar botning o'zida tugmalar orqali sozlanadi: /start yoki /filtr
"""
import os
import re
import json
import time
import html
import sqlite3
import logging
import threading
import subprocess
import sys

from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")                    # e'lonlar shu yerga keladi
ADMIN_ID = os.getenv("ADMIN_ID") or CHAT_ID       # filtrni faqat shu odam o'zgartira oladi
CITY = os.getenv("CITY", "tashkent")              # OLX havolasidagi shahar nomi
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "240"))
MAX_SELLER_ADS = int(os.getenv("MAX_SELLER_ADS", "4"))

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
API = "https://www.olx.uz/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "ru,uz;q=0.9"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("bot.log", encoding="utf-8")])
log = logging.getLogger("bot")

# ======================= FILTR VARIANTLARI =======================

DEALS = {"rent": ("Ijara",), "sale": ("Sotuv",)}

PTYPES = {"apt": "Kvartira", "house": "Hovli/dacha", "kom": "Tijorat binolari", "land": "Yer"}

# OLX bo'limlari: (turi, mulk) -> sahifa yo'li
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

REPAIRS = {
    "evro":  ("Evroremont",   ["евроремонт", "евро ремонт", "evroremont", "evro remont", "yevroremont"]),
    "dizn":  ("Dizaynerlik",  ["авторск", "дизайнер", "dizayner", "dizaynerlik"]),
    "orta":  ("O'rtacha",     ["средний", "o'rtacha", "ortacha", "kosmetik", "yaxshi holatda"]),
    "talab": ("Ta'mir talab", ["требует ремонта", "ta'mir talab", "tamir talab"]),
    "qora":  ("Qora suvoq / korobka", ["черновая", "предчистов", "коробка", "korobka", "qora suvoq"]),
}

ROOMS = {"1": "1", "2": "2", "3": "3", "4": "4+"}

SOURCES = {"olx": "OLX", "joymee": "Joymee"}

DISTRICTS = {
    "bektemir": ("Bektemir", ["бектемир", "bektemir"]),
    "chilonzor": ("Chilonzor", ["чиланзар", "chilonzor"]),
    "mirobod": ("Mirobod", ["мирабад", "mirobod"]),
    "mirzo": ("Mirzo Ulug'bek", ["улугбек", "ulug'bek", "ulugbek", "ulug‘bek", "ulug’bek"]),
    "olmazor": ("Olmazor", ["алмазар", "olmazor"]),
    "sergeli": ("Sergeli", ["сергели", "sergeli"]),
    "shayx": ("Shayxontohur", ["шайхантахур", "shayxontohur", "shayxontoxur"]),
    "uchtepa": ("Uchtepa", ["учтепин", "uchtepa"]),
    "yakka": ("Yakkasaroy", ["яккасарай", "yakkasaroy"]),
    "yashnobod": ("Yashnobod", ["яшнабад", "yashnobod"]),
    "yunusobod": ("Yunusobod", ["юнусабад", "yunusobod"]),
    "yangihayot": ("Yangihayot", ["янгихаёт", "yangihayot"]),
}

AGENT_WORDS = ["риелтор", "риэлтор", "агентств", "комисси", "rieltor", "agentlik",
               "komissiya", "услуги агента"]
OWNER_WORDS = ["vositachisiz", "без посредников", "от хозяина", "от собственника",
               "uy egasidan"]

# ======================= SOZLAMALAR (settings.json) =======================

SETTINGS_FILE = "settings.json"
DEFAULT = {"sources": ["olx", "joymee"], "deals": ["rent", "sale"], "ptypes": ["apt"], "repairs": [], "rooms": [], "districts": [],
           "price": {"rent": [None, None], "sale": [None, None]}, "paused": False}
lock = threading.Lock()


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
        return {**DEFAULT, **s}
    except Exception:
        return json.loads(json.dumps(DEFAULT))


S = load_settings()
awaiting = {}  # chat_id -> "rent" / "sale" (narx kiritishni kutyapmiz)


def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False, indent=2)


# ======================= TELEGRAM =======================

def esc(x):
    return html.escape(str(x).strip(), quote=False)


def tg(method, **data):
    try:
        r = requests.post(f"{TG}/{method}", json=data, timeout=40)
        if not r.ok:
            log.warning("Telegram xato (%s): %s", method, r.text[:200])
        return r
    except Exception as e:
        log.warning("Telegram ulanish xato: %s", e)
        return None


def btn(text, data):
    return {"text": text, "callback_data": data}


def mark(on):
    return "✅ " if on else "▫️ "


def fmt_num(n):
    return f"{n:,.0f}".replace(",", " ")


def price_str(rng):
    lo, hi = rng
    if lo is None and hi is None:
        return "farqi yo'q"
    if lo is None:
        return f"${fmt_num(hi)} gacha"
    if hi is None:
        return f"${fmt_num(lo)} dan"
    return f"${fmt_num(lo)} – ${fmt_num(hi)}"


def names(selected, table):
    if not selected:
        return "hammasi"
    return ", ".join((table[k][0] if isinstance(table[k], tuple) else table[k])
                     for k in selected if k in table)


def summary():
    return (
        "⚙️ <b>Filtr sozlamalari</b>\n\n"
        f"🌐 <b>Saytlar:</b> {names(S['sources'], SOURCES)}\n"
        f"🏷 <b>Turi:</b> {names(S['deals'], DEALS)}\n"
        f"🏠 <b>Mulk:</b> {names(S['ptypes'], PTYPES)}\n"
        f"🛠 <b>Ta'mir:</b> {names(S['repairs'], REPAIRS)}\n"
        f"🚪 <b>Xonalar:</b> {names(S['rooms'], ROOMS)}\n"
        f"📍 <b>Tumanlar:</b> {names(S['districts'], DISTRICTS)}\n"
        f"💰 <b>Ijara narxi:</b> {price_str(S['price']['rent'])}\n"
        f"💰 <b>Sotuv narxi:</b> {price_str(S['price']['sale'])}\n\n"
        f"Holat: {'⏸ To‘xtatilgan' if S['paused'] else '▶️ Ishlayapti'}"
    )


def main_kb():
    return {"inline_keyboard": [
        [btn("🌐 Saytlar", "m:sources"), btn("🏷 Turi", "m:deals")],
        [btn("🛠 Ta'mir", "m:repairs")],
        [btn("🚪 Xonalar", "m:rooms"), btn("📍 Tumanlar", "m:districts")],
        [btn("💰 Narx", "m:price"), btn("🆕 Oxirgi 24 soat", "last:1")],
        [btn(f"📅 Oxirgi {LATEST_DAYS} kunlik", f"last:{LATEST_DAYS}")],
        [btn("▶️ Davom ettirish" if S["paused"] else "⏸ To'xtatish", "pause")],
    ]}


def list_kb(field, table, per_row=2):
    rows, row = [], []
    for k, v in table.items():
        label = v[0] if isinstance(v, tuple) else v
        row.append(btn(mark(k in S[field]) + label, f"t:{field}:{k}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("🔄 Hammasi", f"clr:{field}"), btn("⬅️ Orqaga", "m:main")])
    return {"inline_keyboard": rows}


def price_kb():
    return {"inline_keyboard": [
        [btn(f"Ijara: {price_str(S['price']['rent'])}", "p:rent")],
        [btn(f"Sotuv: {price_str(S['price']['sale'])}", "p:sale")],
        [btn("⬅️ Orqaga", "m:main")],
    ]}


TITLES = {
    "sources": "🌐 Qaysi saytlardan kelsin?",
    "deals": "🏷 Qaysi e'lonlar kelsin?",
    "repairs": "🛠 Qaysi ta'mir turlari kelsin?\n(hech biri belgilanmasa, hammasi keladi)",
    "rooms": "🚪 Necha xonali?\n(hech biri belgilanmasa, hammasi keladi)",
    "districts": "📍 Qaysi tumanlar?\n(hech biri belgilanmasa, hammasi keladi)",
}
TABLES = {"sources": SOURCES, "deals": DEALS, "repairs": REPAIRS, "rooms": ROOMS, "districts": DISTRICTS}


def deals_kb():
    rows = [[btn(mark(k in S["deals"]) + v[0], f"t:deals:{k}") for k, v in DEALS.items()],
            [btn("— 🏠 Mulk turi —", "noop")]]
    items = [btn(mark(k in S["ptypes"]) + v, f"t:ptypes:{k}") for k, v in PTYPES.items()]
    rows += [items[i:i + 2] for i in range(0, len(items), 2)]
    rows.append([btn("⬅️ Orqaga", "m:main")])
    return {"inline_keyboard": rows}


def show_menu(chat_id, msg_id, menu):
    if menu in ("deals", "ptypes"):
        text, kb = "🏷 Ijara yoki sotuv, keyin mulk turini tanlang:", deals_kb()
    elif menu == "main":
        text, kb = summary(), main_kb()
    elif menu == "price":
        text, kb = "💰 Qaysi narxni o'zgartirasiz? (dollarda)", price_kb()
    else:
        per_row = 4 if menu == "rooms" else 2
        text, kb = TITLES[menu], list_kb(menu, TABLES[menu], per_row)
    if msg_id:
        tg("editMessageText", chat_id=chat_id, message_id=msg_id, text=text,
           parse_mode="HTML", reply_markup=kb)
    else:
        tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb)


def parse_price(text):
    """'300-700', '500', '-800', '1000-', '0' (tozalash)"""
    t = text.replace(" ", "").replace("$", "").replace(",", "")
    if t in ("0", "-", "yoq", "yo'q"):
        return [None, None]
    m = re.fullmatch(r"(\d*)-(\d*)", t)
    if m:
        lo = int(m.group(1)) if m.group(1) else None
        hi = int(m.group(2)) if m.group(2) else None
        return [lo, hi]
    if t.isdigit():
        return [None, int(t)]
    return None


def handle_update(u):
    if "callback_query" in u:
        q = u["callback_query"]
        uid = str(q["from"]["id"])
        chat_id = q["message"]["chat"]["id"]
        msg_id = q["message"]["message_id"]
        data = q.get("data", "")
        if uid != str(ADMIN_ID):
            tg("answerCallbackQuery", callback_query_id=q["id"], text="Ruxsat yo'q")
            return
        tg("answerCallbackQuery", callback_query_id=q["id"])
        with lock:
            if data == "noop":
                return
            if data.startswith("m:"):
                show_menu(chat_id, msg_id, data[2:])
                return
            if data.startswith("t:"):
                _, field, key = data.split(":", 2)
                lst = S[field]
                if key in lst:
                    lst.remove(key)
                else:
                    lst.append(key)
                if field in ("deals", "sources", "ptypes") and not lst:   # kamida bittasi qolsin
                    lst.append(key)
                save_settings()
                show_menu(chat_id, msg_id, field)
                return
            if data.startswith("clr:"):
                field = data[4:]
                S[field] = list(DEALS) if field == "deals" else list(SOURCES) if field == "sources" else []
                save_settings()
                show_menu(chat_id, msg_id, field)
                return
            if data.startswith("p:"):
                deal = data[2:]
                awaiting[chat_id] = {"deal": deal, "step": "lo"}
                name = "Ijara" if deal == "rent" else "Sotuv"
                tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=(
                    f"💰 <b>{name}</b>: eng <b>kam</b> narxni yozing ($)\n\n"
                    "Faqat raqam, masalan: <code>300</code>\n"
                    "Chegara kerak bo'lmasa: <code>0</code>"))
                return
            if data.startswith("last"):
                days = int(data.split(":")[1]) if ":" in data else LATEST_DAYS
                threading.Thread(target=send_latest, args=(chat_id, days), daemon=True).start()
                return
            if data == "pause":
                S["paused"] = not S["paused"]
                save_settings()
                show_menu(chat_id, msg_id, "main")
                return

    msg = u.get("message")
    if not msg or "text" not in msg:
        return
    uid = str(msg["from"]["id"])
    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    if uid != str(ADMIN_ID):
        tg("sendMessage", chat_id=chat_id, text="Bu bot shaxsiy.")
        return
    with lock:
        if text.startswith("/oxirgi"):
            threading.Thread(target=send_latest, args=(chat_id, 1), daemon=True).start()
            return
        if text.startswith("/on_kun") or text.startswith("/uch_kun"):
            threading.Thread(target=send_latest, args=(chat_id, LATEST_DAYS), daemon=True).start()
            return
        if text.startswith("/start") or text.startswith("/filtr"):
            awaiting.pop(chat_id, None)
            show_menu(chat_id, None, "main")
            return
        if chat_id in awaiting:
            digits = re.sub(r"[\s$,.']", "", text)
            if not digits.isdigit():
                tg("sendMessage", chat_id=chat_id,
                   text="Faqat raqam yozing, masalan: 500 (chegara kerak bo'lmasa 0)")
                return
            num = int(digits) or None
            st = awaiting[chat_id]
            if st["step"] == "lo":
                st.update(step="hi", lo=num)
                tg("sendMessage", chat_id=chat_id, parse_mode="HTML", text=(
                    "💰 Endi eng <b>ko'p</b> narxni yozing ($)\n\n"
                    "Faqat raqam, masalan: <code>700</code>\n"
                    "Chegara kerak bo'lmasa: <code>0</code>"))
                return
            lo, hi = st["lo"], num
            if lo and hi and lo > hi:
                lo, hi = hi, lo
            awaiting.pop(chat_id)
            S["price"][st["deal"]] = [lo, hi]
            save_settings()
            tg("sendMessage", chat_id=chat_id,
               text=f"✅ Saqlandi: {price_str([lo, hi])}")
            show_menu(chat_id, None, "main")
            return
    tg("sendMessage", chat_id=chat_id, text="Filtrlarni sozlash uchun /filtr ni bosing.")


def is_restart(u):
    m = u.get("message") or {}
    return (str((m.get("from") or {}).get("id")) == str(ADMIN_ID)
            and (m.get("text") or "").strip().startswith("/restart"))


def do_restart(u, offset):
    chat_id = u["message"]["chat"]["id"]
    # Telegramga bu buyruq bajarilganini bildiramiz, aks holda qayta ishga tushgach yana keladi
    try:
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


LATEST_N = int(os.getenv("LATEST_N", "5"))        # /oxirgi nechta e'lon ko'rsatsin
LATEST_DAYS = int(os.getenv("LATEST_DAYS", "10"))   # /oxirgi necha kunlik e'lonlarni qidirsin


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _jm_quick_ok(it, deal, s):
    """Joymee ro'yxatidagi qisqa ma'lumot bo'yicha tez saralash (batafsil so'rovdan oldin)."""
    if s["districts"]:
        place = (it.get("address_line") or "").lower()
        if not any(w in place for k in s["districts"] for w in DISTRICTS[k][1]):
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


def latest_ads(days=LATEST_DAYS):
    """days=1: oxirgi 24 soat. days>1: 24 soatdan oldingi (1..days kun oralig'idagi) e'lonlar."""
    """Filtrlarga mos, oxirgi LATEST_DAYS kun ichidagi eng yangi e'lonlar."""
    with lock:
        s = json.loads(json.dumps(S))
    deals, ptypes = s["deals"], s.get("ptypes") or ["apt"]
    sources = s.get("sources") or list(SOURCES)
    now = datetime.now(TZ)
    cutoff = now - timedelta(days=days)
    newest = now
    found, errors, scanned = [], [], 0
    for deal in deals:
        for ptype in ptypes:
            if "olx" in sources:
                try:
                    params = dict(api_params(deal, ptype))
                    for page in range(min(25, 4 + days * 2)):   # 10 kunda ~24 sahifa (~1000 e'lon)
                        params["offset"] = page * 40
                        r = requests.get(f"{API}/offers/", params=params, headers=HEADERS, timeout=20)
                        r.raise_for_status()
                        ads = r.json().get("data", [])
                        scanned += len(ads)
                        if not ads:
                            break
                        old = 0
                        for ad in ads:
                            t = _ts(ad.get("created_time"))
                            if t and (t < cutoff or t > newest):
                                old += 1
                                continue
                            if was_sent(ad["id"]):
                                continue
                            ad["ptype"] = ptype
                            if passes_filters(ad, deal):
                                found.append((ad.get("created_time") or "", deal, ad))
                        # OLX ro'yxati qat'iy sana bo'yicha emas (ko'tarilgan eski e'lonlar aralash),
                        # shuning uchun barcha sahifalarni ko'rib chiqamiz
                        time.sleep(1)
                except Exception as e:
                    log.exception("Oxirgi (OLX) xato: %s", e)
                    errors.append(f"OLX: {e}")
            if "joymee" in sources:
                try:
                    details = 0
                    for page in range(1, min(16, 3 + days)):
                        p = {"deal_type": JM_DEAL_TYPE[deal], "category": JM_CATS[(deal, ptype)],
                             "region": JM_REGION, "advertiser_type": 1, "ordering": "newest",
                             "perPageTop": 0, "perPageRaised": 0, "perPagePlain": 40, "page": page}
                        r = requests.get(f"{JM_API}/announcement/", params=p, headers=JM_HEADERS, timeout=20)
                        r.raise_for_status()
                        items = r.json().get("results", [])
                        if not items:
                            break
                        old = 0
                        for it in items:
                            t = _ts(it.get("ads_at"))
                            if t and (t < cutoff or t > newest):
                                old += 1
                                continue
                            if was_sent(f"jm:{it['id']}"):
                                continue
                            if not _jm_quick_ok(it, deal, s) or details >= 80:
                                continue
                            details += 1
                            ad = jm_to_ad(jm_detail(it["id"]))
                            ad["ptype"] = ptype
                            if passes_filters(ad, deal):
                                found.append((it.get("ads_at") or "", deal, ad))
                except Exception as e:
                    log.exception("Oxirgi (Joymee) xato: %s", e)
                    errors.append(f"Joymee: {e}")
    uniq, seen_ids = [], set()
    for item in found:                      # bir e'lon bir necha sahifada takrorlanishi mumkin
        if item[2]["id"] not in seen_ids:
            seen_ids.add(item[2]["id"])
            uniq.append(item)
    uniq.sort(key=lambda x: _ts(x[0]) or cutoff, reverse=True)
    log.info("Oxirgi %s kun: %s ta e'lon ko'rildi, %s ta mos, xatolar: %s",
             days, scanned, len(uniq), errors)
    return uniq[:LATEST_N], errors


search_lock = threading.Lock()


def send_latest(chat_id, days=LATEST_DAYS):
    if not search_lock.acquire(blocking=False):
        tg("sendMessage", chat_id=chat_id,
           text="⏳ Oldingi qidiruv hali tugamadi. U tugagach, qaytadan bosing.")
        return
    try:
        _send_latest(chat_id, days)
    finally:
        search_lock.release()


def _send_latest(chat_id, days):
    label = "24 soatlik" if days == 1 else f"{days} kunlik"
    when = "24 soatda" if days == 1 else f"{days} kunda"
    tg("sendMessage", chat_id=chat_id,
       text=f"🔎 Oxirgi {label} e'lonlar filtringiz bo'yicha qidirilmoqda... (" + ("20–60 soniya" if days <= 1 else "1–2 daqiqa") + ")")
    try:
        found, errors = latest_ads(days)
    except Exception as e:
        log.exception("send_latest xato")
        tg("sendMessage", chat_id=chat_id, text=f"Xato: {e}")
        return
    if errors:
        tg("sendMessage", chat_id=chat_id, text="⚠️ Qidiruvda xato:\n" + "\n".join(errors)[:1000])
    if not found:
        tg("sendMessage", chat_id=chat_id,
           text=f"Oxirgi {when} filtringizga mos yangi e'lon topilmadi "
                "(avval yuborilganlari qayta yuborilmaydi). /filtr orqali filtrni kengaytirib ko'ring.")
        return
    for _, deal, ad in reversed(found):   # eng yangisi oxirida (pastda) chiqadi
        send_ad(ad, deal, chat_id)
        time.sleep(1.5)
    tg("sendMessage", chat_id=chat_id, text=f"✅ Oxirgi {when} {len(found)} ta yangi e'lon yuborildi.")


def telegram_loop():
    tg("setMyCommands", commands=[
        {"command": "restart", "description": "Botni qayta ishga tushirish"},
        {"command": "filtr", "description": "Filtrlarni sozlash"},
        {"command": "oxirgi", "description": "Oxirgi 24 soatlik e'lonlar"},
        {"command": "on_kun", "description": f"Oxirgi {LATEST_DAYS} kunlik e'lonlar"},
    ])
    offset = 0
    while True:
        try:
            r = requests.get(f"{TG}/getUpdates", params={"timeout": 30, "offset": offset},
                             timeout=40)
            if r.status_code == 409:
                log.error("DIQQAT: bot boshqa oynada ham ishlab turibdi! "
                          "Eski oynani yoping, aks holda bot sekin javob beradi.")
                time.sleep(3)
                continue
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if is_restart(u):
                    do_restart(u, offset)
                try:
                    handle_update(u)
                except Exception as e:
                    log.exception("Update xato: %s", e)
        except Exception as e:
            log.warning("getUpdates xato: %s", e)
            time.sleep(5)


# ======================= OLX =======================

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
db.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, ts INTEGER)")
db.execute("CREATE TABLE IF NOT EXISTS sent (id TEXT PRIMARY KEY, ts INTEGER)")
db.execute("CREATE TABLE IF NOT EXISTS sellers (uid TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER)")
db.execute("CREATE TABLE IF NOT EXISTS primed (deal TEXT PRIMARY KEY)")
db.commit()

_api_params = {}


def api_params(deal, ptype="apt"):
    """OLX sahifa yo'lini API parametrlariga aylantiradi (bir marta)."""
    if (deal, ptype) not in _api_params:
        path = f"{OLX_PATHS[(deal, ptype)]}/{CITY}".replace("/", ",")  # OLX vergul kutadi
        r = requests.get(f"{API}/friendly-links/query-params/{path}/", headers=HEADERS, timeout=20)
        r.raise_for_status()
        p = dict(r.json().get("data", {}))
        p.update(owner_type="private", sort_by="created_at:desc", limit=40, offset=0)
        _api_params[(deal, ptype)] = p
        log.info("%s -> %s", path, p)
    return _api_params[(deal, ptype)]


def fetch_offers(deal, ptype="apt", pages=2):
    """Birinchi 2 sahifa (~100 e'lon). OLX ro'yxatida ko'tarilgan eski e'lonlar aralash
    turadi, shuning uchun yangi e'lon birinchi sahifadan pastda bo'lishi mumkin."""
    out, ids = [], set()
    params = dict(api_params(deal, ptype))
    for page in range(pages):
        params["offset"] = page * 40
        r = requests.get(f"{API}/offers/", params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        for ad in r.json().get("data", []):
            if ad["id"] not in ids:
                ids.add(ad["id"])
                out.append(ad)
        if page + 1 < pages:
            time.sleep(1)
    return out


def seller_ad_count(uid):
    if not uid:
        return 0
    main = threading.current_thread() is threading.main_thread()  # sqlite faqat asosiy oqimda
    row = db.execute("SELECT cnt, ts FROM sellers WHERE uid=?", (str(uid),)).fetchone() if main else None
    if row and time.time() - row[1] < 86400:
        return row[0]
    try:
        r = requests.get(f"{API}/offers/", params={"user_id": uid, "limit": 1},
                         headers=HEADERS, timeout=20)
        cnt = r.json().get("metadata", {}).get("total_elements", 0)
    except Exception:
        cnt = 0
    if main:
        db.execute("INSERT OR REPLACE INTO sellers VALUES (?,?,?)", (str(uid), cnt, int(time.time())))
        db.commit()
    return cnt


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


# ---- narx ----
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
    cur = str(pv.get("currency") or "").upper()
    if cur in ("UYE", "USD"):
        return value
    conv, conv_cur = pv.get("converted_value"), str(pv.get("converted_currency") or "").upper()
    if conv and conv_cur in ("UYE", "USD"):
        return float(conv)
    rate = usd_rate()
    return value / rate if rate else None


def price_text(ad):
    """E'londagi asl narx + boshqa valyutadagi qiymati.
    OLX dollardagi e'lonning label'ini ham so'mda beradi, shuning uchun asl qiymatdan yasaymiz."""
    pv = price_value(ad)
    if not pv:
        return "kelishiladi"
    cur = str(pv.get("currency") or "").upper()
    try:
        value = float(pv.get("value"))
    except (TypeError, ValueError):
        return pv.get("label") or "kelishiladi"

    if cur in ("UYE", "USD"):
        text = f"${fmt_num(value)}"
        conv = pv.get("converted_value")
        if conv and str(pv.get("converted_currency") or "").upper() == "UZS":
            text += f" (≈ {fmt_num(float(conv))} so'm)"
        else:
            rate = usd_rate()
            if rate:
                text += f" (≈ {fmt_num(value * rate)} so'm)"
    else:
        text = f"{fmt_num(value)} so'm"
        usd = price_usd(ad)
        if usd:
            text += f" (≈ ${fmt_num(usd)})"
    if pv.get("negotiable"):
        text += ", kelishiladi"
    return text


# ---- filtrlar ----

NAME_AGENT_WORDS = ["rieltor", "riyeltor", "риелтор", "риэлтор", "realtor", "agent", "агент",
                    "makler", "маклер", "estate", "недвижим", "ko'chmas", "kochmas", "uy-joy", "uyjoy"]


def is_owner(ad):
    if ad.get("business"):
        return False
    name = " ".join([str((ad.get("contact") or {}).get("name", "")),
                     str((ad.get("user") or {}).get("name", "")),
                     str(ad.get("seller_name", ""))]).lower()
    if any(w in name for w in NAME_AGENT_WORDS):
        return False
    if ad.get("source") == "joymee":
        text = ad_text(ad)
        return not (any(w in text for w in AGENT_WORDS) and not any(w in text for w in OWNER_WORDS))
    # OLX'dagi "Комиссионные: Да" — rieltor
    for p in ad.get("params", []):
        if p.get("key") in ("comission", "commission") and \
                str((p.get("value") or {}).get("key", "")).lower() == "yes":
            return False
    text = ad_text(ad)
    # "без посредников" degan so'zlar faqat matndagi "komissiya" so'zini bekor qiladi
    # (masalan "komissiyasiz"), lekin e'lonlar soni tekshiruvini emas
    if any(w in text for w in AGENT_WORDS) and not any(w in text for w in OWNER_WORDS):
        return False
    return seller_ad_count((ad.get("user") or {}).get("id")) <= MAX_SELLER_ADS


def passes_filters(ad, deal):
    with lock:
        s = json.loads(json.dumps(S))

    ptype = ad.get("ptype", "apt")
    if s["repairs"] and ptype != "land":
        label = (repair_label(ad) or "").lower()
        text = ad_text(ad)
        words = [w for k in s["repairs"] for w in REPAIRS[k][1]]
        if not any(w in label or w in text for w in words):
            return False

    if s["rooms"] and ptype in ("apt", "house"):
        n = rooms_count(ad)
        if n is None:
            return False
        ok = any((n >= 4) if k == "4" else (n == int(k)) for k in s["rooms"])
        if not ok:
            return False

    if s["districts"]:
        loc = ad.get("location") or {}
        place = " ".join(str((loc.get(k) or {}).get("name", "")) for k in ("district", "city")).lower()
        words = [w for k in s["districts"] for w in DISTRICTS[k][1]]
        if not any(w in place for w in words):
            return False

    lo, hi = s["price"][deal]
    if lo is not None or hi is not None:
        usd = price_usd(ad)
        if usd is None:
            return False
        if lo is not None and usd < lo:
            return False
        if hi is not None and usd > hi:
            return False

    return is_owner(ad)


# ---- xabar ----

TZ = timezone(timedelta(hours=5))   # Toshkent vaqti


def posted_text(iso):
    """'2026-11-04T01:33:07+05:00' -> '04.11.2026, 01:33 (25 daqiqa oldin)'"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        dt = dt.astimezone(TZ)
    except ValueError:
        return None
    mins = int((datetime.now(TZ) - dt).total_seconds() // 60)
    if mins < 1:
        ago = "hozirgina"
    elif mins < 60:
        ago = f"{mins} daqiqa oldin"
    elif mins < 24 * 60:
        ago = f"{mins // 60} soat oldin"
    else:
        ago = f"{mins // 1440} kun oldin"
    return f"{dt:%d.%m.%Y, %H:%M} ({ago})"

ADDR_RE = re.compile(
    r"(?im)^(?:[^\w\n]*)("
    r"(?:адрес|manzil|address)\s*[:\-–]\s*.+|"
    r"(?:ул\.|улица|проспект|пр-т|массив|ж/м|квартал|mavze|ko['ʻ’`]?cha|kocha|tor\s?ko['ʻ’`]?cha)\s*.+|"
    r".+\s(?:ул\.|улица|ko['ʻ’`]?chasi|kochasi|mavzesi|kvartal|квартал|massivi)\b.*"
    r")$")
LANDMARK_RE = re.compile(r"(?im)(?:ориентир|orientir|mo['ʻ’`]?ljal)\s*[:\-–]?\s*([^\n]+)")


def address_from_text(desc):
    """E'lon matnidan ko'cha va mo'ljalni ajratib oladi."""
    street = landmark = None
    m = ADDR_RE.search(desc)
    if m:
        street = re.sub(r"(?i)^(адрес|manzil|address)\s*[:\-–]\s*", "", m.group(1)).strip(" .,")
    m = LANDMARK_RE.search(desc)
    if m:
        landmark = m.group(1).strip(" .,")
    return (street[:120] if street else None), (landmark[:100] if landmark else None)


def format_ad(ad, deal):
    loc = ad.get("location") or {}
    parts = [(loc.get(k) or {}).get("name") for k in ("region", "city", "district")]
    address = ", ".join(dict.fromkeys(p for p in parts if p)) or "ko'rsatilmagan"

    area = param(ad, "total_area", "area", "m", "land_area")
    floor = param(ad, "floor")
    floors = param(ad, "total_floors", "floors_in_building")
    rooms = rooms_count(ad)
    rep = repair_label(ad)

    lines = [
        f"🏠 <b>{SOURCES.get(ad.get('source', 'olx'))}'da yangi e'lon joylandi!</b> ({DEALS[deal][0]} · {PTYPES.get(ad.get('ptype', 'apt'))})",
        "",
        f"<b>{esc(ad.get('title', '')[:150])}</b>",
        "",
        f"💰 <b>Narxi:</b> {esc(price_text(ad))}",
        *([f"🕒 <b>Joylangan:</b> {posted_text(ad.get('created_time'))}"]
          if posted_text(ad.get("created_time")) else []),
        f"📞 <b>Telefon:</b> {esc(ad.get('phone_text') or 'e’londa ko‘ring')}",
    ]
    if rooms:
        lines.append(f"🚪 <b>Xonalar:</b> {rooms}")
    if area:
        a = str(area)
        lines.append(f"📐 <b>Maydoni:</b> {esc(a)}{'' if re.search(r'[^\d\s.,]', a) else ' m²'}")
    if floor:
        lines.append(f"🏢 <b>Qavat:</b> {esc(str(floor))}" +
                     (f" / {esc(str(floors))}" if floors else ""))
    if rep:
        lines.append(f"🛠 <b>Ta'mir:</b> {esc(str(rep))}")
    lines.append(f"📍 <b>Manzil:</b> {esc(address)}")

    desc = re.sub(r"<[^>]+>", "", (ad.get("description") or "").replace("<br />", "\n"))
    desc = re.sub(r"\n\s*\n+", "\n", desc).strip()
    street, landmark = address_from_text(desc)
    if street:
        lines.append(f"🏘 <b>Ko'cha:</b> {esc(street)}")
    if landmark:
        lines.append(f"🎯 <b>Mo'ljal:</b> {esc(landmark)}")

    m = ad.get("map") or {}
    if m.get("lat") and m.get("lon"):
        lines.append(f'🗺 <a href="https://maps.google.com/?q={m["lat"]},{m["lon"]}">Xaritada ko\'rish</a>')

    tail = f'\n\n🔗 <a href="{ad.get("url")}">E\'lonni ochish</a>'
    head = "\n".join(lines)
    # Telegram rasm izohi 1024 belgigacha; teglarni buzmaslik uchun faqat matnni qisqartiramiz
    room = min(300, 1000 - len(head) - len(tail) - 2)
    if desc and room > 40:
        part = desc[:room]
        piece = esc(part)
        while len(piece) > room and part:      # &lt; kabi belgilar uzunlikni oshiradi
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


def was_sent(ad_id):
    return db.execute("SELECT 1 FROM sent WHERE id=?", (str(ad_id),)).fetchone() is not None


def mark_sent(ad_id):
    db.execute("INSERT OR IGNORE INTO sent VALUES (?,?)", (str(ad_id), int(time.time())))
    db.commit()


PHONE_RE = re.compile(r"(?:\+?998[\s\-()]*)?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


def fmt_phone(raw):
    d = re.sub(r"\D", "", str(raw))
    if len(d) == 9:
        d = "998" + d
    if len(d) == 12 and d.startswith("998"):
        return f"+998 {d[3:5]} {d[5:8]} {d[8:10]} {d[10:12]}"
    return str(raw).strip()


def get_phone(ad):
    """Sotuvchi telefoni: Joymee'da e'lonning o'zida, OLX'da alohida so'rov orqali."""
    if ad.get("phone"):
        return fmt_phone(ad["phone"])
    if ad.get("source") != "joymee":
        try:
            r = requests.get(f"{API}/offers/{ad['id']}/limited-phones/", headers=HEADERS, timeout=15)
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


def send_ad(ad, deal, chat_id=None):
    chat_id = chat_id or CHAT_ID
    if "phone_text" not in ad:
        ad["phone_text"] = get_phone(ad)
    caption = format_ad(ad, deal)
    pics = photos(ad)
    if len(pics) >= 2:
        media = [{"type": "photo", "media": u} for u in pics]
        media[0].update(caption=caption, parse_mode="HTML")
        r = tg("sendMediaGroup", chat_id=chat_id, media=media)
        if r is not None and r.ok:
            mark_sent(ad["id"])
            return
    if pics:
        r = tg("sendPhoto", chat_id=chat_id, photo=pics[0], caption=caption, parse_mode="HTML")
        if r is not None and r.ok:
            mark_sent(ad["id"])
            return
    r = tg("sendMessage", chat_id=chat_id, text=caption, parse_mode="HTML",
           disable_web_page_preview=True)
    if r is not None and r.ok:
        mark_sent(ad["id"])


# ======================= ASOSIY SIKL =======================

def is_seen(ad_id):
    return db.execute("SELECT 1 FROM seen WHERE id=?", (str(ad_id),)).fetchone() is not None


def mark_seen(ad_id):
    db.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", (str(ad_id), int(time.time())))
    db.commit()


# ======================= JOYMEE =======================

JM_API = "https://api.joymee.uz/api/v1"
JM_CATS = {("rent", "apt"): 4, ("rent", "house"): 5, ("rent", "kom"): 6, ("rent", "land"): 7,
           ("sale", "apt"): 8, ("sale", "house"): 9, ("sale", "kom"): 10, ("sale", "land"): 11}
JM_DEAL_TYPE = {"rent": 2, "sale": 3}
JM_REGION = os.getenv("JOYMEE_REGION", "59")   # 59 = Toshkent shahri
JM_REPAIR = {1: "Ta'mir talab", 2: "Yaxshi holatda", 3: "Kosmetik", 4: "Yevroremont",
             5: "Dizaynerlik", 6: "Kapital"}
JM_HEADERS = {**HEADERS, "Origin": "https://joymee.uz", "Referer": "https://joymee.uz/",
              "Accept": "application/json"}


def jm_list(deal, ptype="apt"):
    p = {"deal_type": JM_DEAL_TYPE[deal], "category": JM_CATS[(deal, ptype)], "region": JM_REGION, "advertiser_type": 1, "ordering": "newest",
         "perPageTop": 0, "perPageRaised": 0, "perPagePlain": 40, "page": 1}
    r = requests.get(f"{JM_API}/announcement/", params=p, headers=JM_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("results", [])


def jm_detail(ann_id):
    r = requests.get(f"{JM_API}/announcement/{ann_id}/", headers=JM_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def jm_to_ad(d):
    """Joymee e'lonini OLX ko'rinishiga keltiramiz, shunda filtr va xabar bir xil ishlaydi."""
    det = d.get("detail") or {}
    pr = d.get("pricing") or {}
    params = []
    try:
        params.append({"key": "price", "value": {
            "value": float(pr.get("price")),
            "currency": "UYE" if pr.get("currency") == 2 else "UZS"}})
    except (TypeError, ValueError):
        pass
    if det.get("room_quantity"):
        params.append({"key": "number_of_rooms", "value": {"label": str(det["room_quantity"])}})
    if det.get("area_m2"):
        params.append({"key": "total_area",
                       "value": {"label": f"{float(det['area_m2']):g}"}})
    if det.get("floor_number"):
        params.append({"key": "floor", "value": {"label": str(det["floor_number"])}})
    if det.get("floors_count"):
        params.append({"key": "total_floors", "value": {"label": str(det["floors_count"])}})
    if det.get("repair") in JM_REPAIR:
        params.append({"key": "repairs", "name": "Ремонт",
                       "value": {"label": JM_REPAIR[det["repair"]]}})
    loc = d.get("location") or {}
    media = sorted(d.get("media") or [], key=lambda m: m.get("order") or 0)
    return {
        "source": "joymee",
        "id": f"jm:{d['id']}",
        "url": f"https://joymee.uz/announcements/{d['id']}",
        "title": d.get("title") or "",
        "created_time": d.get("ads_at"),
        "phone": d.get("phone_number"),
        "seller_name": " ".join(filter(None, [(d.get("seller") or {}).get("first_name"),
                                              (d.get("seller") or {}).get("username")])),
        "description": (d.get("description") or "").replace("\n", "<br />\n"),
        "business": d.get("advertiser_type") == 2,
        "user": {"id": (d.get("seller") or {}).get("id")},
        "params": params,
        "location": {"region": d.get("region") or {}, "district": d.get("district") or {}},
        "map": {"lat": loc.get("latitude"), "lon": loc.get("longitude")},
        "photos": [{"link": (m.get("file") or {}).get("url")} for m in media],
    }


def check_joymee(deal, ptype="apt"):
    items = jm_list(deal, ptype)
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
            ad = jm_to_ad(jm_detail(it["id"]))
            ad["ptype"] = ptype
        except Exception as e:
            log.warning("Joymee e'lon %s xato: %s", it["id"], e)
            continue
        if not was_sent(ad["id"]) and passes_filters(ad, deal):
            log.info("Yangi (Joymee): %s", ad.get("title"))
            send_ad(ad, deal)
            time.sleep(2)
        time.sleep(1)


def check_deal(deal, ptype="apt"):
    ads = fetch_offers(deal, ptype)
    for ad in ads:
        ad["ptype"] = ptype
    pkey = deal if ptype == "apt" else f"{deal}:{ptype}"
    primed = db.execute("SELECT 1 FROM primed WHERE deal=?", (pkey,)).fetchone()
    if not primed:
        # Birinchi marta: eski e'lonlarni yubormaymiz, faqat eslab qolamiz
        for ad in ads:
            mark_seen(ad["id"])
        db.execute("INSERT INTO primed VALUES (?)", (pkey,))
        db.commit()
        log.info("%s: eski e'lonlar saqlandi, endi faqat yangilari keladi", pkey)
        return
    for ad in reversed(ads):
        if is_seen(ad["id"]):
            continue
        mark_seen(ad["id"])
        if not was_sent(ad["id"]) and passes_filters(ad, deal):
            log.info("Yangi: %s", ad.get("title"))
            send_ad(ad, deal)
            time.sleep(2)


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
                if "python" in out:          # faqat python jarayoni bo'lsa
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
    if not (BOT_TOKEN and CHAT_ID):
        raise SystemExit(".env faylida BOT_TOKEN va CHAT_ID ni to'ldiring")

    kill_old_instance()
    if os.path.exists("restart_chat.txt"):
        with open("restart_chat.txt") as f:
            rc = f.read().strip()
        os.remove("restart_chat.txt")
        tg("sendMessage", chat_id=rc, text="✅ Bot qayta ishga tushdi.")
    threading.Thread(target=telegram_loop, daemon=True).start()
    log.info("Bot ishga tushdi. Telegramda /filtr ni bosing.")

    while True:
        with lock:
            paused, deals = S["paused"], list(S["deals"])
            sources = list(S.get("sources") or SOURCES)
            ptypes = list(S.get("ptypes") or ["apt"])
        if not paused:
            for deal in deals:
                for ptype in ptypes:
                    if "olx" in sources:
                        try:
                            check_deal(deal, ptype)
                        except Exception as e:
                            log.warning("OLX xato (%s/%s): %s", deal, ptype, e)
                        time.sleep(4)
                    if "joymee" in sources:
                        try:
                            check_joymee(deal, ptype)
                        except Exception as e:
                            log.warning("Joymee xato (%s/%s): %s", deal, ptype, e)
                        time.sleep(4)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
