import os
import json
import logging
import time
import requests
from datetime import datetime, timezone, timedelta

# ---------- НАСТРОЙКИ ----------
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('CHAT_ID', '').strip()
SCRAPINGBEE_KEY = os.environ.get('SCRAPINGBEE_KEY', '').strip()

# ---------- ФИЛЬТРЫ ПОИСКА ----------
AREA = '5'           # Хайфа
MAX_PRICE = 1_500_000
MIN_ROOMS = 3
MAX_ROOMS = 5

START_HOUR = 7
END_HOUR = 22

SENT_IDS_FILE = 'sent_ids.json'
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def is_active_hours():
    israel_tz = timezone(timedelta(hours=3))
    now = datetime.now(israel_tz)
    logger.info(f'Текущее время в Израиле: {now.strftime("%H:%M")}. Активность с {START_HOUR} до {END_HOUR}.')
    return START_HOUR <= now.hour < END_HOUR

def tg_send_photo(photo_url, caption):
    """Отправка фото с подписью в Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning('Telegram не настроен – пропускаю отправку фото')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
    payload = {
        'chat_id': CHAT_ID,
        'photo': photo_url,
        'caption': caption,
        'parse_mode': 'HTML'
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info('Фото отправлено в Telegram')
    except Exception as e:
        logger.error(f'Ошибка отправки фото: {e}')

def tg_send_message(text):
    """Отправка текстового сообщения (используется редко, когда нет фото)"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning('Telegram не настроен – пропускаю отправку')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info('Сообщение отправлено в Telegram')
    except Exception as e:
        logger.error(f'Ошибка отправки в Telegram: {e}')

def fetch_madlan_listings():
    url = 'https://www.madlan.co.il/for-sale/%D7%97%D7%99%D7%A4%D7%94-%D7%99%D7%A9%D7%A8%D7%90%D7%9C'
    params = {
        'area': AREA,
        'priceTo': MAX_PRICE,
        'roomsFrom': MIN_ROOMS,
        'roomsTo': MAX_ROOMS,
    }
    logger.info(f'Начинаю запрос к Madlan через ScrapingBee. Параметры: {params}')
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
        logger.info(f'Ответ от ScrapingBee получен. Размер: {len(resp.text)} байт.')

        start_marker = 'window.__SSR_HYDRATED_CONTEXT__='
        start = resp.text.find(start_marker)
        if start == -1:
            logger.error('Не найден JSON с данными в ответе.')
            return []
        start += len(start_marker)
        end = resp.text.find('</script>', start)
        if end == -1:
            logger.error('Не найден конец JSON блока.')
            return []
        json_str = resp.text[start:end].strip()
        logger.info(f'JSON извлечён. Длина: {len(json_str)} символов.')

        json_str = json_str.replace(':undefined', ':null')
        json_str = json_str.replace(': undefined', ': null')

        data = json.loads(json_str)
        logger.info('JSON успешно распарсен.')

        redux = data.get('reduxInitialState', {})
        domain = redux.get('domainData', {})
        search_list = domain.get('searchList', {})
        search_data = search_list.get('data', {})
        poi_data = search_data.get('searchPoiV2', {})
        items = poi_data.get('poi', [])
        logger.info(f'Получено {len(items)} элементов poi.')

        listings = [it for it in items if it.get('type') == 'bulletin']
        logger.info(f'Найдено {len(listings)} частных объявлений.')
        return listings
    except Exception as e:
        logger.error(f'Ошибка при запросе к Madlan: {e}')
        return []

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
              f'🛏 Комнат: {rooms} | 📐 Площадь: {area} м² | 🏢 Этаж: {floor}\n' \
              f'<a href="{full_url}">🔗 Посмотреть объявление</a>'

    # Получаем первое фото
    images = item.get('images', [])
    photo_url = None
    if images:
        img = images[0].get('imageUrl', '')
        if img:
            if img.startswith('bulletins/') or img.startswith('/bulletins/'):
                photo_url = f'https://images2.madlan.co.il/{img}'
            elif img.startswith('http'):
                photo_url = img
            else:
                photo_url = f'https://images2.madlan.co.il/{img}'

    return caption, photo_url, listing_id

def main():
    logger.info('===== Запуск Madlan-бота =====')
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error('TELEGRAM_TOKEN или CHAT_ID не заданы.')
        return
    if not SCRAPINGBEE_KEY:
        logger.error('SCRAPINGBEE_KEY не задан.')
        return

    if not is_active_hours():
        logger.info('Сейчас неактивное время, завершаю работу.')
        return

    tg_send_message('🔍 Начинаю поиск квартир на Madlan...')
    sent_ids = load_sent_ids()
    items = fetch_madlan_listings()

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

    new_found = 0
    for item in filtered:
        caption, photo_url, lid = build_message_and_photo(item)
        if lid in sent_ids:
            continue
        if photo_url:
            tg_send_photo(photo_url, caption)
        else:
            tg_send_message(caption)
        sent_ids.add(lid)
        new_found += 1
        time.sleep(1.5)

    if new_found == 0:
        tg_send_message('ℹ️ На данный момент новых квартир нет.')

    save_sent_ids(sent_ids)
    logger.info(f'===== Завершено. Отправлено {new_found} новых объявлений. =====')

if __name__ == '__main__':
    main()
