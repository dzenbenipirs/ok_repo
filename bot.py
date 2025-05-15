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
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID.")
    sys.exit(1)

# --- Настройка логгера с отправкой в Telegram ---
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def emit(self, record):
        payload = {"chat_id": self.chat_id, "text": self.format(record)}
        try:
            requests.post(self.api_url, data=payload)
        except Exception:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

# Консольный логгер
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)
# Telegram-логгер
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
tg.setFormatter(formatter)
logger.addHandler(tg)

# --- WebDriver setup ---
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)

# --- Шаг подтверждения «It’s you» ---
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(), 'Yes, confirm')] | //button[contains(text(), 'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It’s you' пройдено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except TimeoutException:
        logger.info("ℹ️ Страница 'It’s you' не показана.")

# --- Ожидание и ввод SMS-кода через Telegram ---
def retrieve_sms_code(timeout=120, poll_interval=5):
    api_get = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    deadline = time.time() + timeout
    last_update = None
    logger.info("⏳ Ожидание SMS-кода в Telegram...")

    while time.time() < deadline:
        try:
            resp = requests.get(api_get, params={'timeout':0,'offset':last_update}).json()
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
            if not msg or str(msg['chat']['id']) != TELEGRAM_CHAT_ID:
                continue
            text = msg.get('text','')
            m = re.search(r"(\d{4,6})", text)
            if m:
                code = m.group(1)
                logger.info(f"📥 Код получен: {code}")
                return code
        time.sleep(poll_interval)
    raise TimeoutException("Не был получен SMS-код в Telegram")

# --- Шаг запроса SMS-верификации ---
def try_sms_verification():
    try:
        # Убедимся, что инструкция загрузилась
        wait.until(EC.presence_of_element_located((By.XPATH,
            "//div[contains(normalize-space(.), 'With it, we can confirm that this is this your profile. For this, we will send a code by free text message to the phone number indicated')]"
        )))
        # Найдём кнопку Get code с точным текстом
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//*[self::button or self::a or self::div][normalize-space(text())='Get code']"
        )))
        btn.click()
        logger.info("📲 Нажата кнопка 'Get code'. SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        # Уведомление в Telegram
        logger.info("📲 Скрипт ожидает SMS-код. Отправьте его боту.")

        # Ждём поле для ввода кода
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@name='otp'] | //input[contains(@placeholder,'код')]"
        )))
        driver.save_screenshot("sms_input_field.png")

        # Получаем и вводим код
        code = retrieve_sms_code()
        inp.send_keys(code)
        driver.save_screenshot("sms_code_entered.png")

        # Подтверждаем ввод
        ok = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[normalize-space(text())='Submit'] | //button[normalize-space(text())='Подтвердить']"
        )))
        ok.click()
        logger.info("✅ SMS-код подтверждён.")
        driver.save_screenshot("sms_confirmed.png")
    except TimeoutException:
        logger.error("❌ Не найдена кнопка 'Get code' или поле для ввода кода.")
    except Exception as e:
        logger.error(f"❌ Ошибка во время SMS-верификации: {e}")

# --- Основной сценарий авторизации ---
try:
    logger.info("Открываем https://ok.ru...")
    driver.get("https://ok.ru/")
    driver.save_screenshot("login_page.png")

    # Вводим учётные данные
    wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
    driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
    driver.save_screenshot("credentials_entered.png")

    logger.info("Отправляем форму логина...")
    driver.find_element(By.XPATH,"//input[@type='submit']").click()
    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")

    # Подтверждаем личность и SMS-верификацию
    try_confirm_identity()
    try_sms_verification()

    logger.info("Авторизация завершена.")
except Exception as ex:
    logger.error(f"Критическая ошибка: {ex}")
    driver.save_screenshot("fatal_error.png")
finally:
    driver.quit()
    logger.info("Драйвер закрыт.")
