# Botni Oracle Cloud serverga ko'chirish

## 1. Hisob ochish (10 daqiqa)
1. https://www.oracle.com/cloud/free/ → **Start for free**.
2. Pochta, ism, mamlakat (Uzbekistan) kiriting.
3. **Home Region** tanlang — keyin o'zgartirib bo'lmaydi. Bandligi kamroq hudud ma'qul.
4. Karta ma'lumotlarini kiriting (faqat tasdiqlash uchun; bepul limitda pul yechilmaydi).

## 2. Server yaratish
1. Konsolda: **Compute → Instances → Create instance**.
2. **Image**: *Canonical Ubuntu 24.04*.
3. **Shape** → *Change shape*:
   - **Ampere → VM.Standard.A1.Flex**, 1 OCPU, 6 GB (yaxshisi), yoki
   - "Out of capacity" bo'lsa: **AMD → VM.Standard.E2.1.Micro** (doim bor).
   - Har ikkalasida **"Always Free-eligible"** belgisi borligini tekshiring.
4. **Networking**: *Assign a public IPv4 address* yoqilgan bo'lsin.
5. **Add SSH keys** → *Generate a key pair for me* → **Save private key** (fayl yuklanadi, uni yo'qotmang!).
6. **Create** → 1–2 daqiqada holat **Running** bo'ladi. **Public IP address** ni yozib oling.

## 3. Botni ko'chirish
1. Kompyuterdagi botni to'xtating (PowerShell oynasida Ctrl+C → Y) — ikki nusxa bo'lmasin.
2. PowerShell:
   ```powershell
   cd E:\project\uy-bot
   Set-ExecutionPolicy -Scope Process Bypass
   .\upload.ps1 -Ip <SERVER_IP> -Key <yuklangan_kalit_fayl_yo'li>
   ```
   Masalan: `.\upload.ps1 -Ip 152.70.10.20 -Key C:\Users\User\Downloads\ssh-key-2026-11-04.key`
3. Oxirida 3/4 qadamda OLX va Joymee uchun **200** chiqishi kerak.
   403 yoki 000 chiqsa — sayt serverni bloklayapti, menga yozing.

## Keyin kerak bo'ladigan buyruqlar (serverga ulanib)
```powershell
ssh -i <kalit> ubuntu@<SERVER_IP>
```
- Holat: `sudo systemctl status uybot`
- Yozuvlar: `tail -n 50 ~/uy-bot/bot.log`
- Qayta ishga tushirish: `sudo systemctl restart uybot` (yoki Telegramda /restart)
- Yangi bot.py yuklash (kompyuterdan): `scp -i <kalit> bot.py ubuntu@<SERVER_IP>:~/uy-bot/` → /restart
