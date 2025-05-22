import os
import time
import re
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логгер: консоль + Telegram (без ссылок и текста поста)
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
        except:
            pass

logger = logging.getLogger("okru_bot")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(fmt)
logger.addHandler(ch)
logger.addHandler(tg)

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

def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(),'Yes, confirm')] | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("Подтверждение личности прошло")
        time.sleep(1)
    except:
        logger.info("Нет страницы подтверждения личности")

def retrieve_sms_code(timeout=120, poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass
    deadline = time.time() + timeout
    logger.info("Ожидаю SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        except:
            time.sleep(poll)
            continue
        if resp.get('ok'):
            for upd in resp['result']:
                last = upd['update_id'] + 1
                msg = upd.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                text = msg.get('text','').strip()
                m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, re.IGNORECASE)
                if m:
                    logger.info("SMS-код получен")
                    return m.group(1)
        time.sleep(poll)
    logger.error("Не получили SMS-код")
    raise TimeoutException("SMS-код не получен")

def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("Уже залогинены")
        return
    logger.info("Начинаю SMS-верификацию")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)
    if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("Rate limit на SMS")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear()
    inp.send_keys(code)
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    next_btn.click()
    logger.info("SMS-верификация завершена")

def retrieve_groups(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("Жду команды #группы")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", txt, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info("Список групп получен")
                        return urls
        time.sleep(poll)

def retrieve_post_text(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("Жду команды #пост")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#пост\s+(.+)", txt, re.IGNORECASE)
                if m:
                    rest = m.group(1).strip()
                    url_m = re.search(r"https?://\S+", rest)
                    if url_m:
                        vid = url_m.group(0)
                        body = rest.replace(vid, "").strip()
                        logger.info("Информация для поста получена")
                        return vid, body
        time.sleep(poll)

def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    driver.get(post_url)
    logger.info("Открыта страница постинга")
    fld = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "div[contenteditable='true']"
    )))
    fld.click()
    fld.clear()
    # вставляем ссылку
    fld.send_keys(video_url)
    logger.info("Ссылка вставлена")
    # ждём появления карточки
    logger.info("Жду видео-карточку")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
        "div.vid-card.vid-card__xl"
    )))
    # по строкам вставляем текст
    logger.info("Вставляю текст")
    lines = text.split("\n")
    for line in lines:
        fld.send_keys(line)
        fld.send_keys(Keys.SHIFT, Keys.ENTER)
        time.sleep(5)
    # публикуем
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "button.js-pf-submit-btn[data-action='submit']"
    )))
    btn.click()
    logger.info("Пост опубликован")
    time.sleep(1)

def main():
    try:
        logger.info("Запуск бота")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("Успешный вход")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_text()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("Все посты отправлены")
    except Exception as e:
        logger.error("Ошибка выполнения")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("Бот завершил работу")

if __name__ == '__main__':
    main()
