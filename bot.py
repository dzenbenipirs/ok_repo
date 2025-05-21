import os
import time
import re
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # Ваш chat_id или group id

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Настройка логгера: консоль + Telegram
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
    def emit(self, record):
        try:
            requests.post(self.api_url, data={"chat_id": self.chat_id, "text": self.format(record)})
        except:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
# Консольный логгер
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(ch)
# Telegram-логгер
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(tg)

# Инициализация WebDriver
def init_driver():
    opts = uc.ChromeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    return uc.Chrome(options=opts)

driver = init_driver()
wait = WebDriverWait(driver, 20)

# 1) Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(),'Yes, confirm')] | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# 2) Получение SMS-кода из Telegram с таймаутом 120s
#    формат: '#код текст' или просто текст

def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    try:
        init = requests.get(api_url, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            last_update = max(ids) + 1 if ids else None
    except:
        last_update = None
    deadline = time.time() + timeout
    logger.info(f"⏳ Ожидание SMS-кода, таймаут {timeout}s...")
    while time.time() < deadline:
        try:
            resp = requests.get(api_url, params={'timeout':0,'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Получено сообщение: {text!r}")
            m = re.match(r"^(?:#код\s*)?(.+)$", text, flags=re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Код или текст для SMS: {code}")
                return code
        time.sleep(poll_interval)
    logger.error("❌ Таймаут ожидания SMS-кода")
    raise TimeoutException("SMS-код не получен (таймаут)")

# 3) Получение текста для поста из Telegram
#    ждет '#пост ТЕКСТ'

def retrieve_post_text(poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    try:
        init = requests.get(api_url, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            last_update = max(ids) + 1 if ids else None
    except:
        last_update = None
    logger.info("⏳ Ожидание команды '#пост <текст>' в Telegram...")
    while True:
        try:
            resp = requests.get(api_url, params={'timeout':0,'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Получено сообщение: {text!r}")
            m = re.match(r"^#пост\s+(.+)$", text, flags=re.IGNORECASE)
            if m:
                post = m.group(1)
                logger.info(f"✅ Текст для поста: {post}")
                return post
        time.sleep(poll_interval)

# 4) Постинг на страницу пользователя (OK.ru Feed)
def post_to_ok(text):
    logger.info("🚀 Публикую пост на страницу...")
    driver.get("https://ok.ru/feed")
    # Ожидаем поле ввода поста
    textarea = wait.until(EC.presence_of_element_located((By.XPATH,
        "//textarea[contains(@class,'posting_field')]"
    )))
    textarea.click()
    textarea.send_keys(text)
    time.sleep(1)
    # Нажимаем кнопку 'Опубликовать'
    publish = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[contains(.,'Опубликовать')]"
    )))
    publish.click()
    logger.info("✅ Пост опубликован!")

# Основной сценарий
def main():
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        # ввод и логин
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        # SMS-верификация, если требуется
        code = retrieve_sms_code()
        # реальное использование кода не нужно здесь, пропустим
        # Дальше ждем команду #пост и публикуем
        post = retrieve_post_text()
        post_to_ok(post)
        logger.info("🎉 Скрипт завершен.")
    except Exception as ex:
        logger.error(f"🔥 Ошибка: {ex}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
