import { readFileSync } from "node:fs";

type RulesFile = {
  CATEGORIES: Record<string, string[]>;
  FOOD_CATEGORIES: Record<string, string[]>;
  FOOD_KEYWORDS: string[];
  NON_FOOD_KEYWORDS: string[];
  FORCE_DEDUPLICATE_KEYWORDS: string[];
};

const rules = JSON.parse(readFileSync(new URL("../config/rules.json", import.meta.url), "utf8")) as RulesFile;

export function simplifyStoreName(name: string | null | undefined): string {
  if (!name) return "Неизвестный магазин";
  const lower = name.toLowerCase();
  const aliases: Array<[string[], string]> = [
    [["тандер"], "Магнит"],
    [["агроаспект", "агроторг"], "Пятёрочка"],
    [["интернет решения"], "Ozon"],
    [["rwb", "wildberries", "вайлдберриз", "рвб"], "Wildberries"],
    [["вкусвилл"], "ВкусВилл"],
    [["икс 5 диджитал", "x5 digital"], "X5 Доставка"],
    [["арт рест"], "Art Rest"],
    [["бэст прайс"], "Fix Price"],
    [["яндекс.такси", "яндекс такси"], "Яндекс.Такси"],
    [["делимобиль"], "Делимобиль"],
    [["селектел", "selectel"], "Selectel"],
    [["вебмастер", "partner@timeweb"], "Timeweb (Доход)"],
    [["таймвэб", "timeweb"], "Timeweb"],
    [["ростелеком"], "Ростелеком"],
    [["мтс"], "МТС"],
    [["мегафон"], "МегаФон"],
    [["вымпелком", "билайн"], "Билайн"],
    [["т2 мобайл", "tele2"], "Tele2"],
    [["openai"], "OpenAI"],
    [["spotify"], "Spotify"],
    [["anomaly"], "Anomaly"],
    [["x developer platform"], "X Developer Platform"],
    [["x.com", "twitter"], "X (Twitter)"],
  ];

  for (const [needles, value] of aliases) {
    if (needles.some((needle) => lower.includes(needle))) return value;
  }

  return ["ООО", "АО", "ПАО", "ИП", "ОАО", "ЗАО", '"', "'", "«", "»"]
    .reduce((value, prefix) => value.replaceAll(prefix, ""), name)
    .trim();
}

export function getItemCategory(itemName: string | null | undefined, storeName: string | null | undefined): string {
  const owner = (storeName ?? "").toLowerCase();
  if (["wildberries", "вайлдберриз", "rwb", "рвб"].some((value) => owner.includes(value))) {
    return "Покупки на Wildberries";
  }
  if (owner.includes("fasten")) return "Транспорт (Такси)";
  if (owner.includes("трайтек")) return "Связь и интернет-провайдеры";
  if (owner.includes("timeweb (доход)")) return "Доходы";
  if (["spotify", "openai", "anomaly", "x developer platform", "x (twitter)"].some((value) => owner.includes(value))) {
    return "Иностранные сервисы";
  }

  const item = (itemName ?? "").toLowerCase();
  for (const [category, keywords] of Object.entries(rules.CATEGORIES)) {
    if (keywords.some((keyword) => item.includes(keyword))) return category;
  }

  if (
    [
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
    ].some((value) => owner.includes(value))
  ) {
    return "Продукты питания и напитки";
  }

  if (owner.includes("остин")) return "Одежда и обувь";
  if (owner.includes("интернет решения")) {
    return rules.FOOD_KEYWORDS.some((keyword) => item.includes(keyword)) &&
      !rules.NON_FOOD_KEYWORDS.some((keyword) => item.includes(keyword))
      ? "Продукты питания и напитки"
      : "Прочие покупки на Ozon";
  }
  if (owner.includes("бэст прайс")) {
    return rules.FOOD_KEYWORDS.some((keyword) => item.includes(keyword)) &&
      !rules.NON_FOOD_KEYWORDS.some((keyword) => item.includes(keyword))
      ? "Продукты питания и напитки"
      : "Разное / Прочее";
  }
  return "Разное / Прочее";
}

export function getFoodSubcategory(itemName: string, storeName: string): string | undefined {
  const item = itemName.toLowerCase();
  if (rules.NON_FOOD_KEYWORDS.some((keyword) => item.includes(keyword))) return undefined;
  for (const [subcategory, keywords] of Object.entries(rules.FOOD_CATEGORIES)) {
    if (keywords.some((keyword) => item.includes(keyword))) return subcategory;
  }

  const owner = storeName.toLowerCase();
  const foodMerchant = [
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
  ].some((value) => owner.includes(value));

  return foodMerchant || rules.FOOD_KEYWORDS.some((keyword) => item.includes(keyword))
    ? "📦 Прочие продукты"
    : undefined;
}

export function getForceDeduplicateKeywords(): string[] {
  return rules.FORCE_DEDUPLICATE_KEYWORDS;
}
