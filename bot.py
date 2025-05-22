from selenium.webdriver.common.keys import Keys

def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info(f"🚀 Открываю {post_url}")
    driver.get(post_url)

    # ждём появление редактора
    box = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//div[@contenteditable='true']"
    )))
    box.click()
    box.clear()

    # 1) вставляем чисто URL
    logger.info(f"✍️ Вставляю ссылку на видео: {video_url}")
    box.send_keys(video_url)

    # 2) ждём 5 секунд, чтобы OK подтянул видео по ссылке
    logger.info("⏳ Жду 5 секунд для подтягивания видео…")
    time.sleep(5)

    # 3) вставляем текст
    logger.info(f"✍️ Вставляю текст: {text!r}")
    box.send_keys(" " + text)

    # 4) публикуем
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info(f"✅ Опубликовано в {group_url}")
    driver.save_screenshot(f"posted_{group_url.split('/')[-1]}.png")
    time.sleep(1)
