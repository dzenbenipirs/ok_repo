import csv
import os
import time
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

# Получение логина/пароля из переменных окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")

if not EMAIL or not PASSWORD:
    log.error("❌ Переменные окружения OK_EMAIL и OK_PASSWORD не заданы.")
    sys.exit(1)

log.info("Запуск бота...")
log.info(f"EMAIL найден: {EMAIL[:3]}***")

# Настройка браузера
options = uc.ChromeOptions()
# Оставляем headless для CI, можно отключить для локального запуска
options.add_argument('--headless=new')
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

try:
    # Вход в OK.RU
    log.info("Открываем OK.RU...")
    driver.get("https://ok.ru/")
    wait.until(EC.presence_of_element_located((By.NAME, "st.email"))).send_keys(EMAIL)
    driver.find_element(By.NAME, "st.password").send_keys(PASSWORD)

    # Нажимаем на настоящую кнопку входа внутри login-form-actions
    log.info("Нажимаем кнопку входа...")
    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//div[contains(@class, 'login-form-actions')]//input[@type='submit']")
    ))
    login_btn.click()

    time.sleep(2)
    driver.save_screenshot("after_login_submit.png")

    # Проверка успешного входа
    try:
        wait.until(EC.presence_of_element_located((By.ID, "hook_Block_TopUserMenu")))
        log.info("✅ Успешный вход. Пользователь авторизован.")
    except TimeoutException:
        log.error("❌ Не удалось войти. Возможно, неправильный логин/пароль или капча.")
        driver.save_screenshot("login_failed.png")
        sys.exit(1)

    # Чтение CSV и публикация постов
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
