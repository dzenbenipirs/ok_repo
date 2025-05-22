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
from selenium.common.exceptions import TimeoutException

# Чтение учётных данных
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # ваш chat_id или group id

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Настройка логгера: консоль + Telegram
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

# WebDriver
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

# 1) Авторизация и SMS
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        time.sleep(1)
    except:
        logger.info("ℹ️ Страница 'It's you' не показана.")

def retrieve_sms_code(timeout=120, poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    # сбросить старые
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None

    deadline = time.time()+timeout
    logger.info("⏳ Ожидаю SMS-код...")
    while time.time()<deadline:
        resp = requests.get(api, params={'timeout':0,'offset':last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id'))!=TELEGRAM_USER_ID: continue
                txt = msg.get('text','').strip()
                logger.info(f"📨 SMS-код пришёл: {txt!r}")
                m = re.match(r"(\d{4,6})", txt)
                if m:
                    return m.group(1)
        time.sleep(poll)
    raise TimeoutException("SMS-код не получен")

def try_sms_verification():
    # проверяем data-l
    dl = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in dl and 'anonymMain' not in dl:
        logger.info("✅ Уже залогинен по data-l.")
        return

    logger.info("🔄 SMS-верификация...")
    driver.save_screenshot("sms_page.png")
    wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    ))).click()
    logger.info("📲 Get code нажат.")
    time.sleep(1)
    body = driver.find_element(By.TAG_NAME,'body').text.lower()
    if "too often" in body:
        logger.error("🛑 Rate limit на Get code.")
        sys.exit(1)

    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.send_keys(code)
    logger.info(f"✍️ Ввёл код {code}")
    driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    ).click()
    logger.info("✅ SMS подтверждён.")
    time.sleep(1)

# 2) Получаем список групп
def retrieve_groups():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None

    logger.info("⏳ Ожидаю #группы ...")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset':last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id'))!=TELEGRAM_USER_ID: continue
                txt = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", txt, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info(f"✅ Группы: {urls}")
                        return urls
        time.sleep(5)

# 3) Ждём видеофайл
def retrieve_video_file_id():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None

    logger.info("⏳ Ожидаю видеофайл...")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset':last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id'))!=TELEGRAM_USER_ID: continue
                if 'video' in msg or 'document' in msg:
                    fid = msg.get('video',{}).get('file_id') or msg.get('document',{}).get('file_id')
                    if fid:
                        logger.info(f"✅ File ID: {fid}")
                        return fid
        time.sleep(5)

# 4) Из file_id — прямая ссылка
def get_direct_url(file_id):
    # получаем file_path
    res = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
        params={'file_id': file_id}
    ).json()
    path = res['result']['file_path']
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}"
    logger.info(f"🖇️ Direct URL: {url}")
    return url

# 5) Ждём текст поста
def retrieve_post_text():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None

    logger.info("⏳ Ожидаю #пост ...")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset':last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id'))!=TELEGRAM_USER_ID: continue
                txt = msg.get('text','').strip()
                m = re.match(r"#пост\s+(.+)", txt, re.IGNORECASE)
                if m:
                    post = m.group(1)
                    logger.info(f"✅ Текст поста: {post!r}")
                    return post
        time.sleep(5)

# 6) Постинг
def post_to_group(group_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info(f"🚀 Открываю {post_url}")
    driver.get(post_url)
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click()
    box.clear()
    box.send_keys(text)
    logger.info("✍️ Ввёл текст + ссылку видео")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info("✅ Опубликовано")
    time.sleep(1)

# Основной поток
def main():
    try:
        # авторизация
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Логин...")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Авторизация завершена.")

        # этапы по очереди
        groups    = retrieve_groups()
        file_id   = retrieve_video_file_id()
        video_url = get_direct_url(file_id)
        post_txt  = retrieve_post_text()

        full_text = f"{video_url}\n\n{post_txt}"
        for g in groups:
            post_to_group(g, full_text)

        logger.info("🎉 Все выполнено.")
    except Exception as e:
        logger.error(f"🔥 Фатал: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
