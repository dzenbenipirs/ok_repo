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
            requests.post(self.api_url, data={
                "chat_id": self.chat_id,
                "text": self.format(record)
            })
        except:
            pass

logger = logging.getLogger("okru_bot")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(ch)
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
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

# 1) Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except TimeoutException:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# 2) SMS-верификация
def retrieve_sms_code(timeout=120, poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_id = None
    # сброс старых
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last_id = max(ids) + 1 if ids else None
    except:
        pass
    deadline = time.time() + timeout
    logger.info(f"⏳ Ожидание SMS-кода, таймаут {timeout}s...")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0, 'offset': last_id}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp['result']:
            last_id = upd['update_id'] + 1
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
    raise TimeoutException("SMS-код не получен (таймаут)")

def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("✅ Уже залогинен по data-l.")
        return
    logger.info("🔄 Начинаем SMS-верификацию.")
    driver.save_screenshot("sms_page.png")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value=\"Get code\"]"
    )))
    btn.click()
    logger.info("📲 Get code нажата.")
    driver.save_screenshot("sms_requested.png")
    time.sleep(1)
    body = driver.find_element(By.TAG_NAME,'body').text.lower()
    if "you are performing this action too often" in body:
        logger.error("🛑 Rate limit.")
        driver.save_screenshot("rate_limit.png")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    driver.save_screenshot("sms_input.png")
    code = retrieve_sms_code()
    inp.clear(); inp.send_keys(code)
    logger.info(f"✍️ Введён код {code}")
    driver.save_screenshot("sms_filled.png")
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value=\"Next\"]"
    )
    next_btn.click()
    logger.info("✅ SMS подтверждён.")
    driver.save_screenshot("sms_done.png")

# 3) Ожидание списка групп через #группы
def retrieve_groups(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_id = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last_id = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Ожидаю списка групп: #группы <urls> …")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last_id}).json()
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp['result']:
            last_id = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Chan: {text!r}")
            m = re.match(r"^#группы\s+(.+)$", text, re.IGNORECASE)
            if m:
                urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                if urls:
                    logger.info(f"✅ Группы: {urls}")
                    return urls
        time.sleep(poll_interval)

# 4) Ожидание команды #пост: ссылка+текст
def retrieve_post_content(poll_interval=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_id = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last_id = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Ожидаю команды #пост <video_url> <text> …")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last_id}).json()
        if not resp.get('ok'):
            time.sleep(poll_interval); continue
        for upd in resp['result']:
            last_id = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            full = msg.get('text','').strip()
            logger.info(f"📨 Cmd: {full!r}")
            m = re.match(r"^#пост\s+(.+)$", full, re.IGNORECASE|re.DOTALL)
            if m:
                content = m.group(1).strip()
                urls = re.findall(r"https?://\S+", content)
                if not urls:
                    logger.error("❌ Не нашёл URL видео в сообщении.")
                    continue
                video_url = urls[0]
                text = content.replace(video_url, "").strip()
                logger.info(f"✅ Извлекли video_url={video_url!r}, text={text!r}")
                return video_url, text
        time.sleep(poll_interval)

# 5) Постинг: сначала ссылка, ждём 5s, вставляем текст и жмём «Поделиться»
def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info(f"🚀 Открываю {post_url}")
    driver.get(post_url)
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click(); box.clear()
    logger.info(f"✍️ Вставляю ссылку: {video_url}")
    box.send_keys(video_url)
    logger.info("⏳ Жду 5 секунд для подтягивания видео…")
    time.sleep(5)
    logger.info(f"✍️ Добавляю текст: {text!r}")
    box.send_keys(" " + text)
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info(f"✅ Опубликовано в {group_url}")
    driver.save_screenshot(f"posted_{group_url.split('/')[-1]}.png")
    time.sleep(1)

# Основной сценарий
def main():
    try:
        logger.info("🚀 Открываю OK.RU…")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login.png")

        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("cred.png")

        logger.info("🔑 Логин…")
        driver.find_element(By.XPATH,"//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login.png")

        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Авторизация завершена.")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_content()

        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("🎉 Все посты отправлены.")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        driver.save_screenshot("fatal.png")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")

if __name__ == '__main__':
    main()
