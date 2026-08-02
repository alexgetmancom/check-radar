import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { AppConfig } from "../config.js";
import type { OpenDatabase } from "../db/client.js";
import { parseStoredDate } from "../db/dates.js";
import { countReceipts, type FiscalData, type ReceiptPayload, receiptExists, saveReceipt } from "../db/operations.js";
import { log } from "../logger.js";

const defaultUserAgent =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

type FnsAccount = {
  phone?: string;
  device_id: string;
  refresh_token: string;
  user_agent?: string;
};

type JsonObject = Record<string, unknown>;

class FnsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "FnsApiError";
  }
}

export type FnsNotifier = {
  notifyText: (userId: number, text: string) => Promise<void>;
  notifyRich: (userId: number, html: string) => Promise<void>;
  notifyNewReceipt: (
    userId: number,
    receipt: ReceiptPayload,
    fiscalData: FiscalData | null,
    ownerPhone?: string,
  ) => Promise<void>;
  updateDashboard: (userId: number) => Promise<void>;
};

const sleep = (milliseconds: number): Promise<void> =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

function loadCredentials(path: string): FnsAccount | FnsAccount[] | undefined {
  if (!existsSync(path)) {
    mkdirSync(dirname(resolve(path)), { recursive: true });
    writeFileSync(
      path,
      `${JSON.stringify({ device_id: "", refresh_token: "", user_agent: defaultUserAgent }, null, 2)}\n`,
    );
    return undefined;
  }
  try {
    return JSON.parse(readFileSync(path, "utf8")) as FnsAccount | FnsAccount[];
  } catch (error) {
    log("error", "Failed to read FNS credentials", { error });
    return undefined;
  }
}

function saveCredentials(path: string, credentials: FnsAccount | FnsAccount[]): void {
  writeFileSync(path, `${JSON.stringify(credentials, null, 2)}\n`);
}

async function apiRequest(
  config: AppConfig,
  path: string,
  payload: Record<string, unknown>,
  token?: string,
  userAgent = defaultUserAgent,
): Promise<JsonObject> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`${config.FNS_BASE_URL}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json;charset=UTF-8",
          "User-Agent": userAgent,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(15_000),
      });
      const body = await response.text();
      let parsed: JsonObject;
      try {
        parsed = JSON.parse(body) as JsonObject;
      } catch {
        parsed = { message: body };
      }
      if (!response.ok) {
        const error = new FnsApiError(`FNS API ${response.status}: ${String(parsed.message ?? body)}`, response.status);
        if (response.status === 400 || response.status === 401 || attempt === 2) throw error;
        lastError = error;
      } else {
        return parsed;
      }
    } catch (error) {
      lastError = error;
      if ((error instanceof FnsApiError && (error.status === 400 || error.status === 401)) || attempt === 2)
        throw error;
    }
    log("warn", "FNS request failed; retrying", { path, attempt: attempt + 1, error: lastError });
    await sleep(2_000);
  }
  throw lastError instanceof Error ? lastError : new Error("FNS request failed");
}

async function refreshAccessToken(
  config: AppConfig,
  account: FnsAccount,
  allCredentials: FnsAccount | FnsAccount[],
  notifier: FnsNotifier,
): Promise<string> {
  const userAgent = account.user_agent ?? defaultUserAgent;
  let response: JsonObject;
  try {
    response = await apiRequest(
      config,
      "/v1/auth/token",
      {
        deviceInfo: {
          appVersion: "1.0.0",
          metaDetails: { userAgent },
          sourceDeviceId: account.device_id,
          sourceType: "WEB",
        },
        refreshToken: account.refresh_token,
      },
      undefined,
      userAgent,
    );
  } catch (error) {
    if (error instanceof FnsApiError && (error.status === 400 || error.status === 401)) {
      for (const userId of config.ALLOWED_USERS) {
        await notifier.notifyText(
          userId,
          `⚠️ <b>Сессия ФНС для аккаунта ${account.phone ?? "unknown"} истекла!</b>\nПожалуйста, обновите <code>credentials.json</code>.`,
        );
      }
    }
    throw error;
  }

  if (typeof response.refreshToken === "string" && response.refreshToken !== account.refresh_token) {
    account.refresh_token = response.refreshToken;
    saveCredentials(config.FNS_CREDENTIALS_FILE, allCredentials);
  }
  if (typeof response.token !== "string" || response.token.length === 0) throw new Error("FNS token was not returned");
  return response.token;
}

async function fetchReceipts(config: AppConfig, token: string, account: FnsAccount): Promise<ReceiptPayload[]> {
  const result: ReceiptPayload[] = [];
  for (let offset = 0; ; offset += 100) {
    const response = await apiRequest(
      config,
      "/v1/receipt",
      { limit: 100, offset },
      token,
      account.user_agent ?? defaultUserAgent,
    );
    const batch = Array.isArray(response.receipts) ? (response.receipts as ReceiptPayload[]) : [];
    result.push(...batch);
    if (response.hasMore !== true || batch.length < 100) return result;
  }
}

async function fetchFiscalData(
  config: AppConfig,
  token: string,
  key: string,
  account: FnsAccount,
): Promise<FiscalData | null> {
  try {
    return (await apiRequest(
      config,
      "/v1/receipt/fiscal_data",
      { key },
      token,
      account.user_agent ?? defaultUserAgent,
    )) as FiscalData;
  } catch (error) {
    log("warn", "Failed to fetch FNS fiscal data", { key, error });
    return null;
  }
}

export async function syncReceiptsFromFns(
  config: AppConfig,
  database: OpenDatabase,
  notifier: FnsNotifier,
): Promise<number> {
  const credentials = loadCredentials(config.FNS_CREDENTIALS_FILE);
  if (!credentials) {
    log("error", "FNS credentials are missing or empty");
    return -1;
  }

  const accounts = Array.isArray(credentials) ? credentials : [credentials];
  let totalNew = 0;
  for (const account of accounts) {
    const label = account.phone ?? "unknown account";
    try {
      const token = await refreshAccessToken(config, account, credentials, notifier);
      const receipts = (await fetchReceipts(config, token, account)).sort(
        (left, right) => parseStoredDate(left.createdDate).valueOf() - parseStoredDate(right.createdDate).valueOf(),
      );
      for (const receipt of receipts) {
        if (receiptExists(database, receipt.key)) continue;
        const fiscalData = await fetchFiscalData(config, token, receipt.key, account);
        saveReceipt(database, receipt, fiscalData, account.phone);
        totalNew += 1;

        const created = parseStoredDate(receipt.createdDate).valueOf();
        const recent = created > 0 && Date.now() - created < 2 * 86_400_000;
        if (countReceipts(database) > 100 && recent) {
          for (const userId of config.ALLOWED_USERS) {
            await notifier.notifyNewReceipt(userId, receipt, fiscalData, account.phone);
            await sleep(1_000);
          }
        }
      }
    } catch (error) {
      log("error", "FNS account synchronization failed", { account: label, error });
    }
  }

  for (const userId of config.ALLOWED_USERS) await notifier.updateDashboard(userId);
  log("info", "FNS synchronization completed", { totalNew });
  return totalNew;
}

export { defaultUserAgent };
