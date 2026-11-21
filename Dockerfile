# Uy Savat bot — uy serveri (Coolify) uchun
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UYBOT_LAUNCHER=1 \
    TZ=Asia/Tashkent

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# Ma'lumotlar (seen.db, bot.log, settings.json) /data papkasida saqlanadi.
# Coolify'da /data uchun "Persistent Storage" qo'shiladi, shunda qayta deploy'da o'chmaydi.
WORKDIR /data
CMD ["sh", "-c", "rm -f /data/bot.pid; exec python /app/bot.py"]
