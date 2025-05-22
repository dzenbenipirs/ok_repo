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

    # 1) вставляем чисто URL и жмём Enter
    logger.info(f"✍️ Вставляю ссылку на видео: {video_url}")

    # 2) ждём, пока OK подтянет видео и удалит сам URL
    logger.info("⏳ Ожидаю, пока подтянется видео…")
    try:
        # здесь ждём появления любого блока с видео (может быть div с классом js-video-scope или блок превью)
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".js-video-scope, .posting_video-upload, .posting_tracks")
        ))
    except TimeoutException:
        logger.warning("⚠️ Видео не подтянулось за 15 сек, продолжаем…")

    # 3) вставляем текст
    logger.info(f"✍️ Вставляю текст: {text!r}")
    box.send_keys(" " + text)

    # 4) публикуем
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//button[@data-action='submit' and contains(@class,'js-pf-submit-btn')]"
    )))
    btn.click()
    logger.info(f"✅ Опубликовано в {group_url}")
    time.sleep(1)
