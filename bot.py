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
EMAIL            = os.environ.get("OK_EMAIL")
PASSWORD         = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")
if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логгер: консоль + Telegram (без текстов/ссылок)
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
wait   = WebDriverWait(driver, 20)

def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 Подтверждена личность")
        time.sleep(1)
    except:
        logger.info("ℹ️ Страница подтверждения личности не показана")

def retrieve_sms_code(timeout=120, poll=5):
    api  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids) + 1 if ids else None
    except:
        pass

    deadline = time.time() + timeout
    logger.info("⏳ Ожидаю SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0, 'offset': last}).json()
        except:
            time.sleep(poll); continue
        if not resp.get('ok'):
            time.sleep(poll); continue
        for u in resp['result']:
            last = u['update_id'] + 1
            msg = u.get('message') or u.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", msg.get('text','').strip(), re.IGNORECASE)
            if m:
                logger.info("✅ SMS-код получен")
                return m.group(1)
        time.sleep(poll)

    logger.error("❌ Таймаут SMS-кода")
    raise TimeoutException("SMS-код не получен")

def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("✅ Уже залогинен")
        return
    logger.info("🔄 Запрос SMS-кода")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click(); time.sleep(1)
    if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("🛑 Превышен лимит запросов")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear(); inp.send_keys(code)
    logger.info("✍️ Ввёл SMS-код")
    nxt = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    nxt.click()
    logger.info("✅ SMS-верификация успешна")

def retrieve_groups(poll=5):
    api  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass

    logger.info("⏳ Жду команды #группы")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                m = re.match(r"#группы\s+(.+)", msg.get('text','').strip(), re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info("✅ Получен список групп")
                        return urls
        time.sleep(poll)

def retrieve_post_info(poll=5):
    api  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass

    logger.info("⏳ Жду команды #пост")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#пост\s+(https?://ok\.ru/video/\d+)\s+(.+)", txt, re.IGNORECASE)
                if m:
                    logger.info("✅ Получена ссылка и текст для поста")
                    return m.group(1), m.group(2)
        time.sleep(poll)

def post_to_group(g_url, video_url, text):
    post_url = g_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю форму публикации")
    driver.get(post_url)

    box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "div[contenteditable='true']"
    )))
    box.click(); box.clear()

    # 1) Вставляем ссылку
    box.send_keys(video_url)
    logger.info("✍️ Ссылка вставлена")

    # 2) Ждём карточку видео
    logger.info("⏳ Жду появления видео-карточки")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
        "div.vid-card.vid-card__xl"
    )))

    # 3) Убираем в DOM все вхождения исходной ссылки
    driver.execute_script("""
        const el = arguments[0], url = arguments[1];
        el.innerHTML = el.innerHTML.split(url).join('');
    """, box, video_url)
    logger.info("🧹 Удалил ссылку из поля")

    # 4) Вставляем только текст
    box.send_keys(" " + text)
    logger.info("✍️ Текст вставлен")

    # 5) Публикуем
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "button.js-pf-submit-btn[data-action='submit']"
    )))
    btn.click()
    logger.info("🎉 Опубликовано")
    time.sleep(1)

def main():
    try:
        logger.info("🚀 Запуск")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Логин")
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Успешный вход")

        groups    = retrieve_groups()
        video_url, post_text = retrieve_post_info()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("✅ Все посты отправлены")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Завершено")

if __name__ == '__main__':
    main()
