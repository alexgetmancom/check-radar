import type { Context } from "grammy";
import type { AppConfig } from "../config.js";
import type { OpenDatabase } from "../db/client.js";

export type AppContext = Context & {
  config: AppConfig;
  database: OpenDatabase;
};
