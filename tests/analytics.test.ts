import { expect, test } from "bun:test";
import { getDashboard } from "../src/bot/bot.js";
import { migrateDatabase, openDatabase } from "../src/db/client.js";
import { formatLocalDateTime, startOfLocalDay } from "../src/db/dates.js";
import { saveReceipt } from "../src/db/operations.js";
import { checkSpendingAnomaly, getCleanItems } from "../src/services/analytics.js";

function createDatabase() {
  const database = openDatabase(":memory:");
  migrateDatabase(database);
  return database;
}

test("date filtering handles legacy local timestamps and UTC timestamps together", () => {
  const database = createDatabase();
  try {
    const now = new Date();
    const start = new Date(now.valueOf() - 86_400_000);
    saveReceipt(
      database,
      { key: "legacy-local", createdDate: formatLocalDateTime(new Date(now.valueOf() - 3_600_000)), totalSum: 100 },
      { items: [{ name: "Local item", price: 100, quantity: 1, sum: 100 }] },
    );
    saveReceipt(
      database,
      { key: "legacy-utc", createdDate: new Date(now.valueOf() - 7_200_000).toISOString(), totalSum: 200 },
      { items: [{ name: "UTC item", price: 200, quantity: 1, sum: 200 }] },
    );

    const items = getCleanItems(database, formatLocalDateTime(start), formatLocalDateTime(now));
    expect(items.reduce((sum, item) => sum + item.sum, 0)).toBe(300);
  } finally {
    database.close();
  }
});

test("spending anomaly does not count the newly saved receipt twice", () => {
  const database = createDatabase();
  try {
    const todayStart = startOfLocalDay(new Date());
    const previousDate = new Date(todayStart.valueOf() - 29 * 86_400_000 + 12 * 3_600_000);
    const todayDate = new Date(todayStart.valueOf() + 3_600_000);
    saveReceipt(
      database,
      { key: "previous-expense", createdDate: formatLocalDateTime(previousDate), totalSum: 9_000 },
      { items: [{ name: "Previous expense", price: 9_000, quantity: 1, sum: 9_000 }] },
    );
    saveReceipt(
      database,
      { key: "today-expense", createdDate: formatLocalDateTime(todayDate), totalSum: 1_000 },
      { items: [{ name: "Today expense", price: 1_000, quantity: 1, sum: 1_000 }] },
    );

    const anomaly = checkSpendingAnomaly(database);
    expect(anomaly?.[0]).toBe(1_000);
    expect(anomaly?.[1]).toBe(300);
    expect(anomaly?.[2]).toBeCloseTo(10 / 3, 8);
  } finally {
    database.close();
  }
});

test("dashboard reports expenses separately from income", () => {
  const database = createDatabase();
  try {
    const now = formatLocalDateTime(new Date());
    saveReceipt(
      database,
      { key: "dashboard-expense", createdDate: now, totalSum: 100 },
      { items: [{ name: "Household expense", price: 100, quantity: 1, sum: 100 }] },
    );
    saveReceipt(
      database,
      { key: "dashboard-income", createdDate: now, totalSum: 1_000, kktOwner: "Timeweb (Доход)" },
      { items: [{ name: "Partner income", price: 1_000, quantity: 1, sum: 1_000 }] },
    );

    const dashboard = getDashboard(database);
    expect(dashboard.html).toContain("100.00 ₽");
    expect(dashboard.html).not.toContain("1100.00 ₽");
    expect(dashboard.html).toContain("1000.00 ₽");
  } finally {
    database.close();
  }
});
