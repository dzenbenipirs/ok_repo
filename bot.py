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

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # Ваш chat_id или group id

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
            requests.post(self.api_url, data={"chat_id": self.chat_id, "text": self.format(record)})
        except:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
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

# Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(),'Yes, confirm')] | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# Получение SMS-кода из Telegram
def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    try:
        init = requests.get(api_url, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last_update = max(ids) + 1 if ids else None
    except:
        last_update = None
    deadline = time.time() + timeout
    logger.info(f"⏳ Ожидание SMS-кода, таймаут {timeout}s...")
    while time.time() < deadline:
        try:
            resp = requests.get(api_url, params={'timeout':0,'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval); continue
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp['result']:
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Получено: {text!r}")
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Код: {code}")
                return code
        time.sleep(poll_interval)
    logger.error("❌ Таймаут ожидания SMS-кода")
    raise TimeoutException("SMS-код не получен")

# SMS-верификация
def try_sms_verification():
    try:
        data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
        if 'userMain' in data_l and 'anonymMain' not in data_l:
            logger.info("✅ Уже залогинен по data-l.")
            return
        logger.info("🔄 Начинаем SMS-верификацию.")
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        btn.click()
        logger.info("📲 Get code нажата.")
        time.sleep(1)
        if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
            logger.error("🛑 Rate limit.")
            sys.exit(1)
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@id='smsCode' or contains(@name,'smsCode')]"
        )))
        code = retrieve_sms_code()
        inp.clear(); inp.send_keys(code)
        logger.info(f"✍️ Введён код {code}")
        next_btn = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Next']")
        next_btn.click()
        logger.info("✅ SMS подтверждён.")
    except Exception as e:
        logger.error(f"❌ SMS error: {e}")
        sys.exit(1)

# Ожидание списка групп (#группы)
def retrieve_groups(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids) + 1 if ids else None

    logger.info("⏳ Ожидаю #группы ...")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                text = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", text, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info(f"✅ Группы: {urls}")
                        return urls
        time.sleep(poll_interval)

# Ожидание видео и текста (#пост <url> <text>)
def retrieve_post_text(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    init = requests.get(api, params={'timeout':0}).json()
    if init.get('ok'):
        ids = [u['update_id'] for u in init['result']]
        last = max(ids) + 1 if ids else None

    logger.info("⏳ Ожидаю #пост <url> <текст> ...")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                text = msg.get('text','').strip()
                m = re.match(r"#пост\s+(.+)", text, re.IGNORECASE)
                if m:
                    rest = m.group(1).strip()
                    # выделяем первую ссылку и остальной текст
                    url_match = re.search(r"https?://\S+", rest)
                    if url_match:
                        video_url = url_match.group(0)
                        post_text = rest.replace(video_url, "").strip()
                        logger.info(f"✅ Видео: {video_url}, текст: {post_text!r}")
                        return video_url, post_text
        time.sleep(poll_interval)

# Постинг в группу: сначала ссылка, ждём 5с, потом текст и publish
def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info(f"🚀 Открываю {post_url}")
    driver.get(post_url)
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click()
    box.clear()
    # вставляем ссылку
    box.send_keys(video_url)
    logger.info("✍️ Вставлена ссылка, ждём 5 сек...")
    time.sleep(5)
    # затем вставляем текст
    box.send_keys(" " + text)
    logger.info("✍️ Вставлен текст поста.")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info(f"✅ Опубликовано в {group_url}")
    time.sleep(1)

# Основной сценарий
def main():
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Вход...")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Авторизация успешна!")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_text()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("🎉 Все посты отправлены.")
    except Exception as e:
        logger.error(f"🔥 Ошибка в main: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
