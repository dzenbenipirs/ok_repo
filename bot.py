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
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # переименовано

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Настройка логгера с отправкой сообщений в Telegram
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
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(formatter)
logger.addHandler(tg)

# Настройка Chrome WebDriver
driver_opts = uc.ChromeOptions()
driver_opts.add_argument('--headless=new')
driver_opts.add_argument('--no-sandbox')
driver_opts.add_argument('--disable-dev-shm-usage')
driver_opts.add_argument('--disable-gpu')
driver_opts.add_argument('--window-size=1920,1080')

driver = uc.Chrome(options=driver_opts)
wait = WebDriverWait(driver, 20)

# Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(), 'Yes, confirm')]"
            " | //button[contains(text(), 'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except TimeoutException:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# Получение SMS-кода из Telegram

def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    deadline = time.time() + timeout
    last_update = None
    logger.info("⏳ Ожидание SMS-кода...")

    while time.time() < deadline:
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
                logger.info(f"📥 Код получен: {code}")
                return code
        time.sleep(poll_interval)
    raise TimeoutException("Не получен SMS-код в Telegram")

# Запрос и ввод SMS-кода
def try_sms_verification():
    try:
        # 1) Запрос SMS-кода
        driver.save_screenshot("sms_verification_page.png")
        send_sms_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//form[contains(@action,'AnonymUnblockConfirmPhone')]/div//input[@type='submit' and @value='Get code']"
        )))
        send_sms_btn.click()
        logger.info("📲 SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        # 2) Ожидаем форму ввода кода
        wait.until(EC.presence_of_element_located((By.XPATH,
            "//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]"
        )))

        # 3) Ждём поле ввода кода
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@name='st.r.smsCode' and @id='smsCode']"
        )))
        driver.save_screenshot("sms_input_field.png")
        logger.info("📲 Скрипт ожидает SMS-код. Отправьте его в Telegram.")

        # 4) Получаем и вводим код
        code = retrieve_sms_code()
        inp.send_keys(code)
        driver.save_screenshot("sms_code_entered.png")

        # 5) Подтверждаем код (Next)
        next_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Next']"
        )))
        next_btn.click()
        logger.info("✅ SMS-код введён и отправлен.")
        driver.save_screenshot("sms_confirmed.png")
    except TimeoutException:
        logger.error("❌ Не удалось найти форму или элементы SMS-верификации.")
    except Exception as e:
        logger.error(f"❌ Ошибка SMS-верификации: {e}")

# Основной сценарий авторизации
def main():
    try:
        logger.info("Открываем OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        # Ввод Email и пароля
        wait.until(EC.presence_of_element_located((By.NAME, 'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME, 'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        # Отправка формы
        logger.info("Отправляем форму входа...")
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        # Подтверждение личности и SMS-верификация
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
