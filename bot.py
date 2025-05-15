import os
import time
import re
import requests
import logging
import sys

# Чтение учётных данных из окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # ваш Chat ID или User ID

if not all([TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Не заданы переменные TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Настройка логгера: консоль + Telegram
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def emit(self, record):
        payload = {"chat_id": self.chat_id, "text": self.format(record)}
        try:
            requests.post(self.api_url, data=payload)
        except:
            pass

logger = logging.getLogger("sms_listener")
logger.setLevel(logging.INFO)
# Консольный логгер
console = logging.StreamHandler(sys.stdout)
console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(console)
# Telegram-логгер
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(tg)

# Получение SMS-кода из Telegram
def retrieve_sms_code(poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    # Сбрасываем старые апдейты
    try:
        init = requests.get(api_url, params={'timeout': 0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            if ids:
                last_update = max(ids) + 1
    except Exception:
        last_update = None

    logger.info("⏳ Скрипт запущен. Ожидание SMS-кода в формате '#код 123456' или '123456'.")
    while True:
        try:
            resp = requests.get(api_url, params={'timeout': 0, 'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue

        if not resp.get('ok'):
            time.sleep(poll_interval)
            continue

        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat', {}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text', '').strip()
            logger.info(f"📨 Получено сообщение: {text!r}")
            # Формат: #код 123456 или просто 123456
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, flags=re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Найден SMS-код: {code}")
                return code
        time.sleep(poll_interval)

if __name__ == '__main__':
    code = retrieve_sms_code()
    logger.info(f"🎉 Код обработан: {code}. Завершение.")
    sys.exit(0)
