import { index, integer, real, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const receipts = sqliteTable(
  "receipts",
  {
    key: text("key").primaryKey(),
    createdDate: text("created_date"),
    receiveDate: text("receive_date"),
    totalSum: real("total_sum"),
    kktOwner: text("kkt_owner"),
    kktOwnerInn: text("kkt_owner_inn"),
    buyer: text("buyer"),
    ownerPhone: text("owner_phone"),
  },
  (table) => [index("idx_receipts_date").on(table.createdDate)],
);

export const items = sqliteTable(
  "items",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    receiptKey: text("receipt_key").references(() => receipts.key, { onDelete: "cascade" }),
    name: text("name"),
    price: real("price"),
    quantity: real("quantity"),
    sum: real("sum"),
  },
  (table) => [index("idx_items_receipt").on(table.receiptKey)],
);

export const taxiTrips = sqliteTable(
  "taxi_trips",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    receiptKey: text("receipt_key")
      .unique()
      .references(() => receipts.key, { onDelete: "cascade" }),
    date: text("date"),
    tariffClass: text("tariff_class"),
    fromAddress: text("from_address"),
    toAddress: text("to_address"),
    distanceKm: real("distance_km"),
    durationMins: integer("duration_mins"),
    fareCost: real("fare_cost"),
    tipsCost: real("tips_cost"),
    totalCost: real("total_cost"),
  },
  (table) => [index("idx_taxi_trips_date").on(table.date)],
);

export const botState = sqliteTable("bot_state", {
  key: text("key").primaryKey(),
  value: text("value"),
});

export const schema = { receipts, items, taxiTrips, botState };

export type Receipt = typeof receipts.$inferSelect;
export type NewReceipt = typeof receipts.$inferInsert;
export type Item = typeof items.$inferSelect;
export type TaxiTrip = typeof taxiTrips.$inferSelect;
