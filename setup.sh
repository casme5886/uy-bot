#!/bin/bash
# Uy Savat botni Ubuntu serverga o'rnatish (Oracle Cloud). OLX uydagi kompyuter "ko'prigi" orqali ishlaydi.
# Ishlatish: bash ~/uy-bot/setup.sh [nostart]
set -e
cd "$(dirname "$0")"
sed -i 's/\r$//' .env 2>/dev/null || true
chmod 600 .env
grep -q '^OLX_PROXY=' .env || echo 'OLX_PROXY=socks5h://127.0.0.1:1080' >> .env

echo "== 1/4 Python o'rnatilmoqda =="
sudo apt-get update -y -qq
sudo apt-get install -y -qq python3 python3-venv curl

echo "== 2/4 Kutubxonalar o'rnatilmoqda =="
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q "requests[socks]" python-dotenv

echo "== 3/4 Ko'prik uchun SSH sozlanmoqda =="
grep -qF "$(cut -d' ' -f2 relay_key.pub)" ~/.ssh/authorized_keys 2>/dev/null || cat relay_key.pub >> ~/.ssh/authorized_keys
printf 'ClientAliveInterval 20\nClientAliveCountMax 3\nAllowTcpForwarding yes\n' | sudo tee /etc/ssh/sshd_config.d/uybot.conf >/dev/null
sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd 2>/dev/null || true

echo "== 4/4 Bot xizmati sozlanmoqda =="
sudo tee /etc/systemd/system/uybot.service >/dev/null <<UNIT
[Unit]
Description=Uy Savat Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$PWD
Environment=UYBOT_LAUNCHER=1
ExecStart=$PWD/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable uybot >/dev/null 2>&1
if [ "$1" = "nostart" ]; then
  sudo systemctl stop uybot 2>/dev/null || true
  echo "Bot o'rnatildi, lekin hali ishga tushirilmadi (uni ko'prik fayli yoqadi)."
else
  sudo systemctl restart uybot
  sleep 6; sudo systemctl --no-pager status uybot | head -5
fi
echo "Telegram: $(curl -s -o /dev/null -w '%{http_code}' https://api.telegram.org)"
