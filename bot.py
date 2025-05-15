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
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # теперь именно USER_ID

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логирование в консоль и Telegram
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
        except Exception:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
# Консоль
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)
logger.addHandler(ch)
# Telegram
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(fmt)
logger.addHandler(tg)

# Запуск Chrome
opts = uc.ChromeOptions()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--disable-gpu')
opts.add_argument('--window-size=1920,1080')
driver = uc.Chrome(options=opts)
wait = WebDriverWait(driver, 20)

# 1) «It's you»
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

# 2) Получение SMS-кода
# --- Получение SMS-кода из Telegram (с логом getUpdates) ---
def retrieve_sms_code(poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    logger.info("⏳ Ожидание SMS-кода в Telegram... Отправьте код в этот чат.")

    # Сбрасываем старые апдейты
    try:
        init = requests.get(api_url, params={'timeout': 0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            if ids:
                last_update = max(ids) + 1
    except Exception:
        last_update = None

    while True:
        try:
            resp = requests.get(api_url, params={'timeout': 0, 'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue

        # Логируем весь ответ, чтобы видеть, что реально приходит
        logger.info(f"🔎 getUpdates вернул: {resp}")

        if not resp.get('ok'):
            time.sleep(poll_interval)
            continue

        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg['chat']['id']) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text', '')
            match = re.search(r"(\d{4,6})", text)
            if match:
                code = match.group(1)
                logger.info(f"✅ Найден код в сообщении: {text!r} → {code}")
                return code

        time.sleep(poll_interval)


# 3) Запрос и ввод SMS-кода
def try_sms_verification():
    try:
        # 3.1) Нажимаем «Get code»
        driver.save_screenshot("sms_verification_page.png")
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        btn.click()
        logger.info("📲 'Get code' нажат, SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        # 3.2) Ждём появления формы ввода…
        logger.info("🔄 Ожидаю форму ввода SMS-кода…")
        while True:
            try:
                form = driver.find_element(By.XPATH,
                    "//div[@class='ext-registration_cnt']//form[contains(@action,'AnonymUnblockVerifyPhoneCodeOldPhone')]"
                )
                inp = form.find_element(By.ID, "smsCode")
                if inp.is_displayed():
                    logger.info("👀 Поле для кода появилось.")
                    driver.save_screenshot("sms_input_field.png")
                    break
            except NoSuchElementException:
                pass
            time.sleep(1)

        # 3.3) Дожидаемся кода из Telegram
        code = retrieve_sms_code()
        inp.clear()
        inp.send_keys(code)
        logger.info(f"✍️ Код введён: {code}")
        driver.save_screenshot("sms_code_entered.png")

        # 3.4) Нажимаем «Next»
        next_btn = form.find_element(By.XPATH,
            ".//input[@type='submit' and @value='Next']"
        )
        next_btn.click()
        logger.info("✅ Код подтверждён, нажал 'Next'.")
        driver.save_screenshot("sms_confirmed.png")

    except Exception as e:
        logger.error(f"❌ Проблема с SMS-верификацией: {e}")

# Основной сценарий
def main():
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        # Ввод учётных
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        # Входим
        logger.info("🔑 Отправляю форму входа...")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        # Подтвердить identity + SMS
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
