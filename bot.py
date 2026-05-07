import os
import json
import logging
import time
import requests
from datetime import datetime, timezone, timedelta

# ---------- НАСТРОЙКИ ----------
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
SCRAPINGBEE_KEY = os.environ.get('SCRAPINGBEE_KEY', '').strip()

# Поддержка нескольких чатов
CHAT_IDS_RAW = os.environ.get('CHAT_IDS', os.environ.get('CHAT_ID', '')).strip()
CHAT_IDS = [cid.strip() for cid in CHAT_IDS_RAW.split(',') if cid.strip()] if CHAT_IDS_RAW else []

# ---------- ЗАГРУЗКА КОНФИГУРАЦИИ ----------
DEFAULT_CONFIG = {
    "area": "5",
    "max_price": 1_500_000,
    "min_rooms": 3,
    "max_rooms": 5,
    "deal_type": "unitBuy",
    "start_hour": 7,
    "end_hour": 22
}

def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        params = {k: v for k, v in config.items() if k in DEFAULT_CONFIG}
        for single_param in ['area', 'max_price', 'min_rooms', 'max_rooms', 'deal_type']:
            if isinstance(params.get(single_param), list):
                raise ValueError(f"Параметр {single_param} должен быть одним значением, а не списком")
        return params
    except Exception as e:
        logging.warning(f'Ошибка загрузки config.json, используются значения по умолчанию: {e}')
        return DEFAULT_CONFIG

CONFIG = load_config()
AREA = CONFIG.get('area', DEFAULT_CONFIG['area'])
MAX_PRICE = CONFIG.get('max_price', DEFAULT_CONFIG['max_price'])
MIN_ROOMS = CONFIG.get('min_rooms', DEFAULT_CONFIG['min_rooms'])
MAX_ROOMS = CONFIG.get('max_rooms', DEFAULT_CONFIG['max_rooms'])
DEAL_TYPE = CONFIG.get('deal_type', DEFAULT_CONFIG['deal_type'])
START_HOUR = CONFIG.get('start_hour', DEFAULT_CONFIG['start_hour'])
END_HOUR = CONFIG.get('end_hour', DEFAULT_CONFIG['end_hour'])

SENT_IDS_FILE = 'sent_ids.json'
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def is_active_hours():
    israel_tz = timezone(timedelta(hours=3))
    now = datetime.now(israel_tz)
    logger.info(f'Текущее время в Израиле: {now.strftime("%H:%M")}. Активность с {START_HOUR} до {END_HOUR}.')
    return START_HOUR <= now.hour < END_HOUR

def tg_send_message(chat_id, text):
    if not TELEGRAM_TOKEN:
        logger.warning('Telegram не настроен – пропускаю отправку')
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f'Сообщение отправлено в Telegram ({chat_id})')
        return True
    except Exception as e:
        logger.error(f'Ошибка отправки в Telegram ({chat_id}): {e}')
        return False

