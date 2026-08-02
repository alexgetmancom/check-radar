import { webhookCallback } from "grammy";
import type { Hono } from "hono";
import { Hono as HonoApp } from "hono";
import { logger } from "hono/logger";
import type { BotRuntime } from "./bot/bot.js";
import type { AppConfig } from "./config.js";
import type { OpenDatabase } from "./db/client.js";
import { log } from "./logger.js";
import type { RuntimeStatus } from "./runtime/status.js";

export function createHttpApp(
  config: AppConfig,
  runtime: BotRuntime | null,
  database: OpenDatabase,
  status: RuntimeStatus,
): Hono {
  const app = new HonoApp();
  if (config.NODE_ENV !== "production") app.use("*", logger());

  app.get("/", (context) => context.json({ name: config.APP_NAME, status: "ok" }));
  app.get("/healthz", (context) => context.text("ok\n"));
  app.get("/readyz", (context) => {
    try {
      database.sqlite.query("SELECT 1").get();
    } catch (error) {
      log("error", "Readiness check failed", { error });
      return context.text("error\n", 500);
    }
    if (config.BOT_MODE === "polling" && !status.botReady) return context.text("not ready\n", 503);
    return context.text("ready\n");
  });

  if (config.BOT_MODE === "webhook" && runtime) {
    if (!config.TELEGRAM_WEBHOOK_SECRET) throw new Error("TELEGRAM_WEBHOOK_SECRET is required in webhook mode");
    app.post(
      "/telegram/webhook",
      webhookCallback(runtime.bot, "hono", { secretToken: config.TELEGRAM_WEBHOOK_SECRET }),
    );
  }

  app.onError((error, context) => {
    log("error", "Unhandled HTTP error", { error, path: context.req.path });
    return context.json({ error: "Internal Server Error" }, 500);
  });
  return app;
}
