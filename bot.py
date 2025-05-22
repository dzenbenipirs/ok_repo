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
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логгер: консоль + Telegram (без текстов и ссылок)
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
    logger.info("⏳ Ожидаю SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        except:
            time.sleep(poll)
            continue

        if not resp.get('ok'):
            time.sleep(poll)
            continue

        for upd in resp['result']:
            last = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue

            txt = msg.get('text','').strip()
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", txt, re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info("✅ Код получен")
                return code

        time.sleep(poll)

    logger.error("❌ Таймаут SMS-кода")
    raise TimeoutException("SMS-код не получен")

def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("✅ Уже залогинен")
        return

    logger.info("🔄 Запрашиваю SMS-код")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)

    if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("🛑 Rate limit")
        sys.exit(1)

    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear()
    inp.send_keys(code)
    logger.info("✍️ Ввёл SMS-код")
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    next_btn.click()
    logger.info("✅ SMS-верификация успешна")

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

    logger.info("⏳ Жду команду #группы")
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
                        logger.info("✅ Группы получены")
                        return urls
        time.sleep(poll)

def retrieve_post_info(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init['result']]
            last = max(ids)+1 if ids else None
    except:
        pass

    logger.info("⏳ Жду команду #пост")
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
                        txt_body = rest.replace(vid, "").strip()
                        logger.info("✅ Пост-инфо получено")
                        return vid, txt_body
        time.sleep(poll)

def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю страницу постинга")
    driver.get(post_url)

    # Вставляем ссылку
    box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "div[contenteditable='true']"
    )))
    box.click()
    box.clear()
    box.send_keys(video_url)
    logger.info("✍️ Ссылка вставлена")

    # Ждем карточку превью
    logger.info("⏳ Жду карточку видео")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
        "div.vid-card.vid-card__xl"
    )))

    # Удаляем текстовый узел с URL, чтобы не было дублирования
    driver.execute_script("""
    var box = arguments[0], url = arguments[1];
    var nodes = box.childNodes;
    for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n.nodeType === Node.TEXT_NODE && n.textContent.includes(url)) {
            box.removeChild(n);
            break;
        }
    }
    """, box, video_url)
    logger.info("🗑️ Текст ссылки удалён")

    # Вставляем остальной текст (без ссылки)
    box.send_keys(" " + text)
    logger.info("✍️ Текст вставлен")

    # Публикуем
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "button.js-pf-submit-btn[data-action='submit']"
    )))
    btn.click()
    logger.info("✅ Опубликовано")
    time.sleep(1)

def main():
    try:
        logger.info("🚀 Начинаю работу")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Логин")
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)

        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Вход выполнен")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_info()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("🎉 Все задачи выполнены")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Завершено")

if __name__ == '__main__':
    main()
