from config.rules import FORCE_DEDUPLICATE_KEYWORDS


def filter_duplicate_receipts(receipts_dict):
    """
    Принимает словарь receipts_dict вида:
    {
        key: {
            'date': datetime,
            'owner': str,
            'total_sum': float,
            'items': [{'name': str, 'price': float, 'qty': float, 'sum': float}]
        }
    }
    Возвращает множество (set) ключей, которые являются дубликатами.
    """
    sorted_keys = sorted(receipts_dict.keys(), key=lambda k: receipts_dict[k]["date"])
    ignored_keys = set()

    for i in range(len(sorted_keys)):
        for j in range(i + 1, len(sorted_keys)):
            k1, k2 = sorted_keys[i], sorted_keys[j]
            r1, r2 = receipts_dict[k1], receipts_dict[k2]

            # Если один и тот же магазин и одинаковая сумма трат
            if r1["owner"] == r2["owner"] and abs(r1["total_sum"] - r2["total_sum"]) < 0.1:
                # В пределах 4 дней
                if abs((r1["date"] - r2["date"]).days) <= 4:
                    n1 = {item["name"] for item in r1["items"] if item["name"] != "Платеж"}
                    n2 = {item["name"] for item in r2["items"] if item["name"] != "Платеж"}

                    # Проверяем принудительные слова дедупликации (из правил)
                    has_force_kw = False
                    for kw in FORCE_DEDUPLICATE_KEYWORDS:
                        if any(kw in n.lower() for n in n1):
                            has_force_kw = True
                            break

                    # Если есть пересечения товаров или совпадение по force-словам
                    if n1.intersection(n2) or has_force_kw:
                        ignored_keys.add(k1)

    return ignored_keys
