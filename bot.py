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
from selenium.common.exceptions import TimeoutException

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

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
            requests.post(self.api_url, data={
                "chat_id": self.chat_id,
                "text": self.format(record)
            })
        except:
            pass
logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
# Консольный
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(ch)
# Telegram
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(tg)

# Инициализация WebDriver
opts = uc.ChromeOptions()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--disable-gpu')
opts.add_argument('--window-size=1920,1080')
driver = uc.Chrome(options=opts)
wait = WebDriverWait(driver, 20)

# Шаг 1: "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']" +
            " | //button[contains(text(),'Yes, confirm')]" +
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# Шаг 2: Получение SMS-кода из Telegram с таймаутом
def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    # сброс старых
    try:
        init = requests.get(api_url, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            if ids:
                last_update = max(ids) + 1
    except:
        last_update = None
    deadline = time.time() + timeout
    logger.info(f"⏳ Ждем SMS-код (#код 123456 или 123456), таймаут {timeout}s...")
    while time.time() < deadline:
        try:
            resp = requests.get(api_url, params={'timeout':0,'offset': last_update}).json()
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
            if not msg or str(msg['chat']['id']) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Сообщение: {text!r}")
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, flags=re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Код найден: {code}")
                return code
        time.sleep(poll_interval)
    logger.error("❌ Таймаут ожидания SMS-кода")
    raise TimeoutException("SMS-код не получен")

# Шаг 3: Клик Get code, retrieve, дождаться формы, ввести код
def try_sms_verification():
    try:
        driver.save_screenshot("sms_verification_page.png")
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        btn.click()
        logger.info("📲 'Get code' нажат")
        driver.save_screenshot("sms_requested.png")
        # сразу ждем код
        code = retrieve_sms_code()
        # затем ждем форму
        logger.info("🔄 Ждем форму и поле для кода...")
        inp = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH,
            "//input[@id='smsCode' or @name='st.r.smsCode']"
        )))
        driver.save_screenshot("sms_input_field.png")
        inp.clear()
        inp.send_keys(code)
        logger.info(f"✍️ Код введён: {code}")
        driver.save_screenshot("sms_code_entered.png")
        next_btn = driver.find_element(By.XPATH,
            "//input[@type='submit' and @value='Next']"
        )
        next_btn.click()
        logger.info("✅ Нажат Next")
        driver.save_screenshot("sms_confirmed.png")
    except TimeoutException:
        logger.error("❌ Не дождались кода или формы")
        driver.save_screenshot("sms_timeout.png")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        driver.save_screenshot("sms_error.png")
        sys.exit(1)

# Основной сценарий
if __name__ == '__main__':
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")
        logger.info("🔑 Вход")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")
        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Готово")
    except Exception as ex:
        logger.error(f"🔥 Ошибка: {ex}")
        driver.save_screenshot("fatal_error.png")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Закрыто")
