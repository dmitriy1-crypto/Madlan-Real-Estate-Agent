import os
import json
import time
import logging
import requests

# ---------- НАСТРОЙКИ ----------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN и CHAT_ID должны быть заданы в Secrets!")

# ---------- ФИЛЬТРЫ ПОИСКА (меняйте под себя) ----------
CITY = "חיפה"               # город на иврите
DEAL_TYPE = "unitBuy"       # продажа
MAX_PRICE = 1_500_000
MIN_ROOMS = 3
MAX_ROOMS = 5
IMAGE_ONLY = True
PRICE_ONLY = True

# GraphQL endpoint (из кода страницы)
API_URL = "https://www.madlan.co.il/api2"

SENT_IDS_FILE = "sent_ids.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------- ОТПРАВКА В TELEGRAM ----------
def tg_send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
        logger.info("Сообщение отправлено")
    except Exception as e:
        logger.error("Ошибка отправки в Telegram: %s", e)

# ---------- ЗАПРОС К MADLAN ----------
def fetch_madlan_listings():
    query = """
    query searchPoiV2($input: SearchPoiInput!) {
      searchPoiV2(input: $input) {
        total
        poi {
          id
          type
          address
          price
          beds
          floor
          area
          buildingYear
          generalCondition
          buildingClass
          images {
            imageUrl
            __typename
          }
          __typename
        }
      }
    }
    """
    variables = {
        "input": {
            "city": CITY,
            "dealType": DEAL_TYPE,
            "priceTo": MAX_PRICE,
            "roomsFrom": MIN_ROOMS,
            "roomsTo": MAX_ROOMS,
            "imageOnly": IMAGE_ONLY,
            "priceOnly": PRICE_ONLY,
            "pagination": {
                "bulletinsOffset": 0,
                "projectsOffset": 0,
                "seenProjects": []
            }
        }
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.madlan.co.il",
        "Referer": "https://www.madlan.co.il/for-sale/%D7%97%D7%99%D7%A4%D7%94-%D7%99%D7%A9%D7%A8%D7%90%D7%9C",
    }
    try:
        resp = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            logger.error("GraphQL errors: %s", data["errors"])
            return []
        poi = data.get("data", {}).get("searchPoiV2", {}).get("poi", [])
        # Отфильтровываем только bulletin (частные объявления), не projects
        items = [p for p in poi if p.get("type") == "bulletin"]
        logger.info("Получено %d частных объявлений", len(items))
        return items
    except Exception as e:
        logger.error("Ошибка при запросе к Madlan: %s", e)
        return []

# ---------- КЕШ ОТПРАВЛЕННЫХ ----------
def load_sent_ids():
    try:
        with open(SENT_IDS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_sent_ids(ids_set):
    with open(SENT_IDS_FILE, "w") as f:
        json.dump(list(ids_set), f)

# ---------- ФОРМИРОВАНИЕ СООБЩЕНИЯ ----------
def build_message(item):
    listing_id = item["id"]
    address = item.get("address", "Адрес не указан")
    price = item.get("price", "—")
    rooms = item.get("beds", "—")
    area = item.get("area", "—")
    floor = item.get("floor", "—")
    url = f"https://www.madlan.co.il/item/{listing_id}"

    msg = f"{address}\n"
    msg += f"Цена: {price} ₪\n"
    msg += f"Комнат: {rooms} | Площадь: {area} м² | Этаж: {floor}\n"
    msg += f"Ссылка: {url}"
    return msg, listing_id

def main():
    tg_send_message("Запуск агента Madlan. Начинаю поиск...")
    sent_ids = load_sent_ids()
    items = fetch_madlan_listings()
    new_found = 0

    for item in items:
        msg, lid = build_message(item)
        if lid in sent_ids:
            continue
        tg_send_message(msg)
        sent_ids.add(lid)
        new_found += 1
        time.sleep(1.2)

    save_sent_ids(sent_ids)
    logger.info("Отправлено %d новых объявлений", new_found)

if __name__ == "__main__":
    main()
