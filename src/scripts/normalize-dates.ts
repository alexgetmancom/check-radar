import { loadConfig } from "../config.js";
import { openDatabase } from "../db/client.js";
import { formatLocalDateTime, parseStoredDate } from "../db/dates.js";

type DateColumn = { table: "receipts" | "taxi_trips"; column: string };

const dateColumns: DateColumn[] = [
  { table: "receipts", column: "created_date" },
  { table: "receipts", column: "receive_date" },
  { table: "taxi_trips", column: "date" },
];

const hasExplicitTimezone = (value: string): boolean => /(?:Z|[+-]\d{2}:?\d{2})$/u.test(value);

const config = loadConfig({ ...process.env, BOT_MODE: "http-only" });
const database = openDatabase(config.DATABASE_URL);
let updated = 0;

try {
  database.sqlite.transaction(() => {
    for (const { table, column } of dateColumns) {
      const rows = database.sqlite.query(`SELECT rowid, ${column} AS value FROM ${table}`).all() as Array<{
        rowid: number;
        value?: string | null;
      }>;
      for (const row of rows) {
        if (!row.value || !hasExplicitTimezone(row.value)) continue;
        database.sqlite
          .query(`UPDATE ${table} SET ${column} = ? WHERE rowid = ?`)
          .run(formatLocalDateTime(parseStoredDate(row.value)), row.rowid);
        updated += 1;
      }
    }
  })();
  console.log(JSON.stringify({ updated }));
} finally {
  database.close();
}
