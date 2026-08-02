import type { OpenDatabase } from "../db/client.js";
import { formatLocalDate, formatLocalDateTime, parseStoredDate, startOfLocalDay } from "../db/dates.js";
import { getCleanReceipts, getLatestReceipt, getState, setState } from "../db/operations.js";
import { filterDuplicateReceipts } from "./deduplicator.js";
import { formatFoodStats, formatMonthlyStats, formatWeeklyReport, monthName } from "./formatters.js";
import { getFoodSubcategory, getItemCategory } from "./rules.js";

export function getCleanItems(
  database: OpenDatabase,
  startDate: string,
  endDate: string,
): Array<{ owner: string | null; name: string; sum: number; ownerPhone: string | null }> {
  const receipts = getCleanReceipts(database, startDate, endDate);
  const ignored = filterDuplicateReceipts(receipts);
  const result: Array<{ owner: string | null; name: string; sum: number; ownerPhone: string | null }> = [];
  for (const [key, receipt] of receipts) {
    if (ignored.has(key)) continue;
    for (const item of receipt.items) {
      if (["Платеж", "Предоплата", "Аванс"].includes(item.name)) continue;
      result.push({ owner: receipt.owner, name: item.name, sum: item.sum, ownerPhone: receipt.ownerPhone });
    }
  }
  return result;
}

export function categorizeItems(
  items: Array<{ owner: string | null; name: string; sum: number }>,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const item of items) {
    const category = getItemCategory(item.name, item.owner);
    result[category] = (result[category] ?? 0) + item.sum;
  }
  return result;
}

export function sumExpenses(categories: Record<string, number>): number {
  return Object.entries(categories)
    .filter(([key]) => key !== "Доходы")
    .reduce((sum, [, value]) => sum + value, 0);
}

function totalExpenses(items: Array<{ owner: string | null; name: string; sum: number }>): number {
  return sumExpenses(categorizeItems(items));
}

export function checkSpendingAnomaly(database: OpenDatabase): [number, number, number] | undefined {
  const now = new Date();
  const todayStart = startOfLocalDay(now);
  const thirtyDaysAgo = new Date(todayStart.valueOf() - 30 * 86_400_000);
  const previousItems = getCleanItems(
    database,
    formatLocalDateTime(thirtyDaysAgo),
    formatLocalDateTime(new Date(todayStart.valueOf() - 1_000)),
  );
  const todayItems = getCleanItems(database, formatLocalDateTime(todayStart), formatLocalDateTime(now));
  const average = totalExpenses(previousItems) / 30;
  const todayTotal = totalExpenses(todayItems);
  if (average <= 200 || todayTotal <= 3 * average) return undefined;

  const today = formatLocalDate(now);
  if (getState(database, "last_anomaly_warning_date") === today) return undefined;
  setState(database, "last_anomaly_warning_date", today);
  return [todayTotal, average, todayTotal / average];
}

function monday(date: Date): Date {
  const result = new Date(date);
  result.setHours(0, 0, 0, 0);
  result.setDate(result.getDate() - result.getDay() + (result.getDay() === 0 ? -6 : 1));
  return result;
}

export function buildWeeklyReport(database: OpenDatabase): string {
  const today = new Date();
  const thisStart = monday(today);
  const lastStart = new Date(thisStart);
  lastStart.setDate(lastStart.getDate() - 7);
  const lastEnd = new Date(thisStart);
  lastEnd.setMilliseconds(-1);
  const thisEnd = new Date(thisStart);
  thisEnd.setDate(thisEnd.getDate() + 6);
  const thisItems = getCleanItems(database, formatLocalDateTime(thisStart), formatLocalDateTime(thisEnd));
  const lastItems = getCleanItems(database, formatLocalDateTime(lastStart), formatLocalDateTime(lastEnd));
  const thisCategories = categorizeItems(thisItems);
  const lastCategories = categorizeItems(lastItems);
  const totalThis = sumExpenses(thisCategories);
  const totalLast = sumExpenses(lastCategories);
  return formatWeeklyReport(
    thisStart,
    today,
    lastStart,
    lastEnd,
    thisCategories,
    lastCategories,
    totalThis,
    totalLast,
    thisItems,
  );
}

export function buildFoodReport(database: OpenDatabase): string | undefined {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const items = getCleanItems(database, formatLocalDateTime(monthStart), formatLocalDateTime(now));
  const expenses: Record<string, number> = {};
  let total = 0;
  for (const item of items) {
    const subcategory = getFoodSubcategory(item.name, item.owner ?? "");
    if (!subcategory) continue;
    expenses[subcategory] = (expenses[subcategory] ?? 0) + item.sum;
    total += item.sum;
  }
  return total === 0 ? undefined : formatFoodStats(total, expenses);
}

