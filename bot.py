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
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID")
    sys.exit(1)

# Логи в консоль + Телеграм (без контента сообщений)
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
    def emit(self, record):
        try:
            requests.post(self.url, data={"chat_id": self.chat_id, "text": self.format(record)})
        except:
            pass

logger = logging.getLogger("okru_bot")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
ch = logging.StreamHandler(sys.stdout); ch.setFormatter(fmt)
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID); tg.setFormatter(fmt)
logger.addHandler(ch); logger.addHandler(tg)

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

def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("✔ Подтверждение личности")
    except TimeoutException:
        logger.info("ℹ Нет подтверждения личности")

def retrieve_sms_code(timeout=120, interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        last = (max(u['update_id'] for u in init['result'])+1) if init.get('ok') and init['result'] else None
    except:
        pass
    deadline = time.time() + timeout
    logger.info("⏳ Жду SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        except:
            time.sleep(interval); continue
        if not resp.get('ok'):
            time.sleep(interval); continue
        for up in resp['result']:
            last = up['update_id']+1
            msg = up.get('message') or {}
            if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            txt = msg.get('text','').strip()
            if re.match(r"^(?:#код\s*)?\d{4,6}$", txt, re.IGNORECASE):
                logger.info("✔ SMS-код получен")
                return re.search(r"\d{4,6}", txt).group(0)
        time.sleep(interval)
    raise TimeoutException("SMS-код не пришёл")

def try_sms_verification():
    body = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in body and 'anonymMain' not in body:
        logger.info("✔ Уже залогинены")
        return
    logger.info("🔄 Запрос SMS-кода")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)
    if "too often" in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("❗ Лимит SMS-запросов")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear(); inp.send_keys(code)
    driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    ).click()
    logger.info("✔ SMS-верификация пройдена")

def retrieve_groups():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok') and init['result']:
        last = max(u['update_id'] for u in init['result'])+1
    logger.info("⏳ Жду #группы")
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
                        logger.info("✔ Группы получены")
                        return urls
        time.sleep(5)

def retrieve_post_text():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok') and init['result']:
        last = max(u['update_id'] for u in init['result'])+1
    logger.info("⏳ Жду #пост")
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
                        logger.info("✔ Команда #пост получена")
                        return video_url, text
        time.sleep(5)

def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю форму поста")
    driver.get(post_url)
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click(); box.clear()
    box.send_keys(video_url)
    logger.info("⏳ Жду появления карточки видео")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
        "div.vid-card.vid-card__xl"
    )))
    box.send_keys(" " + text)
    logger.info("✔ Вставил текст")
    wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    ))).click()
    logger.info("✔ Пост опубликован")
    time.sleep(1)

def main():
    try:
        logger.info("🚀 Начало авторизации")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("✔ Авторизация завершена")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_text()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("🎉 Все посты отправлены")
    except Exception:
        logger.error("❌ Критическая ошибка")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт")

if __name__ == '__main__':
    main()
