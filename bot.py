
import csv
import os
import time
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

# Настройка логгера (в начале)
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
    log.error("Переменные окружения OK_EMAIL и OK_PASSWORD не заданы.")
    sys.exit(1)

log.info("Запуск бота...")
log.info(f"EMAIL найден: {EMAIL[:3]}***")

# Настройки браузера с undetected_chromedriver
options = uc.ChromeOptions()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
log.info("Создаём undetected_chromedriver...")
log.info("Запускаем undetected_chromedriver...")
driver = uc.Chrome(options=options)

def download_video(url, filename):
    try:
        log.info(f"Загрузка видео: {url}")
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info("Видео загружено.")
    except Exception as e:
        log.error(f"Ошибка при загрузке видео: {e}")

try:
    log.info("Открываем OK.RU...")
    driver.get("https://ok.ru/")
    time.sleep(3)

    log.info("Вводим логин и пароль...")
    driver.find_element(By.NAME, "st.email").send_keys(EMAIL)
    driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)
    driver.find_element(By.CLASS_NAME, "login-form-actions").click()
    time.sleep(5)

    with open("posts.csv", newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            group_url = row['group_url']
            video_url = row['video_url']
            description = row['description']
            video_file = "video_temp.mp4"

            log.info(f"--- Обработка группы: {group_url} ---")
            download_video(video_url, video_file)

            log.info(f"Переход в группу: {group_url}")
            driver.get(group_url)
            time.sleep(5)

            try:
                log.info("Открываем форму загрузки видео...")
                driver.find_element(By.XPATH, "//button[contains(., 'Видео')]").click()
                time.sleep(3)

                log.info("Загрузка видео...")
                upload_input = driver.find_element(By.XPATH, "//input[@type='file']")
                upload_input.send_keys(os.path.abspath(video_file))
                time.sleep(10)

                log.info("Ввод описания...")
                desc_field = driver.find_element(By.XPATH, "//textarea")
                desc_field.send_keys(description)
                time.sleep(1)

                log.info("Публикация поста...")
                publish_button = driver.find_element(By.XPATH, "//button[contains(., 'Опубликовать')]")
                publish_button.click()
                log.info("✅ Пост опубликован!")

            except NoSuchElementException as e:
                log.error(f"❌ Элемент не найден: {e}")

            finally:
                if os.path.exists(video_file):
                    os.remove(video_file)
                    log.info("Временный файл удалён.")
                time.sleep(5)

except Exception as e:
    log.exception(f"Ошибка выполнения скрипта: {e}")

finally:
    driver.quit()
    log.info("Сессия завершена.")