export function buildMonthlyStatsReport(database: OpenDatabase): { chartUrl?: string; html?: string; total: number } {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const items = getCleanItems(database, formatLocalDateTime(monthStart), formatLocalDateTime(now));
  const categories = categorizeItems(items);
  const total = sumExpenses(categories);
  if (total === 0 && (categories.Доходы ?? 0) === 0) return { total: 0 };

  const totalLesha = items
    .filter((item) => item.ownerPhone === "79639629392" && getItemCategory(item.name, item.owner) !== "Доходы")
    .reduce((sum, item) => sum + item.sum, 0);
  const totalMasha = items
    .filter((item) => item.ownerPhone === "79013652064" && getItemCategory(item.name, item.owner) !== "Доходы")
    .reduce((sum, item) => sum + item.sum, 0);
  const sorted = Object.entries(categories)
    .filter(([key]) => key !== "Доходы")
    .sort(([, a], [, b]) => b - a);
  const chart = {
    type: "doughnut",
    data: {
      labels: sorted.map(
        ([category, value]) => `${category} (${total > 0 ? ((value / total) * 100).toFixed(1) : "0.0"}%)`,
      ),
      datasets: [
        {
          data: sorted.map(([, value]) => Number(value.toFixed(2))),
          backgroundColor: ["#5C6BC0", "#26A69A", "#FFA726", "#EC407A", "#AB47BC", "#78909C"],
        },
      ],
    },
    options: { title: { display: true, text: `Расходы за текущий месяц (Итого: ${total.toFixed(0)} ₽)` } },
  };
  return {
    chartUrl: `https://quickchart.io/chart?c=${encodeURIComponent(JSON.stringify(chart))}&w=600&h=450`,
    html: formatMonthlyStats(total, categories, totalLesha, totalMasha),
    total,
  };
}

export function buildTaxiReport(database: OpenDatabase): { chartUrl?: string; html?: string } {
  const monthStart = new Date();
  monthStart.setDate(1);
  const start = formatLocalDate(monthStart);
  const summary = database.sqlite
    .query(
      "SELECT COUNT(*) AS count, SUM(total_cost) AS total_cost, SUM(distance_km) AS total_dist, SUM(duration_mins) AS total_dur, SUM(tips_cost) AS total_tips FROM taxi_trips WHERE date >= ?",
    )
    .get(start) as { count: number; total_cost?: number; total_dist?: number; total_dur?: number; total_tips?: number };
  if (!summary || summary.count === 0) return {};
  const popular = database.sqlite
    .query("SELECT tariff_class FROM taxi_trips WHERE date >= ? GROUP BY tariff_class ORDER BY COUNT(*) DESC LIMIT 1")
    .get(start) as { tariff_class?: string } | null;
  const addresses = database.sqlite
    .query(
      "SELECT to_address, COUNT(*) AS count FROM taxi_trips WHERE date >= ? AND to_address != 'Неизвестно' GROUP BY to_address ORDER BY count DESC LIMIT 3",
    )
    .all(start) as Array<{ to_address?: string; count: number }>;
  const tariffCosts = database.sqlite
    .query("SELECT tariff_class, SUM(total_cost) AS total FROM taxi_trips WHERE date >= ? GROUP BY tariff_class")
    .all(start) as Array<{ tariff_class?: string; total: number }>;
  const total = summary.total_cost ?? 0;
  const distance = summary.total_dist ?? 0;
  let html = `<h1>🚕 Статистика поездок: ${monthName(new Date().getMonth())} ${new Date().getFullYear()}</h1><p>💰 <b>Всего потрачено:</b> ${total.toFixed(2)} ₽ (Чаевые: ${(summary.total_tips ?? 0).toFixed(0)} ₽)</p><p>🛣 <b>Общий пробег:</b> ${distance.toFixed(1)} км</p><p>⏱ <b>Время в пути:</b> ${(summary.total_dur ?? 0).toFixed(0)} мин</p><p>💳 <b>Средняя цена 1 км:</b> ${(distance > 0 ? total / distance : 0).toFixed(2)} ₽/км</p><p>🚗 <b>Частый тариф:</b> ${popular?.tariff_class ?? "Неизвестно"}</p>`;
  if (addresses.length > 0) {
    html += "<h3>📍 Популярные направления:</h3><ul>";
    for (const address of addresses)
      html += `<li><b>${address.count} раз(а)</b> — ${(address.to_address ?? "").split(",")[0]}</li>`;
    html += "</ul>";
  }
  let chartUrl: string | undefined;
  if (tariffCosts.length > 1) {
    const chart = {
      type: "doughnut",
      data: {
        labels: tariffCosts.map((row) => `${row.tariff_class} (${row.total.toFixed(0)} ₽)`),
        datasets: [
          {
            data: tariffCosts.map((row) => Number(row.total.toFixed(2))),
            backgroundColor: ["#5C6BC0", "#26A69A", "#FFA726", "#EC407A"],
          },
        ],
      },
      options: { title: { display: true, text: "Траты на такси по тарифам" } },
    };
    chartUrl = `https://quickchart.io/chart?c=${encodeURIComponent(JSON.stringify(chart))}&w=400&h=300`;
  }
  return chartUrl ? { chartUrl, html } : { html };
}

export function getLatestDashboardReceipt(database: OpenDatabase): string {
  const latest = getLatestReceipt(database);
  return latest
    ? `🛍 ${parseStoredDate(latest.date).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${latest.owner ?? "Неизвестный магазин"} · <b>${latest.total.toFixed(0)} ₽</b>`
    : "Нет трат";
}
