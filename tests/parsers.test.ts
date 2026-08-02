import { describe, expect, test } from "bun:test";
import { migrateDatabase, openDatabase } from "../src/db/client.js";
import { saveReceipt, saveTaxiTrip } from "../src/db/operations.js";
import {
  parseFastenRideHtml,
  parseSpotifyPlan,
  parseStripeReceipt,
  parseTimewebIncome,
  parseYandexTaxiHtml,
} from "../src/services/gmail.js";

const yandexHtml = `
  <table>
    <tr><td>Откуда</td><td>ул. Ленина, д. 10</td></tr>
    <tr><td>Куда</td><td>просп. Мира, д. 25</td></tr>
    <tr><td>Тариф</td><td>Комфорт+</td></tr>
    <tr><td>Дистанция</td><td>14.2 км</td></tr>
    <tr><td>Время в пути</td><td>32 мин</td></tr>
    <tr><td>Итого</td><td>750.50 ₽</td></tr>
    <tr><td>Чаевые водителю</td><td>50 ₽</td></tr>
  </table>`;

const fastenHtml = `
  <table>
    <tr><td class="route__name">Аэропорт Домодедово</td></tr>
    <tr><td class="route__name">ул. Тверская, 12</td></tr>
    <tr><td class="check__price">₽ 1850</td></tr>
  </table>`;

describe("Gmail parsers", () => {
  test("parses Yandex Taxi details", () => {
    expect(parseYandexTaxiHtml(yandexHtml)).toEqual([
      "ул. Ленина, д. 10",
      "просп. Мира, д. 25",
      750.5,
      "Комфорт+",
      14.2,
      32,
      50,
    ]);
  });

  test("parses Fasten route and price", () => {
    expect(parseFastenRideHtml(fastenHtml)).toEqual(["Аэропорт Домодедово", "ул. Тверская, 12", 1850]);
  });

  test("parses provider-specific receipt formats", () => {
    expect(parseTimewebIncome("На счёт зачислено 454 от клиента wr995583")).toEqual([454, "wr995583"]);
    expect(parseStripeReceipt("Your receipt from X Developer Platform #2854-7093", "<div>$5.00</div>")).toEqual([
      "X Developer Platform",
      5,
      "$",
    ]);
    expect(parseSpotifyPlan('Your order confirmation for "Premium Duo"')).toEqual(["Premium Duo", 14.99]);
  });
});

test("preserves the legacy taxi database contract", () => {
  const database = openDatabase(":memory:");
  try {
    migrateDatabase(database);
    saveReceipt(
      database,
      {
        key: "test_receipt_key_123",
        createdDate: "2026-07-04T12:00:00",
        totalSum: 750.5,
        kktOwner: "Яндекс.Такси",
        ownerPhone: "79639629392",
      },
      { items: [{ name: "Поездка", price: 750.5, quantity: 1, sum: 750.5 }] },
    );
    saveTaxiTrip(database, {
      receiptKey: "test_receipt_key_123",
      date: "2026-07-04T12:00:00",
      tariffClass: "Комфорт+",
      fromAddress: "ул. Ленина, д. 10",
      toAddress: "просп. Мира, д. 25",
      distanceKm: 14.2,
      durationMins: 32,
      fareCost: 700.5,
      tipsCost: 50,
      totalCost: 750.5,
    });

    const row = database.sqlite.query("SELECT * FROM taxi_trips WHERE receipt_key = ?").get("test_receipt_key_123") as {
      receipt_key: string;
      tariff_class: string;
      distance_km: number;
      duration_mins: number;
      fare_cost: number;
      tips_cost: number;
      total_cost: number;
    } | null;
    expect(row).toMatchObject({
      receipt_key: "test_receipt_key_123",
      tariff_class: "Комфорт+",
      distance_km: 14.2,
      duration_mins: 32,
      fare_cost: 700.5,
      tips_cost: 50,
      total_cost: 750.5,
    });
  } finally {
    database.close();
  }
});
