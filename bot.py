import csv
import os
import time
import json
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

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

if not EMAIL or not PASSWORD:
    log.error("❌ Переменные окружения OK_EMAIL и OK_PASSWORD не заданы.")
    sys.exit(1)

options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
options.add_argument('--start-maximized')
options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

log.info("Запуск браузера...")
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

def load_cookies():
    if os.path.exists("cookies.json"):
        log.info("🔄 Загрузка cookies...")
        driver.get("https://ok.ru/")
        with open("cookies.json", "r") as f:
            cookies = json.load(f)
        for cookie in cookies:
            if 'sameSite' in cookie:
                del cookie['sameSite']
            driver.add_cookie(cookie)
        driver.get("https://ok.ru/feed")
        time.sleep(3)

def save_cookies():
    log.info("💾 Сохраняем cookies...")
    with open("cookies.json", "w") as f:
        json.dump(driver.get_cookies(), f)

def try_confirm_identity():
    try:
        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//input[@value='Yes, confirm'] | //button[contains(text(), 'Yes, confirm')]")
        ))
        confirm_btn.click()
        log.info("🔓 Подтверждение 'It’s you' пройдено.")
        time.sleep(2)
    except TimeoutException:
        log.info("✅ Подтверждение не требовалось.")

def login_if_needed():
    driver.get("https://ok.ru/")
    time.sleep(3)
    body_class = driver.find_element(By.TAG_NAME, "body").get_attribute("class")

    if "anonym" not in body_class:
        log.info("🔐 Уже авторизованы через cookies.")
        return

    log.info("🔑 Входим вручную...")
    wait.until(EC.presence_of_element_located((By.NAME, "st.email"))).send_keys(EMAIL)
    driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)

    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//div[contains(@class, 'login-form-actions')]//input[@type='submit']")
    ))
    login_btn.click()

    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")
    try_confirm_identity()

    # Проверка входа через переход на /post
    test_url = "https://ok.ru/group/70000033095519/post"
    driver.get(test_url)
    time.sleep(3)
    body_class = driver.find_element(By.TAG_NAME, "body").get_attribute("class")

    if "anonym" in body_class:
        log.error("❌ Вход не удался. OK требует подтверждение.")
        driver.save_screenshot("not_logged_in.png")
        sys.exit(1)

    log.info("✅ Авторизация подтверждена.")
    save_cookies()

try:
    load_cookies()
    login_if_needed()

    with open("posts.csv", newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            group_id = row.get('group_id')
            video_url = row.get('video_url')
            description = row.get('description')

            if not all([group_id, video_url, description]):
                log.warning("⛔️ Пропущена строка CSV: отсутствуют поля.")
                continue

            group_post_url = f"https://ok.ru/group/{group_id}/post"
            video_file = "video_temp.mp4"

            log.info(f"--- Публикация в группу: {group_post_url} ---")
            try:
                download_video(video_url, video_file)
            except Exception:
                continue

            driver.get(group_post_url)
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
    log.exception(f"❌ Критическая ошибка: {e}")
    driver.save_screenshot("fatal_error.png")

finally:
    driver.quit()
    log.info("Сессия завершена.")
