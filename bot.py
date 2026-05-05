import os
import json
import logging
import requests

# ---------- НАСТРОЙКИ ----------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# ---------- ФИЛЬТРЫ ПОИСКА ----------
AREA = "חיפה"
MAX_PRICE = 1_500_000
MIN_ROOMS = 3
MAX_ROOMS = 5

SENT_IDS_FILE = "sent_ids.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def tg_send_message(text):
    """Отправка сообщения в Telegram (только если заданы токен и chat_id)."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.info("Telegram не настроен – пропускаю отправку: %s", text[:100])
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
        logger.info("Сообщение отправлено в Telegram")
    except Exception as e:
        logger.error("Ошибка отправки в Telegram: %s", e)

def fetch_madlan_listings():
    """
    GET-запрос к странице поиска Madlan, извлечение JSON из HTML.
    """
    url = "https://www.madlan.co.il/for-sale/%D7%97%D7%99%D7%A4%D7%94-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
    params = {
        "priceTo": MAX_PRICE,
        "roomsFrom": MIN_ROOMS,
        "roomsTo": MAX_ROOMS,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.madlan.co.il/",
    }
    logger.info("Отправляю GET-запрос к %s", url)
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info("HTTP статус: %s", resp.status_code)
        logger.info("Размер ответа: %d байт", len(resp.text))
        # Сохраняем первые 2000 символов ответа для диагностики
        logger.info("Первые 2000 символов ответа:\n%s", resp.text[:2000])

        # Ищем JSON с данными
        start_str = 'window.__SSR_HYDRATED_CONTEXT__='
        start = resp.text.find(start_str)
        if start == -1:
            logger.error("Не найден JSON с данными на странице")
            return []
        start += len(start_str)
        end = resp.text.find('</script>', start)
        if end == -1:
            logger.error("Не найден конец JSON блока")
            return []
        json_str = resp.text[start:end].strip()
        logger.info("Извлечён JSON длиной %d символов", len(json_str))
        data = json.loads(json_str)

        # Извлекаем объявления
        listings = []
        if "reduxInitialState" in data:
            search_data = data["reduxInitialState"].get("searchList", {}).get("data", {}).get("searchPoiV2", {})
            items = search_data.get("poi", [])
            logger.info("Всего элементов в poi: %d", len(items))
            for item in items:
                if item.get("type") == "bulletin":
                    listings.append(item)
        logger.info("Получено %d частных объявлений", len(listings))
        if listings:
            # Показываем первое объявление для проверки структуры
            logger.info("Пример первого объявления:\n%s", json.dumps(listings[0], indent=2, ensure_ascii=False)[:1500])
        return listings
    except Exception as e:
        logger.error("Ошибка при запросе к Madlan: %s", e)
        return []

def load_sent_ids():
    try:
        with open(SENT_IDS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_sent_ids(ids_set):
    with open(SENT_IDS_FILE, "w") as f:
        json.dump(list(ids_set), f)

def build_message(item):
    listing_id = item.get("id", "")
    address = item.get("address", "Адрес не указан")
    price = item.get("price", "—")
    rooms = item.get("beds", "—")
    area = item.get("area", "—")
    floor = item.get("floor", "—")
    url = f"https://www.madlan.co.il/item/{listing_id}" if listing_id else ""

    msg = f"{address}\n"
    msg += f"Цена: {price} ₪\n"
    msg += f"Комнат: {rooms} | Площадь: {area} м² | Этаж: {floor}\n"
    if url:
        msg += f"Ссылка: {url}"
    return msg, listing_id

def main():
    tg_send_message("Запуск агента Madlan. Начинаю поиск...")
    sent_ids = load_sent_ids()
    items = fetch_madlan_listings()
    new_found = 0

    for item in items:
        msg, lid = build_message(item)
        if not lid or lid in sent_ids:
            continue
        tg_send_message(msg)
        sent_ids.add(lid)
        new_found += 1

    save_sent_ids(sent_ids)
    logger.info("Отправлено %d новых объявлений", new_found)

if __name__ == "__main__":
    main()
