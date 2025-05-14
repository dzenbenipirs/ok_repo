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

if not EMAIL or not PASSWORD:
    log.error("❌ Переменные окружения OK_EMAIL и OK_PASSWORD не заданы.")
    sys.exit(1)

options = uc.ChromeOptions()
options.add_argument('--headless=new')  # убери для отладки
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
options.add_argument('--start-maximized')
options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

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

def save_cookies():
    log.info("💾 Сохраняем cookies...")
    with open("cookies.json", "w") as f:
        json.dump(driver.get_cookies(), f)

def load_cookies():
    if os.path.exists("cookies.json"):
        log.info("🔄 Загружаем cookies...")
        driver.get("https://ok.ru/")
        with open("cookies.json", "r") as f:
            cookies = json.load(f)
        for cookie in cookies:
            if 'sameSite' in cookie:
                del cookie['sameSite']
            driver.add_cookie(cookie)
        driver.get("https://ok.ru/feed")
        time.sleep(3)

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

try:
    log.info("Запуск скрипта...")

    load_cookies()

    # Проверка авторизации через cookies
    driver.get("https://ok.ru/group/70000033095519/post")
    time.sleep(3)
    body_class = driver.find_element(By.TAG_NAME, "body").get_attribute("class")

    if "anonym" in body_class:
        log.info("🔐 Авторизация через cookies не удалась. Переходим к ручному входу.")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME, "st.email"))).send_keys(EMAIL)
        driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)

        login_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//div[contains(@class, 'login-form-actions')]//input[@type='submit']")
        ))
        login_btn.click()

        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")
        try_confirm_identity()

        # Проверка повторная
        driver.get("https://ok.ru/group/70000033095519/post")
        time.sleep(3)
        body_class = driver.find_element(By.TAG_NAME, "body").get_attribute("class")
        if "anonym" in body_class:
            log.error("❌ Не удалось авторизоваться. Страница недоступна.")
            driver.save_screenshot("not_logged_in.png")
            sys.exit(1)

        save_cookies()
        log.info("✅ Авторизация выполнена и сохранена.")

    else:
        log.info("✅ Авторизация через cookies успешна.")

    # Публикация постов
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
