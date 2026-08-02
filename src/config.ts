import { config as loadDotenv } from "dotenv";
import { z } from "zod";

loadDotenv();

const allowedUsers = z
  .string()
  .default("7629366167,1260959328")
  .transform((value, context) => {
    if (value.trim() === "") return [];

    const ids = value.split(",").map((item) => Number(item.trim()));
    if (ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) {
      context.addIssue({
        code: "custom",
        message: "ALLOWED_USERS must contain positive integer IDs separated by commas",
      });
      return z.NEVER;
    }
    return ids;
  });

const optionalText = z.preprocess(
  (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
  z.string().min(1).optional(),
);

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  APP_NAME: z.string().min(1).default("me-checks"),
  BOT_MODE: z.enum(["polling", "webhook", "http-only"]).default("polling"),
  TELEGRAM_BOT_TOKEN: optionalText,
  TELEGRAM_API_ROOT: z.string().url().default("https://api.telegram.org"),
  TELEGRAM_WEBHOOK_SECRET: z.preprocess(
    (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
    z.string().min(32).optional(),
  ),
  PUBLIC_WEBHOOK_URL: z.preprocess(
    (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
    z.string().url().optional(),
  ),
  ALLOWED_USERS: allowedUsers,
  DATABASE_URL: z.string().min(1).default("./data/receipts.db"),
  FNS_CREDENTIALS_FILE: z.string().min(1).default("./credentials.json"),
  GMAIL_TOKEN_FILE: z.string().min(1).default("./gmail_token.json"),
  GMAIL_CLIENT_SECRET_FILE: z.string().min(1).default("./client_secret.json"),
  FNS_BASE_URL: z.string().url().default("https://lkdr.nalog.ru/api"),
  PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  BIND_HOST: z.string().min(1).default("127.0.0.1"),
  SYNC_INTERVAL_SECONDS: z.coerce.number().int().positive().default(3600),
  TZ: z.string().default("Europe/Moscow"),
});

export type AppConfig = z.infer<typeof envSchema>;

export class ConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigurationError";
  }
}

export function loadConfig(env: Record<string, string | undefined> = process.env): AppConfig {
  const result = envSchema.safeParse(env);
  if (!result.success) {
    const details = result.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ");
    throw new ConfigurationError(`Configuration validation failed: ${details}`);
  }

  if (result.data.BOT_MODE !== "http-only" && !result.data.TELEGRAM_BOT_TOKEN)
    throw new ConfigurationError("TELEGRAM_BOT_TOKEN is required in polling and webhook modes");
  if (result.data.BOT_MODE === "webhook") {
    if (!result.data.TELEGRAM_WEBHOOK_SECRET)
      throw new ConfigurationError("TELEGRAM_WEBHOOK_SECRET is required in webhook mode");
    if (!result.data.PUBLIC_WEBHOOK_URL) throw new ConfigurationError("PUBLIC_WEBHOOK_URL is required in webhook mode");
  }

  return result.data;
}
