import { Database } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { type BunSQLiteDatabase, drizzle } from "drizzle-orm/bun-sqlite";
import { migrate } from "drizzle-orm/bun-sqlite/migrator";
import * as schema from "./schema.js";

export type DatabaseClient = BunSQLiteDatabase<typeof schema>;

export type OpenDatabase = {
  sqlite: Database;
  db: DatabaseClient;
  path: string;
  close: () => void;
};

export function openDatabase(databasePath: string): OpenDatabase {
  const resolvedPath = databasePath === ":memory:" ? databasePath : resolve(databasePath);
  if (resolvedPath !== ":memory:") mkdirSync(dirname(resolvedPath), { recursive: true });

  const sqlite = new Database(resolvedPath, { create: true, strict: true });
  sqlite.run("PRAGMA busy_timeout = 30000");
  if (resolvedPath !== ":memory:") sqlite.run("PRAGMA journal_mode = WAL");
  sqlite.run("PRAGMA foreign_keys = ON");

  const db = drizzle(sqlite, { schema });
  return { sqlite, db, path: resolvedPath, close: () => sqlite.close() };
}

export function migrateDatabase(database: OpenDatabase, migrationsFolder = resolve(process.cwd(), "drizzle")): void {
  migrate(database.db, { migrationsFolder });
  ensureLegacyColumns(database.sqlite);
}

function ensureLegacyColumns(sqlite: Database): void {
  const columns = sqlite.query("PRAGMA table_info(receipts)").all() as Array<{ name: string }>;
  if (columns.length > 0 && !columns.some((column) => column.name === "owner_phone")) {
    sqlite.run("ALTER TABLE receipts ADD COLUMN owner_phone TEXT");
  }
}
