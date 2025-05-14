import csv
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

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")

# Telegram bot settings
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_USER_ID")

if not EMAIL or not PASSWORD:
    log.error("❌ Переменные окружения OK_EMAIL и OK_PASSWORD не заданы.")
    sys.exit(1)

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    log.error("❌ Переменные окружения TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы.")
    sys.exit(1)

log.info("Запуск бота...")
log.info(f"EMAIL найден: {EMAIL[:3]}***")

options = uc.ChromeOptions()
options.add_argument('--headless=new')  # Убери для отладки
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
options.add_argument('--start-maximized')
options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

log.info("Создаём undetected_chromedriver...")
driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 20)


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


def retrieve_sms_code_via_telegram(timeout=120, poll_interval=5):
    """
    Ожидаем SMS-код: пользователь вручную отправляет код боту.
    Функция опрашивает getUpdates Telegram Bot API и возвращает первый найденный 4-6 значный код.
    """
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    deadline = time.time() + timeout
    last_update_id = None

    log.info("⏳ Ожидание кода в Telegram...")
    while time.time() < deadline:
        resp = requests.get(api_url, params={
            'timeout': 0,
            'offset': last_update_id
        }).json()
        if not resp.get('ok'):
            log.warning("⚠️ Ошибка при getUpdates: %s", resp)
            time.sleep(poll_interval)
            continue

        for upd in resp.get('result', []):
            last_update_id = upd['update_id'] + 1
            msg = upd.get('message')
            if not msg or str(msg['chat']['id']) != TELEGRAM_CHAT_ID:
                continue

            text = msg.get('text', '')
            match = re.search(r'(\d{4,6})', text)
            if match:
                code = match.group(1)
                log.info(f"📥 Принят код из Telegram: {code}")
                return code

        time.sleep(poll_interval)

    log.error(f"❌ Не получили код в Telegram за {timeout} секунд")
    raise TimeoutException("SMS код не пришёл в Telegram")


def try_sms_verification():
    try:
        # 1) Запросить SMS-код
        get_code_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Get code')]")
        ))
        get_code_btn.click()
        log.info("📲 Запрошен SMS-код через Get code")

        # 2) Ждём появления поля ввода OTP
        code_input = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input[@name='otp'] | //input[@type='text' and contains(@placeholder, 'код')]")
        ))

        # 3) Получаем код из Telegram и вводим
        sms_code = retrieve_sms_code_via_telegram()
        code_input.send_keys(sms_code)

        # 4) Подтверждаем ввод
        submit_btn = driver.find_element(
            By.XPATH, "//button[contains(., 'Submit') or contains(., 'Подтвердить')]"
        )
        submit_btn.click()
        log.info("✅ SMS-код введён успешно")
        time.sleep(2)
    except (TimeoutException, NoSuchElementException):
        log.info("ℹ️ SMS-верификация не потребовалась или не найдена.")


try:
    # Вход в OK.RU
    log.info("Открываем OK.RU...")
    driver.get("https://ok.ru/")
    wait.until(EC.presence_of_element_located((By.NAME, "st.email"))).send_keys(EMAIL)
    driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)

    log.info("Нажимаем кнопку входа...")
    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//div[contains(@class, 'login-form-actions')]//input[@type='submit']")
    ))
    login_btn.click()

    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")

    # Подтверждаем личность
    try_confirm_identity()
    # Обработка SMS через Telegram
    try_sms_verification()

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
