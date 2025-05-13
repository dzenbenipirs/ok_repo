
import csv
import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

def download_video(url, filename):
    r = requests.get(url, stream=True)
    with open(filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

try:
    driver.get("https://ok.ru/")
    time.sleep(3)
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

            print(f"Загружаем видео: {video_url}")
            download_video(video_url, video_file)

            print(f"Переход в группу: {group_url}")
            driver.get(group_url)
            time.sleep(5)

            driver.find_element(By.XPATH, "//button[contains(., 'Видео')]").click()
            time.sleep(3)

            upload_input = driver.find_element(By.XPATH, "//input[@type='file']")
            upload_input.send_keys(os.path.abspath(video_file))
            time.sleep(10)

            desc_field = driver.find_element(By.XPATH, "//textarea")
            desc_field.send_keys(description)
            time.sleep(1)

            publish_button = driver.find_element(By.XPATH, "//button[contains(., 'Опубликовать')]")
            publish_button.click()
            print(f"Пост опубликован в {group_url}")

            time.sleep(5)
            os.remove(video_file)

finally:
    driver.quit()
