import json
import os

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_JSON_PATH = os.path.join(CONFIG_DIR, "rules.json")

# Загружаем правила из шаблона JSON
if os.path.exists(RULES_JSON_PATH):
    with open(RULES_JSON_PATH, "r", encoding="utf-8") as f:
        _rules = json.load(f)
else:
    _rules = {}

CATEGORIES = _rules.get("CATEGORIES", {})
FOOD_CATEGORIES = _rules.get("FOOD_CATEGORIES", {})
FOOD_KEYWORDS = _rules.get("FOOD_KEYWORDS", [])
NON_FOOD_KEYWORDS = _rules.get("NON_FOOD_KEYWORDS", [])
FORCE_DEDUPLICATE_KEYWORDS = _rules.get("FORCE_DEDUPLICATE_KEYWORDS", [])


def simplify_store_name(name):
    if not name:
        return "Неизвестный магазин"
    name_lower = name.lower()
    if "тандер" in name_lower:
        return "Магнит"
    elif "агроаспект" in name_lower or "агроторг" in name_lower:
        return "Пятёрочка"
    elif "интернет решения" in name_lower:
        return "Ozon"
    elif "rwb" in name_lower or "wildberries" in name_lower or "вайлдберриз" in name_lower or "рвб" in name_lower:
        return "Wildberries"
    elif "вкусвилл" in name_lower:
        return "ВкусВилл"
    elif "икс 5 диджитал" in name_lower or "x5 digital" in name_lower:
        return "X5 Доставка"
    elif "арт рест" in name_lower:
        return "Art Rest"
    elif "бэст прайс" in name_lower:
        return "Fix Price"
    elif "яндекс.такси" in name_lower or "яндекс такси" in name_lower:
        return "Яндекс.Такси"
    elif "делимобиль" in name_lower:
        return "Делимобиль"
    elif "селектел" in name_lower or "selectel" in name_lower:
        return "Selectel"
    elif "вебмастер" in name_lower or "partner@timeweb" in name_lower:
        return "Timeweb (Доход)"
    elif "таймвэб" in name_lower or "timeweb" in name_lower:
        return "Timeweb"
    elif "ростелеком" in name_lower:
        return "Ростелеком"
    elif "мтс" in name_lower:
        return "МТС"
    elif "мегафон" in name_lower:
        return "МегаФон"
    elif "вымпелком" in name_lower or "билайн" in name_lower:
        return "Билайн"
    elif "т2 мобайл" in name_lower or "tele2" in name_lower:
        return "Tele2"
    elif "openai" in name_lower:
        return "OpenAI"
    elif "spotify" in name_lower:
        return "Spotify"
    elif "anomaly" in name_lower:
        return "Anomaly"
    elif "x developer platform" in name_lower:
        return "X Developer Platform"
    elif "x.com" in name_lower or "twitter" in name_lower:
        return "X (Twitter)"

    cleaned = name
    for prefix in ["ООО", "АО", "ПАО", "ИП", "ОАО", "ЗАО", '"', "'", "«", "»"]:
        cleaned = cleaned.replace(prefix, "")
    return cleaned.strip()


def get_item_category(item_name, store_name):
    owner_lower = (store_name or "").lower()
    if "wildberries" in owner_lower or "вайлдберриз" in owner_lower or "rwb" in owner_lower or "рвб" in owner_lower:
        return "Покупки на Wildberries"
    elif "fasten" in owner_lower:
        return "Транспорт (Такси)"
    elif "трайтек" in owner_lower:
        return "Связь и интернет-провайдеры"
    elif "timeweb (доход)" in owner_lower:
        return "Доходы"
    elif any(x in owner_lower for x in ["spotify", "openai", "anomaly", "x developer platform", "x (twitter)"]):
        return "Иностранные сервисы"

    name_lower = (item_name or "").lower()

    # 1. Проверяем по общим ключевым словам категорий трат
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in name_lower:
                return cat

    # 2. Если не подошло, но магазин продуктовый
    owner_lower = store_name.lower()
    if any(
        x in owner_lower
        for x in [
            "тандер",
            "агроаспект",
            "агроторг",
            "перекресток",
            "озон фреш",
            "ozon fresh",
            "вкусвилл",
            "дикси",
            "икс 5 диджитал",
            "x5 digital",
        ]
    ):
        return "Продукты питания и напитки"
    elif "остин" in owner_lower:
        return "Одежда и обувь"
    elif "интернет решения" in owner_lower:
        if any(fw in name_lower for fw in FOOD_KEYWORDS) and not any(nfw in name_lower for nfw in NON_FOOD_KEYWORDS):
            return "Продукты питания и напитки"
        else:
            return "Прочие покупки на Ozon"
    elif "бэст прайс" in owner_lower:
        if any(fw in name_lower for fw in FOOD_KEYWORDS) and not any(nfw in name_lower for nfw in NON_FOOD_KEYWORDS):
            return "Продукты питания и напитки"
        else:
            return "Разное / Прочее"

    return "Разное / Прочее"


def get_food_subcategory(item_name, store_name):
    name_lower = item_name.lower()

    # 1. Проверяем, не является ли товар кормом, техникой или химией
    for kw in NON_FOOD_KEYWORDS:
        if kw in name_lower:
            return None

    # 2. Проверяем совпадения по подкатегориям еды
    for subcat, keywords in FOOD_CATEGORIES.items():
        for kw in keywords:
            if kw in name_lower:
                return subcat

    # 3. Если не совпало по ключевым словам, но магазин продуктовый
    owner_lower = store_name.lower()
    is_food_merchant = any(
        x in owner_lower
        for x in [
            "тандер",
            "агроаспект",
            "агроторг",
            "перекресток",
            "озон фреш",
            "ozon fresh",
            "вкусвилл",
            "дикси",
            "икс 5 диджитал",
            "x5 digital",
            "арт рест",
            "art rest",
            "яндекс.еда",
        ]
    )

    if is_food_merchant or any(fw in name_lower for fw in FOOD_KEYWORDS):
        return "📦 Прочие продукты"

    return None
