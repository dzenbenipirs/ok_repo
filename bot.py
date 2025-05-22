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

EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте все переменные OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID")
    sys.exit(1)

class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
    def emit(self, record):
        try:
            requests.post(self.url, data={
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
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("Подтверждение личности выполнено")
        time.sleep(1)
    except TimeoutException:
        logger.info("Страница подтверждения личности не показана")

def retrieve_sms_code(timeout=120, poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    # сброс старых
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
            time.sleep(poll_interval); continue
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp['result']:
            last = upd['update_id']+1
            msg = upd.get('message') or {}
            if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, re.IGNORECASE)
            if m:
                logger.info("SMS-код получен")
                return m.group(1)
        time.sleep(poll_interval)
    raise TimeoutException("SMS-код не получен")

def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("Уже залогинены, SMS не нужен")
        return
    logger.info("Запрашиваю SMS-код")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)
    if "you are performing this action too often" in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("Превышен лимит запросов SMS")
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
    logger.info("SMS-верификация пройдена")

def retrieve_groups(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None
    logger.info("Ожидаю списка групп (#группы ...)")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                t = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", t, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info("Группы получены")
                        return urls
        time.sleep(poll_interval)

def retrieve_post_text(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids)+1 if ids else None
    logger.info("Ожидаю команды #пост <url> <текст>")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id']+1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                t = msg.get('text','').strip()
                m = re.match(r"#пост\s+(.+)", t, re.IGNORECASE)
                if m:
                    rest = m.group(1).strip()
                    url_m = re.search(r"https?://\S+", rest)
                    if url_m:
                        video_url = url_m.group(0)
                        text = rest.replace(video_url, "").strip()
                        logger.info("Команда пост принята")
                        return video_url, text
        time.sleep(poll_interval)

def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info(f"Открываю {group_url}")
    driver.get(post_url)
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click()
    box.clear()

    # вставляем ссылку
    box.send_keys(video_url)
    logger.info("Ссылка вставлена, жду 5 секунд")
    time.sleep(5)

    # чистим вёрстку ссылки (если осталось)
    driver.execute_script(
        "arguments[0].querySelectorAll('a').forEach(e=>e.remove());",
        box
    )

    # вставляем текст
    box.send_keys(" " + text)
    logger.info("Текст вставлен")

    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info(f"Пост опубликован в {group_url}")
    time.sleep(1)

def main():
    try:
        logger.info("Старт авторизации")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)

        try_confirm_identity()
        try_sms_verification()
        logger.info("Авторизация успешна")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_text()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("Все посты отправлены")
    except Exception as e:
        logger.error("Ошибка в main")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("Драйвер закрыт")

if __name__ == '__main__':
    main()
