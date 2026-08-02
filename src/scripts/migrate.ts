import { loadConfig } from "../config.js";
import { migrateDatabase, openDatabase } from "../db/client.js";
import { log } from "../logger.js";

const config = loadConfig({ ...process.env, BOT_MODE: "http-only" });
const database = openDatabase(config.DATABASE_URL);

try {
  migrateDatabase(database);
  log("info", "Database migrations applied", { database: config.DATABASE_URL });
} finally {
  database.close();
}
