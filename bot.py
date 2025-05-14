import csv
import os
import time
import requests
import logging
import sys
import threading
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Логгер
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("bot.log", mode='w'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # В виде строки

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    log.error("❌ Отсутствуют необходимые переменные окружения.")
    sys.exit(1)

# Настройка браузера
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
options.add_argument('--start-maximized')
options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)

# Telegram auth sync
sms_code_received = threading.Event()
sms_code_value = None

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Жду код для подтверждения входа.")

def handle_code(update: Update, context: CallbackContext):
    global sms_code_value
    if str(update.effective_user.id) != TELEGRAM_USER_ID:
        update.message.reply_text("❌ У вас нет доступа.")
        return
    sms_code_value = update.message.text.strip()
    sms_code_received.set()
    update.message.reply_text("✅ Код принят.")

def run_telegram_bot():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_code))
    updater.start_polling()

def download_video(url, filename):
    try:
        log.info(f"Загрузка видео: {url}")
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info("✅ Видео загружено.")
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке видео: {e}")
        raise

def try_confirm_identity():
    try:
        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//input[@value='Yes, confirm'] | //button[contains(text(), 'Yes, confirm')]")
        ))
        confirm_btn.click()
        log.info("🔓 Подтверждение 'It’s you' пройдено.")
        time.sleep(2)
        driver.save_screenshot("after_confirm_identity.png")
    except TimeoutException:
        log.info("✅ Подтверждение 'It’s you' не требовалось.")

def wait_for_sms_code():
    try:
        code_button = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Get code') or contains(., 'Send code')]")
        ))
        code_button.click()
        log.info("📲 Нажата кнопка отправки кода.")
        driver.save_screenshot("code_requested.png")
    except TimeoutException:
        log.warning("🚫 Не найдена кнопка 'Get code'.")

    log.info("⏳ Ожидаем код от пользователя в Telegram...")
    sms_code_received.wait(timeout=300)
    if not sms_code_value:
        log.error("❌ Код не получен в течение времени ожидания.")
        sys.exit(1)

    try:
        code_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='tel']")))
        code_input.send_keys(sms_code_value)
        submit_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Continue') or contains(., 'Submit')]")
        ))
        submit_btn.click()
        log.info("✅ Код подтверждён.")
        driver.save_screenshot("code_entered.png")
    except Exception as e:
        log.error(f"❌ Ошибка при вводе кода: {e}")
        driver.save_screenshot("code_error.png")
        sys.exit(1)

# Запуск Telegram бота в фоновом потоке
telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
telegram_thread.start()

try:
    log.info("Открываем OK.RU...")
    driver.get("https://ok.ru/")
    wait.until(EC.presence_of_element_located((By.NAME, "st.email"))).send_keys(EMAIL)
    driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)

    log.info("Нажимаем кнопку входа...")
    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//div[contains(@class, 'login-form-actions')]//input[@type='submit']")))
    login_btn.click()

    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")

    try_confirm_identity()
    wait_for_sms_code()

    test_post_url = "https://ok.ru/group/70000033095519/post"
    log.info(f"Проверка входа через переход: {test_post_url}")
    driver.get(test_post_url)
    time.sleep(5)

    body_class = driver.find_element(By.TAG_NAME, "body").get_attribute("class")
    log.info(f"Класс <body>: {body_class}")

    if "anonym" in body_class:
        log.error("❌ Не авторизован. OK.ru перенаправил на страницу ошибки.")
        driver.save_screenshot("not_logged_in.png")
        sys.exit(1)

    log.info("✅ Пользователь авторизован. Доступ к постингу подтверждён.")

    with open("posts.csv", newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            group_post_url = row['group_post_url']
            video_url = row['video_url']
            description = row['description']
            video_file = "video_temp.mp4"

            log.info(f"--- Публикация в группу: {group_post_url} ---")
            try:
                download_video(video_url, video_file)
            except Exception:
                continue

            driver.get(group_post_url)
            log.info(f"Перешли к публикации: {group_post_url}")
            time.sleep(5)

            try:
                video_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
                video_input.send_keys(os.path.abspath(video_file))
                log.info("🎞️ Видео загружается...")
                time.sleep(10)

                desc_field = driver.find_element(By.XPATH, "//textarea")
                desc_field.send_keys(description)
                time.sleep(1)

                publish_button = driver.find_element(By.XPATH, "//button[contains(., 'Опубликовать')]")
                publish_button.click()
                log.info("✅ Пост опубликован!")

            except Exception as e:
                log.error(f"❌ Ошибка при публикации: {e}")
                driver.save_screenshot("post_error.png")

            finally:
                if os.path.exists(video_file):
                    os.remove(video_file)
                    log.info("🧹 Временный файл удалён.")
                time.sleep(5)

except Exception as e:
    log.exception(f"❌ Критическая ошибка выполнения скрипта: {e}")
    driver.save_screenshot("fatal_error.png")

finally:
    driver.quit()
    log.info("Сессия завершена.")