def tg_send_photo(chat_id, photo_url, caption):
    if not TELEGRAM_TOKEN:
        logger.warning('Telegram не настроен – пропускаю отправку фото')
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
    payload = {
        'chat_id': chat_id,
        'photo': photo_url,
        'caption': caption,
        'parse_mode': 'HTML'
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(f'Фото отправлено в Telegram ({chat_id})')
        return True
    except Exception as e:
        logger.error(f'Ошибка отправки фото ({chat_id}): {e}')
        return False

# ========== НОВАЯ ФУНКЦИЯ С ПАГИНАЦИЕЙ ==========
def fetch_madlan_listings():
    # Определяем список зон: если задан "areas" – используем его,
    # иначе берём одиночный "area" (старый стиль).
    if "areas" in CONFIG:
        areas = CONFIG["areas"]
    else:
        areas = [AREA]

    all_items = []

    for area_code in areas:
        url = 'https://www.madlan.co.il/for-sale/%D7%97%D7%99%D7%A4%D7%94-%D7%99%D7%A9%D7%A8%D7%90%D7%9C'
        params = {
            'area': area_code,
            'sort': 'date_desc',
        }
        logger.info(f'Запрашиваю area={area_code}')
        api_url = 'https://app.scrapingbee.com/api/v1/'
        query = {
            'api_key': SCRAPINGBEE_KEY,
            'url': f'{url}?{"&".join(f"{k}={v}" for k, v in params.items())}',
            'render_js': False,
            'premium_proxy': True,
            'country_code': 'il',
        }
        try:
            resp = requests.get(api_url, params=query, timeout=30)
            resp.raise_for_status()
            raw_content = resp.content
            html = raw_content.decode('utf-8', errors='replace')
            
            start_marker = 'window.__SSR_HYDRATED_CONTEXT__='
            start = html.find(start_marker)
            if start == -1:
                logger.error(f'JSON не найден для area={area_code}')
                continue
            start += len(start_marker)
            end = html.find('</script>', start)
            if end == -1:
                logger.error(f'Конец JSON не найден для area={area_code}')
                continue
            json_str = html[start:end].strip()
            json_str = json_str.replace(':undefined', ':null').replace(': undefined', ': null')
            data = json.loads(json_str)

            redux = data.get('reduxInitialState', {})
            domain = redux.get('domainData', {})
            search_list = domain.get('searchList', {})
            search_data = search_list.get('data', {})
            poi_data = search_data.get('searchPoiV2', {})
            items = poi_data.get('poi', [])
            
            logger.info(f'Получено {len(items)} элементов для area={area_code}')

            # Добавляем в общий список, избегая дубликатов по id
            existing_ids = {it.get('id') for it in all_items}
            for it in items:
                if it.get('id') not in existing_ids:
                    all_items.append(it)
                    existing_ids.add(it.get('id'))
        except Exception as e:
            logger.error(f'Ошибка для area={area_code}: {e}')
            continue

    # Фильтрация в Python
    listings = []
    for it in all_items:
        if it.get('type') != 'bulletin':
            continue
        price = it.get('price')
        beds = it.get('beds')
        if price is None or price == 0:
            continue
        if price > MAX_PRICE:
            continue
        if beds is None:
            continue
        if beds < MIN_ROOMS or beds > MAX_ROOMS:
            continue
        listings.append(it)

    logger.info(f'Найдено {len(listings)} частных объявлений после фильтрации.')
    return listings
# ==============================================

def load_sent_ids():
    try:
        with open(SENT_IDS_FILE, 'r') as f:
            ids = set(json.load(f))
            logger.info(f'Загружено {len(ids)} отправленных ID.')
            return ids
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info('Файл sent_ids не найден, начинаю с чистого листа.')
        return set()

def save_sent_ids(ids_set):
    with open(SENT_IDS_FILE, 'w') as f:
        json.dump(list(ids_set), f)
    logger.info(f'Сохранено {len(ids_set)} ID в кеш.')

def format_price(price):
    if isinstance(price, (int, float)):
        return f'{price:,.0f}'.replace(',', ' ')
    return str(price)

def build_message_and_photo(item):
    listing_id = item.get('id', '')
    address = item.get('address', 'Адрес не указан')
    full_url = f'https://www.madlan.co.il/listings/{listing_id}'
    price = format_price(item.get('price', 0))
    rooms = item.get('beds', '—')
    area = item.get('area', '—')
    floor = item.get('floor', '—')

    caption = f'<b>{address}</b>\n' \
              f'💰 Цена: {price} ₪\n' \
              f'Комнат: {rooms} | Площадь: {area} м² | Этаж: {floor}\n' \
              f'<a href="{full_url}">Посмотреть объявление</a>'

    # Собираем первое фото
    images = item.get('images', [])
    photo_url = None
    if images:
        img = images[0].get('imageUrl', '')
        if img:
            img = img.lstrip('/')
            if img.startswith('bulletins/') or img.startswith('/bulletins/'):
                photo_url = f'https://images2.madlan.co.il/{img}'
            elif img.startswith('http'):
                photo_url = img
            else:
                photo_url = f'https://images2.madlan.co.il/{img}'

    # Если фото нет – сразу добавляем пометку
    if not photo_url:
        caption += '\n📷 <i>Фото не загрузилось</i>'

    return caption, photo_url, listing_id

def main():
    logger.info('===== Запуск Madlan-бота =====')
    if not TELEGRAM_TOKEN or not CHAT_IDS:
        logger.error('TELEGRAM_TOKEN или CHAT_IDS не заданы.')
        return
    if not SCRAPINGBEE_KEY:
        logger.error('SCRAPINGBEE_KEY не задан.')
        return

    # Приветствие всем подписчикам
    for cid in CHAT_IDS:
        tg_send_message(cid, '🔍 Начинаю поиск квартир на Madlan...')

    sent_ids = load_sent_ids()
    items = fetch_madlan_listings()

    # Фильтрация
    filtered = []
    for item in items:
        price = item.get('price')
        beds = item.get('beds')
        if price is None or price == 0:
            continue
        if price > MAX_PRICE:
            continue
        if beds is None:
            continue
        if beds < MIN_ROOMS or beds > MAX_ROOMS:
            continue
        filtered.append(item)

    logger.info(f'После фильтрации осталось {len(filtered)} объявлений.')

    success_send = 0
    error_send = 0

    for item in filtered:
        try:
            caption, photo_url, lid = build_message_and_photo(item)
            if lid in sent_ids:
                continue

            sent = False
            for cid in CHAT_IDS:
                if photo_url:
                    if tg_send_photo(cid, photo_url, caption):
                        sent = True
                    else:
                        # Фото не отправилось – добавляем пометку и шлём текст
                        caption_with_note = caption + '\n📷 <i>Фото не загрузилось</i>'
                        if tg_send_message(cid, caption_with_note):
                            sent = True
                else:
                    if tg_send_message(cid, caption):
                        sent = True

            if sent:
                sent_ids.add(lid)
                success_send += 1
            else:
                error_send += 1
        except Exception as e:
            logger.error(f'Не удалось обработать объявление: {e}')
            error_send += 1
        time.sleep(1.5)

    if success_send > 0:
        save_sent_ids(sent_ids)

    # Итоговый отчёт всем подписчикам
    report = f'📊 <b>Отчёт Madlan-бота</b>\n' \
             f'Найдено: {len(items)}\n' \
             f'После фильтров: {len(filtered)}\n' \
             f'Отправлено: {success_send}\n' \
             f'Ошибок: {error_send}'
    for cid in CHAT_IDS:
        tg_send_message(cid, report)

    logger.info(f'===== Завершено. Отправлено {success_send} новых объявлений. =====')

if __name__ == '__main__':
    main()
