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
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
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
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
telegram_handler = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
telegram_handler.setFormatter(formatter)
logger.addHandler(telegram_handler)

# --- Инициализация WebDriver ---
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)

# --- Подтверждение "It's you" ---
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(), 'Yes, confirm')] | //button[contains(text(), 'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except TimeoutException:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# --- Получение SMS-кода из Telegram (без таймаута) ---
def retrieve_sms_code(poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    logger.info("⏳ Ожидание SMS-кода из Telegram... Отправьте код в этот чат.")

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
            if not msg or str(msg['chat']['id']) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text', '')
            m = re.search(r"(\d{4,6})", text)
            if m:
                code = m.group(1)
                logger.info(f"✅ Получен код из Telegram: {code}")
                return code
        time.sleep(poll_interval)

# --- Запрос SMS и ввод кода ---
def try_sms_verification():
    try:
        # 1) Запросить SMS-код
        driver.save_screenshot("sms_verification_page.png")
        get_code_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        get_code_btn.click()
        logger.info("📲 'Get code' нажат, SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        # 2) Ждём загрузки формы ввода кода
        wait.until(EC.presence_of_element_located((By.XPATH,
            "//div[@class='ext-registration_cnt']//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]"
        )))
        driver.save_screenshot("sms_form_loaded.png")

        # 3) Ожидаем поле ввода кода
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@id='smsCode']"
        )))
        logger.info("📲 Ожидаю SMS-код. Отправьте его в Telegram.")
        driver.save_screenshot("sms_input_field.png")

        # 4) Получаем и вводим код
        code = retrieve_sms_code()
        inp.send_keys(code)
        driver.save_screenshot("sms_code_entered.png")

        # 5) Подтверждаем код (Next)
        next_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]//input[@type='submit' and @value='Next']"
        )))
        next_btn.click()
        logger.info("✅ Код введён и форма отправлена (Next).")
        driver.save_screenshot("sms_confirmed.png")
    except Exception as e:
        logger.error(f"❌ Проблема с SMS-верификацией: {e}")

# --- Основной сценарий авторизации ---
def main():
    try:
        logger.info("Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        # Вводим Email и пароль
        wait.until(EC.presence_of_element_located((By.NAME, 'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME, 'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        # Отправка формы входа
        logger.info("Нажимаю Войти...")
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        # Подтверждаем личность и вводим SMS-код
        try_confirm_identity()
        try_sms_verification()

        logger.info("Авторизация завершена.")
    except Exception as ex:
        logger.error(f"Критическая ошибка: {ex}")
        driver.save_screenshot("fatal_error.png")
    finally:
        driver.quit()
        logger.info("Драйвер закрыт.")

if __name__ == '__main__':
    main()
