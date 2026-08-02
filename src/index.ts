import { configureBot, createBot, createNoopNotifier } from "./bot/bot.js";
import { loadConfig } from "./config.js";
import { migrateDatabase, openDatabase } from "./db/client.js";
import { getState, setState } from "./db/operations.js";
import { createHttpApp } from "./http.js";
import { log } from "./logger.js";
import { stopServerGracefully } from "./runtime/shutdown.js";
import { createRuntimeStatus } from "./runtime/status.js";
import { RuntimeSupervisor } from "./runtime/supervisor.js";
import { startIntervalWorker } from "./runtime/worker.js";
import { buildWeeklyReport } from "./services/analytics.js";
import type { FnsNotifier } from "./services/fns.js";
import { syncReceiptsFromFns } from "./services/fns.js";
import { syncGmailReceipts } from "./services/gmail.js";

function zonedParts(date: Date, timeZone: string): { date: string; hour: number; weekday: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(date);
  const get = (type: string): string => parts.find((part) => part.type === type)?.value ?? "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { date: `${get("year")}-${get("month")}-${get("day")}`, hour: Number(get("hour")), weekday };
}

async function runScheduledCycle(
  config: ReturnType<typeof loadConfig>,
  database: ReturnType<typeof openDatabase>,
  notifier: FnsNotifier,
): Promise<void> {
  const now = new Date();
  const lastSync = getState(database, "last_sync_time");
  const lastSyncAt = lastSync ? Date.parse(lastSync) : Number.NaN;
  if (!Number.isFinite(lastSyncAt) || Date.now() - lastSyncAt > config.SYNC_INTERVAL_SECONDS * 1000) {
    log("info", "Starting scheduled synchronization");
    await syncReceiptsFromFns(config, database, notifier);
    try {
      await syncGmailReceipts(config, database, notifier);
    } catch (error) {
      log("error", "Scheduled Gmail synchronization failed", { error });
    }
    setState(database, "last_sync_time", now.toISOString());
  }

  const parts = zonedParts(now, config.TZ);
  if (parts.weekday === 0 && parts.hour === 21 && getState(database, "last_weekly_report_date") !== parts.date) {
    const report = buildWeeklyReport(database);
    for (const userId of config.ALLOWED_USERS) {
      await notifier.notifyRich(userId, report);
    }
    setState(database, "last_weekly_report_date", parts.date);
  }
}

async function main(): Promise<void> {
  const config = loadConfig();
  const database = openDatabase(config.DATABASE_URL);
  try {
    migrateDatabase(database);
  } catch (error) {
    database.close();
    log("error", "Database migration failed", { error });
    throw error;
  }

  const runtime = config.BOT_MODE === "http-only" ? null : createBot(config, database);
  const notifier = runtime?.notifier ?? createNoopNotifier();
  const status = createRuntimeStatus(config.BOT_MODE);
  const app = createHttpApp(config, runtime, database, status);
  const server = Bun.serve({ fetch: app.fetch, hostname: config.BIND_HOST, port: config.PORT });
  const supervisor = new RuntimeSupervisor();

  if (runtime) {
    supervisor.register(startIntervalWorker("scheduler", 60_000, () => runScheduledCycle(config, database, notifier)));
  }

  let stopping = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (stopping) return;
    stopping = true;
    log("info", "Stopping service", { signal });
    await supervisor.stop();
    if (runtime?.bot.isRunning()) await runtime.bot.stop();
    await stopServerGracefully(server);
    database.close();
    log("info", "Service stopped");
  };
  process.once("SIGINT", () => void shutdown("SIGINT"));
  process.once("SIGTERM", () => void shutdown("SIGTERM"));

  if (runtime) {
    try {
      await configureBot(runtime.bot);
    } catch (error) {
      log("error", "Failed to configure Telegram commands", { error });
    }
  }

  if (config.BOT_MODE === "polling" && runtime) {
    void runtime.bot
      .start({
        onStart: (botInfo) => {
          status.botReady = true;
          status.botError = null;
          log("info", "Telegram polling started", { username: botInfo.username });
        },
      })
      .catch(async (error) => {
        status.botReady = false;
        status.botError = error instanceof Error ? error.message : String(error);
        log("error", "Telegram polling stopped unexpectedly", { error });
        await shutdown("TELEGRAM_POLLING_FAILED");
        process.exitCode = 1;
      });
  } else if (config.BOT_MODE === "webhook") {
    log("info", "Telegram webhook mode enabled");
  } else {
    log("info", "HTTP-only mode enabled");
  }

  log("info", "HTTP server listening", {
    address: `http://${config.BIND_HOST}:${config.PORT}`,
    mode: config.BOT_MODE,
  });
}

void main().catch((error) => {
  log("error", "Service startup failed", { error });
  process.exitCode = 1;
});
