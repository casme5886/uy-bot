import urllib.request, json
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "ru-RU,ru;q=0.9"}
tests = [("olx.uz", "https://olx.uz/api/v1/offers/?limit=1"),
         ("m.olx.uz", "https://m.olx.uz/api/v1/offers/?limit=1"),
         ("www api", "https://www.olx.uz/api/v1/offers/?limit=1"),
         ("rasm cdn", "https://frankfurt.apollo.olxcdn.com/"),
         ("olx.kz", "https://www.olx.kz/api/v1/offers/?limit=1")]
for name, url in tests:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=20)
        print(f"{name:10} -> {r.status} OK")
    except urllib.error.HTTPError as e:
        print(f"{name:10} -> {e.code} {'BLOKLANGAN' if e.code == 403 else ''}")
    except Exception as e:
        print(f"{name:10} -> XATO {e}")
try:
    print("IP:", urllib.request.urlopen("https://ipinfo.io/json", timeout=10).read().decode().replace("\n", " ")[:250])
except Exception as e:
    print("IP xato", e)
