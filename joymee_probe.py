"""
Joymee.uz qanday ma'lumot yuborishini aniqlash uchun bir martalik dastur.
Natija: joymee_dump.json — shu faylni Claude'ga yuboring.

O'rnatish (bir marta):
    pip install playwright
    python -m playwright install chromium
Ishga tushirish:
    python joymee_probe.py
"""
import json
from playwright.sync_api import sync_playwright

PAGES = [
    "https://joymee.uz/",
    "https://joymee.uz/seller/search",
]

captured = []


def on_response(resp):
    try:
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            return
        body = resp.json()
        text = json.dumps(body, ensure_ascii=False)
        captured.append({
            "url": resp.url,
            "method": resp.request.method,
            "post_data": resp.request.post_data,
            "status": resp.status,
            "body": body if len(text) < 60000 else text[:60000] + "...(qisqartirildi)",
        })
        print("JSON:", resp.status, resp.url[:150])
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # brauzer oynasi ochiladi
    page = browser.new_page(locale="uz-UZ")
    page.on("response", on_response)
    for url in PAGES:
        print("Ochilmoqda:", url)
        page.goto(url, wait_until="networkidle", timeout=60000)
        for _ in range(5):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)

    print("\nBrauzerda Ijara / Sotuv filtrlarini, 'Egasi' filtrini bosing, bitta e'lonni oching.")
    input("Tugatgach shu yerda Enter bosing...")

    browser.close()

with open("joymee_dump.json", "w", encoding="utf-8") as f:
    json.dump(captured, f, ensure_ascii=False, indent=1)
print(f"\nTayyor: {len(captured)} ta so'rov joymee_dump.json fayliga saqlandi.")
