import { eq } from "drizzle-orm";
import type { OpenDatabase } from "./client.js";
import { parseStoredDate } from "./dates.js";
import { botState, items, receipts, taxiTrips } from "./schema.js";

export type ReceiptPayload = {
  key: string;
  createdDate?: string | null;
  receiveDate?: string | null;
  totalSum?: number | string | null;
  kktOwner?: string | null;
  kktOwnerInn?: string | null;
  buyer?: string | null;
  ownerPhone?: string | null;
};

export type FiscalData = {
  items?: Array<{
    name?: string | null;
    price?: number | null;
    quantity?: number | null;
    sum?: number | null;
  }>;
};

export type CleanReceipt = {
  date: Date;
  owner: string | null;
  totalSum: number;
  ownerPhone: string | null;
  items: Array<{ name: string; price: number; qty: number; sum: number }>;
};

export function getState(database: OpenDatabase, key: string, defaultValue?: string): string | undefined {
  return (
    database.db.select({ value: botState.value }).from(botState).where(eq(botState.key, key)).get()?.value ??
    defaultValue
  );
}

export function setState(database: OpenDatabase, key: string, value: string): void {
  database.db
    .insert(botState)
    .values({ key, value })
    .onConflictDoUpdate({ target: botState.key, set: { value } })
    .run();
}

export function receiptExists(database: OpenDatabase, key: string): boolean {
  return Boolean(database.db.select({ key: receipts.key }).from(receipts).where(eq(receipts.key, key)).get());
}

export function saveReceipt(
  database: OpenDatabase,
  receipt: ReceiptPayload,
  fiscalData: FiscalData | null | undefined,
  ownerPhone?: string | null,
): void {
  const totalSum = Number(receipt.totalSum ?? 0) || 0;
  database.db.transaction((tx) => {
    tx.insert(receipts)
      .values({
        key: receipt.key,
        createdDate: receipt.createdDate ?? null,
        receiveDate: receipt.receiveDate ?? null,
        totalSum,
        kktOwner: receipt.kktOwner ?? null,
        kktOwnerInn: receipt.kktOwnerInn ?? null,
        buyer: receipt.buyer ?? null,
        ownerPhone: ownerPhone ?? receipt.ownerPhone ?? null,
      })
      .onConflictDoUpdate({
        target: receipts.key,
        set: {
          createdDate: receipt.createdDate ?? null,
          receiveDate: receipt.receiveDate ?? null,
          totalSum,
          kktOwner: receipt.kktOwner ?? null,
          kktOwnerInn: receipt.kktOwnerInn ?? null,
          buyer: receipt.buyer ?? null,
          ownerPhone: ownerPhone ?? receipt.ownerPhone ?? null,
        },
      })
      .run();

    if (fiscalData?.items) {
      tx.delete(items).where(eq(items.receiptKey, receipt.key)).run();
      for (const item of fiscalData.items) {
        tx.insert(items)
          .values({
            receiptKey: receipt.key,
            name: item.name ?? null,
            price: item.price ?? 0,
            quantity: item.quantity ?? 1,
            sum: item.sum ?? 0,
          })
          .run();
      }
    }
  });
}

export type TaxiTripInput = {
  receiptKey: string;
  date: string;
  tariffClass: string;
  fromAddress: string;
  toAddress: string;
  distanceKm: number;
  durationMins: number;
  fareCost: number;
  tipsCost: number;
  totalCost: number;
};

export function saveTaxiTrip(database: OpenDatabase, trip: TaxiTripInput): void {
  database.db
    .insert(taxiTrips)
    .values({
      receiptKey: trip.receiptKey,
      date: trip.date,
      tariffClass: trip.tariffClass,
      fromAddress: trip.fromAddress,
      toAddress: trip.toAddress,
      distanceKm: trip.distanceKm,
      durationMins: trip.durationMins,
      fareCost: trip.fareCost,
      tipsCost: trip.tipsCost,
      totalCost: trip.totalCost,
    })
    .onConflictDoUpdate({
      target: taxiTrips.receiptKey,
      set: {
        date: trip.date,
        tariffClass: trip.tariffClass,
        fromAddress: trip.fromAddress,
        toAddress: trip.toAddress,
        distanceKm: trip.distanceKm,
        durationMins: trip.durationMins,
        fareCost: trip.fareCost,
        tipsCost: trip.tipsCost,
        totalCost: trip.totalCost,
      },
    })
    .run();
}

export function getCleanReceipts(
  database: OpenDatabase,
  startDate?: string,
  endDate?: string,
): Map<string, CleanReceipt> {
  const query = database.db
    .select({
      key: receipts.key,
      date: receipts.createdDate,
      owner: receipts.kktOwner,
      totalSum: receipts.totalSum,
      ownerPhone: receipts.ownerPhone,
      itemName: items.name,
      itemPrice: items.price,
      itemQuantity: items.quantity,
      itemSum: items.sum,
    })
    .from(receipts)
    .innerJoin(items, eq(items.receiptKey, receipts.key));

  const start = startDate ? parseStoredDate(startDate).valueOf() : undefined;
  const end = endDate ? parseStoredDate(endDate).valueOf() : undefined;
  const rows = query
    .all()
    .filter((row) => {
      const timestamp = parseStoredDate(row.date).valueOf();
      return (start === undefined || timestamp >= start) && (end === undefined || timestamp <= end);
    })
    .sort((left, right) => parseStoredDate(right.date).valueOf() - parseStoredDate(left.date).valueOf());
  const result = new Map<string, CleanReceipt>();
  for (const row of rows) {
    const current = result.get(row.key) ?? {
      date: parseStoredDate(row.date),
      owner: row.owner,
      totalSum: row.totalSum ?? 0,
      ownerPhone: row.ownerPhone,
      items: [],
    };
    current.items.push({
      name: row.itemName ?? "",
      price: row.itemPrice ?? 0,
      qty: row.itemQuantity ?? 0,
      sum: row.itemSum ?? 0,
    });
    result.set(row.key, current);
  }
  return result;
}

export function getLatestReceipt(database: OpenDatabase): { date: string; owner: string; total: number } | undefined {
  const rows = database.db
    .select({ date: receipts.createdDate, owner: receipts.kktOwner, total: receipts.totalSum })
    .from(receipts)
    .all()
    .sort((left, right) => parseStoredDate(right.date).valueOf() - parseStoredDate(left.date).valueOf());
  const row = rows[0];
  if (!row?.date) return undefined;
  return { date: row.date, owner: row.owner ?? "", total: row.total ?? 0 };
}

export function countReceipts(database: OpenDatabase): number {
  return database.db.select({ key: receipts.key }).from(receipts).all().length;
}
