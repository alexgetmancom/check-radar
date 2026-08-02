import { parseStoredDate } from "../db/dates.js";
import type { FiscalData, ReceiptPayload } from "../db/operations.js";
import { getFoodSubcategory, getItemCategory, simplifyStoreName } from "./rules.js";

const monthNames = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : value ? parseStoredDate(value) : undefined;
  if (!date || Number.isNaN(date.valueOf())) return "Неизвестная дата";
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatShortDate(value: string | Date): string {
  const date = value instanceof Date ? value : parseStoredDate(value);
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${String(date.getFullYear()).slice(-2)}`;
}

export function monthName(monthIndex: number): string {
  return monthNames[monthIndex] ?? "Неизвестно";
}

export function formatReceiptHtml(
  receipt: ReceiptPayload,
  fiscalData: FiscalData | null,
  ownerPhone?: string | null,
): string {
  const owner = simplifyStoreName(receipt.kktOwner);
  const total = Number(receipt.totalSum ?? 0) || 0;
  let html = `<h1>🛒 ${owner}</h1>`;
  if (ownerPhone) {
    const names: Record<string, string> = { "79639629392": "Лёша", "79013652064": "Маша" };
    html += `<p>💳 <b>Оплатил(а):</b> ${names[ownerPhone] ?? ownerPhone}</p>\n`;
  }
  html += `<p>📅 <i>${formatDateTime(receipt.createdDate)}</i> | 💰 <b>Итого: ${total.toFixed(2)} ₽</b></p>\n`;

  const grouped = new Map<string, Map<string, { price: number; qty: number; sum: number }>>();
  for (const item of fiscalData?.items ?? []) {
    const name = item.name ?? "Товар";
    const qty = item.quantity ?? 1;
    const price = item.price ?? 0;
    const sum = item.sum ?? 0;
    if (["Платеж", "Предоплата", "Аванс"].includes(name) || sum <= 0.01 || price <= 0.01) continue;

    const category = getItemCategory(name, receipt.kktOwner);
    const iconMap: Record<string, string> = {
      "Бытовая техника и электроника": "🔌 Бытовая техника",
      "Товары для питомцев (корма)": "🐈 Товары для питомцев",
      "Одежда и обувь": "👕 Одежда и обувь",
      "Хостинг, серверы и облака": "☁️ Хостинг и облака",
      "Связь и интернет-провайдеры": "🌐 Связь и интернет",
      "Транспорт (Такси)": "🚕 Такси",
      "Кафе и рестораны / Готовая еда": "🍕 Кафе и рестораны",
      "Доставка и сервисные сборы": "🛵 Доставка и сборы",
      "Гигиена и бытовая химия": "🧼 Гигиена и химия",
      "Упаковка / Пакеты": "🛍️ Пакеты",
      "Подписки и лояльность": "🎟️ Подписки",
      "Объявления и реклама": "📣 Объявления",
    };
    const subcategory =
      category === "Продукты питания и напитки"
        ? (getFoodSubcategory(name, receipt.kktOwner ?? "") ?? "📦 Прочие продукты")
        : (iconMap[category] ?? `📦 ${category}`);
    const byName = grouped.get(subcategory) ?? new Map();
    const entry = byName.get(name) ?? { price, qty: 0, sum: 0 };
    entry.qty += qty;
    entry.sum += sum;
    byName.set(name, entry);
    grouped.set(subcategory, byName);
  }

  if (grouped.size === 0) return `${html}<p>💳 <b>Предоплата заказа / Авансовый платёж</b></p>\n`;

  for (const subcategory of [...grouped.keys()].sort()) {
    html += `<h3>${subcategory}:</h3><table bordered striped><tr><th>Товар</th><th>Кол-во</th><th>Сумма</th></tr>`;
    for (const [name, data] of grouped.get(subcategory) ?? []) {
      const unitPrice = data.qty > 1 ? ` (<i>${data.price.toFixed(2)} ₽/шт</i>)` : "";
      html += `<tr><td>${name}</td><td>${data.qty.toFixed(1)} шт</td><td><b>${data.sum.toFixed(2)} ₽</b>${unitPrice}</td></tr>`;
    }
    html += "</table>\n";
  }
  return html;
}

export function formatWeeklyReport(
  startThis: Date,
  endThis: Date,
  startLast: Date,
  endLast: Date,
  catsThis: Record<string, number>,
  catsLast: Record<string, number>,
  totalThis: number,
  totalLast: number,
  itemsThis: Array<{ owner: string | null; name: string; sum: number }>,
): string {
  const diff = totalThis - totalLast;
  const diffPct = totalLast > 0 ? (diff / totalLast) * 100 : 0;
  const sign = diff > 0 ? "+" : "";
  let html = `<h1>📊 Финансовый отчет за неделю</h1><p><i>Сравнение: ${formatShortDate(startThis)} - ${formatShortDate(endThis)} vs ${formatShortDate(startLast)} - ${formatShortDate(endLast)}</i></p>\n`;
  html += `<p>💰 <b>Траты на этой неделе:</b> ${totalThis.toFixed(2)} ₽<br>📊 <b>Изменение:</b> ${sign}${diff.toFixed(2)} ₽ (<i>${sign}${diffPct.toFixed(1)}%</i>) vs прошлые ${totalLast.toFixed(0)} ₽</p>\n`;
  const incomeThis = catsThis.Доходы ?? 0;
  const incomeLast = catsLast.Доходы ?? 0;
  if (incomeThis > 0 || incomeLast > 0) {
    const incomeDiff = incomeThis - incomeLast;
    html += `<p>📈 <b>Доходы на этой неделе:</b> ${incomeThis.toFixed(2)} ₽ (<i>${incomeDiff > 0 ? "+" : ""}${incomeDiff.toFixed(2)} ₽</i> vs ${incomeLast.toFixed(0)} ₽)</p>\n`;
  }
  html +=
    "<h2>📊 Распределение по категориям:</h2><table bordered striped><tr><th>Категория</th><th>Эта неделя</th><th>Было</th><th>Дельта</th></tr>";
  const categories = [...new Set([...Object.keys(catsThis), ...Object.keys(catsLast)])]
    .filter((cat) => cat !== "Доходы")
    .sort();
  for (const category of categories) {
    const current = catsThis[category] ?? 0;
    const previous = catsLast[category] ?? 0;
    const delta = current - previous;
    if (current === 0 && previous === 0) continue;
    html += `<tr><td>${category}</td><td>${current.toFixed(0)} ₽</td><td>${previous.toFixed(0)} ₽</td><td><b>${delta > 0 ? "+" : ""}${delta.toFixed(0)} ₽</b></td></tr>`;
  }
  html += "</table>\n";
  const top = [...itemsThis].sort((left, right) => right.sum - left.sum).slice(0, 5);
  if (top.length > 0) {
    html += "<h2>🔝 Топ-5 трат недели:</h2><ul>";
    for (const item of top)
      html += `<li><b>${item.sum.toFixed(2)} ₽</b> — ${simplifyStoreName(item.owner)}: ${item.name.slice(0, 30)}...</li>`;
    html += "</ul>";
  }
  return html;
}

export function formatMonthlyStats(
  total: number,
  categories: Record<string, number>,
  totalLesha = 0,
  totalMasha = 0,
): string {
  let html = `<h1>📊 Статистика расходов за месяц</h1><p>💰 <b>Всего трат:</b> ${total.toFixed(2)} ₽</p>`;
  const income = categories.Доходы ?? 0;
  if (income > 0) html += `<p>📈 <b>Всего доходов:</b> ${income.toFixed(2)} ₽</p>`;
  if (totalLesha > 0 || totalMasha > 0)
    html += `<p>🧔 <b>Лёша:</b> ${totalLesha.toFixed(2)} ₽ | 👩 <b>Маша:</b> ${totalMasha.toFixed(2)} ₽</p>`;
  html += "<table bordered striped><tr><th>Категория</th><th>Сумма</th><th>Доля</th></tr>";
  for (const [category, value] of Object.entries(categories)
    .filter(([key]) => key !== "Доходы")
    .sort(([, a], [, b]) => b - a)) {
    html += `<tr><td>${category}</td><td><b>${value.toFixed(2)} ₽</b></td><td><i>${total > 0 ? ((value / total) * 100).toFixed(1) : "0.0"}%</i></td></tr>`;
  }
  return `${html}</table>`;
}

export function formatFoodStats(totalFood: number, expenses: Record<string, number>): string {
  let html = `<h1>🛒 Расходы на еду и продукты</h1><p>💰 <b>Итого продукты:</b> ${totalFood.toFixed(2)} ₽</p><table bordered striped><tr><th>Группа товаров</th><th>Сумма</th><th>Доля</th></tr>`;
  for (const [subcategory, value] of Object.entries(expenses).sort(([, a], [, b]) => b - a)) {
    html += `<tr><td>${subcategory}</td><td><b>${value.toFixed(2)} ₽</b></td><td><i>${((value / totalFood) * 100).toFixed(1)}%</i></td></tr>`;
  }
  return `${html}</table>`;
}
