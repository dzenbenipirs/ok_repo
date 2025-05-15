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
from selenium.common.exceptions import NoSuchElementException

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
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
telegram_handler = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
telegram_handler.setFormatter(formatter)
logger.addHandler(telegram_handler)

# Инициализация WebDriver
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)

# Шаг 1: "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(),'Yes, confirm')] | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# Шаг 2: Получение и вывод всех сообщений из Telegram (для отладки)
def debug_print_updates():
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        resp = requests.get(api_url, params={'timeout': 0}).json()
        logger.info(f"📨 Все сообщения в чате: {resp}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка получения getUpdates: {e}")

# Шаг 3: Запрос кода и отладка получения из Telegram
def try_sms_verification():
    try:
        # 3.1) Ждём и кликаем 'Get code'
        driver.save_screenshot("sms_verification_page.png")
        get_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        get_btn.click()
        logger.info("📲 'Get code' нажат, SMS запрошен.")
        driver.save_screenshot("sms_requested.png")

        # 3.2) Ждём форму ввода кода
        logger.info("🔄 Ожидаю форму ввода SMS-кода...")
        while True:
            try:
                form = driver.find_element(By.XPATH,
                    "//div[@class='ext-registration_cnt']//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]"
                )
                inp = form.find_element(By.ID, "smsCode")
                if inp.is_displayed():
                    driver.save_screenshot("sms_input_field.png")
                    logger.info("👀 Поле для кода появилось.")
                    break
            except NoSuchElementException:
                pass
            time.sleep(1)

        # 3.3) Отладочный вывод всех сообщений из Telegram
        debug_print_updates()

        # Завершаем скрипт после вывода сообщений
        logger.info("🛑 Завершаю после вывода всех сообщений for debugging.")
        driver.quit()
        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Проблема при запросе SMS или отладке: {e}")
        driver.quit()
        sys.exit(1)

# Основной сценарий авторизации
def main():
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        # Логин и пароль
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        # Отправляем форму
        logger.info("🔑 Отправляю форму логина...")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        # Identity + SMS отладка
        try_confirm_identity()
        try_sms_verification()

        logger.info("🎉 Авторизация завершена.")
    except Exception as ex:
        logger.error(f"🔥 Критическая ошибка: {ex}")
        driver.save_screenshot("fatal_error.png")
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
