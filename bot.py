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
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    print("❌ Не заданы необходимые переменные окружения: OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.")
    sys.exit(1)

# Настройка логгера
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def emit(self, record):
        log_entry = self.format(record)
        try:
            requests.post(
                self.api_url,
                data={"chat_id": self.chat_id, "text": log_entry}
            )
        except Exception:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

# Консольный вывод
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Telegram-логгер
tg_handler = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
tg_handler.setFormatter(formatter)
logger.addHandler(tg_handler)

# Настройка Chrome\options = uc.ChromeOptions()
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)

def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(), 'Yes, confirm')] | //button[contains(., 'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 Подтверждение 'It’s you' пройдено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(2)
    except TimeoutException:
        logger.info("ℹ️ Страница 'It’s you' не показана.")


def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    deadline = time.time() + timeout
    last_update = None
    logger.info("⏳ Ожидание SMS-кода в Telegram...")

    while time.time() < deadline:
        try:
            resp = requests.get(api_url, params={'timeout': 0, 'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка при запросе к Telegram: {e}")
            time.sleep(poll_interval)
            continue
        if not resp.get('ok'): time.sleep(poll_interval); continue

        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg['chat']['id']) != TELEGRAM_CHAT_ID: continue
            text = msg.get('text', '')
            m = re.search(r"(\d{4,6})", text)
            if m:
                code = m.group(1)
                logger.info(f"📥 Получен код: {code}")
                return code
        time.sleep(poll_interval)
    raise TimeoutException("Не получили SMS-код в Telegram")


def try_sms_verification():
    try:
        # Ожидание кнопки Get code
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(., 'Get code')] | //button[contains(., 'Получить код')]"
        )))
        btn.click()
        logger.info("📲 Запрошен SMS-код (Get code).")
        driver.save_screenshot("sms_requested.png")

        # Уведомление в Telegram
        logger.info("📲 Жду SMS-код. Отправьте его боту в Telegram.")

        # Ожидание поля ввода OTP
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@name='otp'] | //input[contains(@placeholder,'код')]"
        )))
        driver.save_screenshot("sms_input_field.png")

        # Получаем и вводим код
        code = retrieve_sms_code()
        inp.send_keys(code)
        driver.save_screenshot("sms_code_entered.png")

        # Подтверждение
        ok_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(., 'Submit')] | //button[contains(., 'Подтвердить')]"
        )))
        ok_btn.click()
        logger.info("✅ SMS-код подтвержден.")
        driver.save_screenshot("sms_confirmed.png")
    except TimeoutException:
        logger.error("❌ Не удалось найти элементы SMS-верификации.")
    except Exception as e:
        logger.error(f"❌ Ошибка SMS-верификации: {e}")


# Основной сценарий
try:
    logger.info("Открываем OK.RU...")
    driver.get("https://ok.ru/")
    driver.save_screenshot("login_page.png")

    wait.until(EC.presence_of_element_located((By.NAME, 'st.email'))).send_keys(EMAIL)
    driver.find_element(By.NAME, 'st.password').send_keys(PASSWORD)
    driver.save_screenshot("credentials_entered.png")

    logger.info("Вводим логин/пароль и нажимаем Войти...")
    driver.find_element(By.XPATH, "//input[@type='submit']").click()

    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")

    try_confirm_identity()
    try_sms_verification()
    logger.info("Авторизация завершена.")
except Exception as ex:
    logger.error(f"Критическая ошибка: {ex}")
    driver.save_screenshot("fatal_error.png")
finally:
    driver.quit()
    logger.info("Драйвер закрыт.")
