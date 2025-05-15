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
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
# Telegram-логгер
tg_handler = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg_handler.setFormatter(formatter)
logger.addHandler(tg_handler)

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

# Шаг 1: Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# Шаг 2: Получение SMS-кода из Telegram по формату "#код 123456" с 2-минутным таймаутом
def retrieve_sms_code(timeout=120, poll_interval=5):
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

    deadline = time.time() + timeout
    logger.info(f"⏳ Ожидание SMS-кода '#код 123456' (таймаут {timeout} сек)...")
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
            text = msg.get('text', '').strip()
            logger.info(f"📨 Получено сообщение: {text!r}")
            m = re.search(r"^#код\s+(\d{4,6})", text, flags=re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Найден код: {code}")
                return code
        time.sleep(poll_interval)

    logger.error("❌ Таймаут ожидания SMS-кода истек.")
    raise TimeoutException("Не получен SMS-код в течение заданного времени")

# Шаг 3: Запрос и ввод SMS-кода
def try_sms_verification():
    try:
        # Запрос кода
        driver.save_screenshot("sms_verification_page.png")
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        btn.click()
        logger.info("📲 'Get code' нажат, SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        # Ждём форму ввода кода
        logger.info("🔄 Ожидаю форму для ввода SMS-кода...")
        while True:
            try:
                form = driver.find_element(By.XPATH,
                    "//div[@class='ext-registration_cnt']//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]"
                )
                inp = form.find_element(By.ID, "smsCode")
                if inp.is_displayed():
                    logger.info("👀 Поле для ввода SMS-кода появилось.")
                    driver.save_screenshot("sms_input_field.png")
                    break
            except NoSuchElementException:
                pass
            time.sleep(1)

        # Получаем и вводим код
        code = retrieve_sms_code()
        inp.clear()
        inp.send_keys(code)
        logger.info(f"✍️ Код введён: {code}")
        driver.save_screenshot("sms_code_entered.png")

        # Подтверждаем
        next_btn = form.find_element(By.XPATH,
            ".//input[@type='submit' and @value='Next']"
        )
        next_btn.click()
        logger.info("✅ SMS-код подтверждён, нажата кнопка 'Next'.")
        driver.save_screenshot("sms_confirmed.png")
    except TimeoutException:
        logger.error("❌ Не удалось получить SMS-код в течение 2 минут.")
        driver.save_screenshot("sms_timeout.png")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Ошибка SMS-верификации: {e}")
        sys.exit(1)

# Основной сценарий авторизации
def main():
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        # Ввод логина и пароля
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        # Отправка формы
        logger.info("🔑 Отправляю форму логина...")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        # Identity и SMS-верификация
        try_confirm_identity()
        try_sms_verification()

        logger.info("🎉 Авторизация завершена.")
    except Exception as ex:
        logger.error(f"🔥 Критическая ошибка: {ex}")
        driver.save_screenshot("fatal_error.png")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
