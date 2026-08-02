import { existsSync, readFileSync, writeFileSync } from "node:fs";
import type { AppConfig } from "../config.js";
import type { OpenDatabase } from "../db/client.js";
import { formatLocalDateTime, parseStoredDate } from "../db/dates.js";
import {
  type FiscalData,
  type ReceiptPayload,
  receiptExists,
  saveReceipt,
  saveTaxiTrip,
  type TaxiTripInput,
} from "../db/operations.js";
import { log } from "../logger.js";
import type { FnsNotifier } from "./fns.js";
import { parseHtmlTokens } from "./html.js";

type GmailMessage = { id: string };
type GmailPart = {
  mimeType?: string;
  body?: { data?: string };
  parts?: GmailPart[];
  headers?: Array<{ name?: string; value?: string }>;
};
type GmailDetail = GmailPart & {
  payload?: GmailPart;
  internalDate?: string | number;
  snippet?: string;
  messages?: GmailMessage[];
};
type GmailTokens = {
  access_token?: string;
  refresh_token?: string;
  expires_at?: number;
  [key: string]: unknown;
};
type GmailTokenResponse = {
  access_token?: string;
  expires_in?: number;
};
type ParsedImport = { receipt: ReceiptPayload; fiscalData: FiscalData; taxi?: TaxiTripInput };

const sleep = (milliseconds: number): Promise<void> =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
let cbrRates: { USD: number; EUR: number } | undefined;
let cbrRatesUpdatedAt = 0;

function tokenFile(config: AppConfig): string {
  return config.GMAIL_TOKEN_FILE;
}

export async function refreshGmailToken(config: AppConfig): Promise<string | undefined> {
  if (!existsSync(config.GMAIL_TOKEN_FILE) || !existsSync(config.GMAIL_CLIENT_SECRET_FILE)) return undefined;
  const tokens = JSON.parse(readFileSync(config.GMAIL_TOKEN_FILE, "utf8")) as GmailTokens;
  if (tokens.access_token && Number(tokens.expires_at ?? 0) > Math.floor(Date.now() / 1000) + 60)
    return String(tokens.access_token);

  const client = JSON.parse(readFileSync(config.GMAIL_CLIENT_SECRET_FILE, "utf8")) as {
    installed?: Record<string, string>;
  };
  const installed = client.installed ?? {};
  const body = new URLSearchParams({
    refresh_token: String(tokens.refresh_token ?? ""),
    client_id: String(installed.client_id ?? ""),
    client_secret: String(installed.client_secret ?? ""),
    grant_type: "refresh_token",
  });
  try {
    const response = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!response.ok) throw new Error(`Gmail token refresh failed: HTTP ${response.status}`);
    const refreshed = (await response.json()) as GmailTokenResponse;
    if (!refreshed.access_token) throw new Error("Gmail access token was not returned");
    tokens.access_token = refreshed.access_token;
    tokens.expires_at = Math.floor(Date.now() / 1000) + Number(refreshed.expires_in ?? 3600);
    writeFileSync(tokenFile(config), `${JSON.stringify(tokens, null, 2)}\n`);
    return String(tokens.access_token);
  } catch (error) {
    log("error", "Gmail token refresh failed", { error });
    return undefined;
  }
}

async function gmailApiRequest(config: AppConfig, path: string): Promise<GmailDetail | undefined> {
  const token = await refreshGmailToken(config);
  if (!token) return undefined;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`https://gmail.googleapis.com/gmail/v1${path}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) throw new Error(`Gmail API HTTP ${response.status}`);
      return (await response.json()) as GmailDetail;
    } catch (error) {
      log("warn", "Gmail request failed; retrying", { path, attempt: attempt + 1, error });
      if (attempt === 2) return undefined;
      await sleep(2_000);
    }
  }
  return undefined;
}

export function extractHtmlBody(payload: GmailPart): string {
  const extract = (part: GmailPart): string => {
    const mimeType = part.mimeType ?? "";
    const bodyData = part.body?.data ?? "";
    if (mimeType === "text/html" && bodyData) return Buffer.from(bodyData, "base64url").toString("utf8");
    for (const child of part.parts ?? []) {
      const html = extract(child);
      if (html) return html;
    }
    return "";
  };
  const html = extract(payload);
  if (html) return html;
  const bodyData = payload.body?.data ?? "";
  return bodyData ? Buffer.from(bodyData, "base64url").toString("utf8") : "";
}

export function parseFastenRideHtml(html: string): [string, string, number] {
  const tokens = parseHtmlTokens(html);
  const routes = tokens.filter((token) => token.attrs.class?.includes("route__name")).map((token) => token.text);
  let price = 0;
  for (const token of tokens) {
    if (token.attrs.class?.includes("check__price")) {
      const match = token.text
        .replaceAll(" ", "")
        .replaceAll("\u00a0", "")
        .match(/(\d+(?:\.\d+)?)/);
      if (match?.[1]) {
        price = Number(match[1]);
        if (price > 0) break;
      }
    }
  }
  if (price === 0) {
    for (const token of tokens) {
      if (!token.text.includes("₽")) continue;
      const match = token.text
        .replaceAll(" ", "")
        .replaceAll("\u00a0", "")
        .match(/(\d+(?:\.\d+)?)/);
      if (match?.[1]) {
        price = Number(match[1]);
        break;
      }
    }
  }
  return [routes[0] ?? "Неизвестно", routes[1] ?? "Неизвестно", price];
}

export function parseYandexTaxiHtml(html: string): [string, string, number, string, number, number, number] {
  const textList = parseHtmlTokens(html).map((token) => token.text);
  let start = "Неизвестно";
  let end = "Неизвестно";
  let price = 0;
  let tariff = "Эконом";
  let distance = 0;
  let duration = 0;
  let tips = 0;

  for (let index = 0; index < textList.length; index += 1) {
    const text = textList[index] ?? "";
    const lower = text.toLowerCase();
    const next = textList[index + 1] ?? "";
    if (lower.includes("откуда") || lower.includes("адрес подачи") || text === "А") start = next;
    if (lower.includes("куда") || lower.includes("адрес назначения") || text === "Б") end = next;
    for (const candidate of ["эконом", "комфорт+", "комфорт", "бизнес", "ultima", "детский", "минивэн"]) {
      if (lower.includes(candidate) && text.length < 15) tariff = text.charAt(0).toUpperCase() + text.slice(1);
    }
    if (lower.includes("км") || lower.includes("km")) {
      const match = lower.match(/(\d+(?:\.\d+)?)\s*(?:км|km)/);
      if (match?.[1]) distance = Number(match[1]);
    }
    if (lower.includes("мин") || lower.includes("min")) {
      const match = lower.match(/(\d+)\s*(?:мин|min)/);
      if (match?.[1]) duration = Number(match[1]);
    }
    if (lower.includes("итого") || lower.includes("всего")) {
      const match = next
        .replaceAll(" ", "")
        .replaceAll("\u00a0", "")
        .match(/(\d+(?:\.\d+)?)/);
      if (match?.[1]) price = Number(match[1]);
    }
    if (lower.includes("чаевые")) {
      const match = next
        .replaceAll(" ", "")
        .replaceAll("\u00a0", "")
        .match(/(\d+(?:\.\d+)?)/);
      if (match?.[1]) tips = Number(match[1]);
    }
  }

  if (price === 0) {
    for (const text of textList) {
      if (
        !text.includes("₽") ||
        !(
          text.toLowerCase().includes("итого") ||
          text.toLowerCase().includes("стоимость") ||
          text.toLowerCase().includes("оплата")
        )
      )
        continue;
      const match = text.replaceAll(" ", "").match(/(\d+(?:\.\d+)?)/);
      if (match?.[1]) {
        price = Number(match[1]);
        break;
      }
    }
  }
  if (start === "Неизвестно" || end === "Неизвестно") {
    const addresses = textList.filter((text) =>
      ["ул.", "просп.", "д.", "проспект", "шоссе", "бульвар", "пер.", "переулок"].some((marker) =>
        text.toLowerCase().includes(marker),
      ),
    );
    if (addresses.length >= 2) {
      if (start === "Неизвестно") start = addresses[0] ?? start;
      if (end === "Неизвестно") end = addresses[1] ?? end;
    }
  }
  return [start, end, price, tariff, distance, duration, tips];
}

export function parseTrytekPayment(snippet: string): number {
  const match = snippet.match(/Сумма\s*([\d\s]+)\s*₽/);
  return match?.[1] ? Number(match[1].replaceAll(" ", "").replaceAll("\u00a0", "")) : 0;
}

export async function getCbrRates(): Promise<{ USD: number; EUR: number }> {
  if (cbrRates && Date.now() - cbrRatesUpdatedAt < 3_600_000) return cbrRates;
  try {
    const response = await fetch("https://www.cbr-xml-daily.ru/daily_json.js", {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(10_000),
    });
    const data = (await response.json()) as { Valute?: Record<string, { Value: number }> };
    const rates = { USD: Number(data.Valute?.USD?.Value ?? 0), EUR: Number(data.Valute?.EUR?.Value ?? 0) };
    if (rates.USD > 0 && rates.EUR > 0) {
      cbrRates = rates;
      cbrRatesUpdatedAt = Date.now();
      return rates;
    }
  } catch (error) {
    log("warn", "Failed to fetch CBR exchange rates; using fallback", { error });
  }
  return { USD: 90, EUR: 98 };
}

export async function convertToRub(amount: number, currency: string): Promise<number> {
  const rates = await getCbrRates();
  if (currency === "$") return amount * rates.USD;
  if (currency === "€") return amount * rates.EUR;
  return amount;
}

export function parseTimewebIncome(snippet: string): [number, string] {
  const amount = snippet.match(/зачислено\s*(\d+(?:\.\d+)?)\s*от/)?.[1];
  const client = snippet.match(/клиента\s*(\w+)/)?.[1];
  return [amount ? Number(amount.replaceAll(" ", "").replaceAll("\u00a0", "")) : 0, client ?? "Неизвестно"];
}

export function parseStripeReceipt(subject: string, html: string): [string, number, string] {
  let merchant = "Stripe Merchant";
  const fromMatch = subject.match(/from\s+([^#]+)/i) ?? subject.match(/от\s+(.+)$/i);
  if (fromMatch?.[1]) merchant = fromMatch[1].trim();
  for (const suffix of ["#", "№", ..."0123456789"]) {
    const index = merchant.indexOf(suffix);
    if (index >= 0) merchant = merchant.slice(0, index).trim();
  }
  let amount = 0;
  let currency = "$";
  for (const token of parseHtmlTokens(html)) {
    const match = token.text.match(/^([$€])\s*(\d+(?:\.\d+)?)$/);
    if (match?.[1] && match[2]) {
      currency = match[1];
      amount = Number(match[2]);
      break;
    }
  }
  if (amount === 0) {
    for (const token of parseHtmlTokens(html)) {
      const match = token.text.match(/([$€])\s*(\d+(?:\.\d+)?)/);
      if (match?.[1] && match[2]) {
        currency = match[1];
        amount = Number(match[2]);
        break;
      }
    }
  }
  return [merchant, amount, currency];
}

export function parseSpotifyPlan(subject: string): [string, number] {
  const lower = subject.toLowerCase();
  if (lower.includes("individual")) return ["Premium Individual", 10.99];
  if (lower.includes("family")) return ["Premium Family", 16.99];
  if (lower.includes("student")) return ["Premium Student", 5.99];
  return ["Premium Duo", 14.99];
}

function header(detail: GmailDetail, name: string): string {
  const headers = detail.payload?.headers ?? [];
  return headers.find((item) => item.name?.toLowerCase() === name.toLowerCase())?.value ?? "";
}

function timestamp(detail: GmailDetail): string {
  return formatLocalDateTime(new Date(Number(detail.internalDate ?? Date.now())));
}

async function processMessages(
  config: AppConfig,
  database: OpenDatabase,
  notifier: FnsNotifier,
  query: string,
  keyFor: (messageId: string) => string,
  build: (messageId: string, detail: GmailDetail) => Promise<ParsedImport | undefined>,
): Promise<number> {
  const encoded = encodeURIComponent(query);
  const list = await gmailApiRequest(config, `/users/me/messages?q=${encoded}&maxResults=10`);
  let count = 0;
  for (const message of list?.messages ?? []) {
    const key = keyFor(message.id);
    if (receiptExists(database, key)) continue;
    const detail = await gmailApiRequest(config, `/users/me/messages/${message.id}?format=full`);
    if (!detail) continue;
    const parsed = await build(key, detail);
    if (!parsed || Number(parsed.receipt.totalSum ?? 0) <= 0) continue;
    saveReceipt(database, parsed.receipt, parsed.fiscalData, parsed.receipt.ownerPhone);
    if (parsed.taxi) saveTaxiTrip(database, parsed.taxi);
    count += 1;
    const created = parseStoredDate(parsed.receipt.createdDate).valueOf();
    const recent = created > 0 && Date.now() - created < 2 * 86_400_000;
    if (recent) {
      for (const userId of config.ALLOWED_USERS) {
        await notifier.notifyNewReceipt(
          userId,
          parsed.receipt,
          parsed.fiscalData,
          parsed.receipt.ownerPhone ?? undefined,
        );
        await sleep(1_000);
      }
    }
  }
  return count;
}

export async function syncGmailReceipts(
  config: AppConfig,
  database: OpenDatabase,
  notifier: FnsNotifier,
): Promise<number> {
  if (!existsSync(config.GMAIL_TOKEN_FILE)) {
    log("info", "Gmail integration is not configured");
    return 0;
  }

  let total = 0;
  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:no-reply@taxi.yandex.ru subject:("Поездка" OR "Отчет")',
      (id) => `gmail_${id}`,
      async (key, detail) => {
        const [from, to, price, tariff, distance, duration, tips] = parseYandexTaxiHtml(
          extractHtmlBody(detail.payload ?? {}),
        );
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: price,
            kktOwner: 'ООО "ЯНДЕКС.ТАКСИ"',
            kktOwnerInn: "",
            buyer: "",
          },
          fiscalData: {
            items: [
              { name: `Поездка: ${from} -> ${to}`, price: price - tips, quantity: 1, sum: price - tips },
              ...(tips > 0 ? [{ name: "Чаевые водителю", price: tips, quantity: 1, sum: tips }] : []),
            ],
          },
          taxi: {
            receiptKey: key,
            date: timestamp(detail),
            tariffClass: tariff,
            fromAddress: from,
            toAddress: to,
            distanceKm: distance,
            durationMins: duration,
            fareCost: price - tips,
            tipsCost: tips,
            totalCost: price,
          },
        };
      },
    );
  } catch (error) {
    log("error", "Yandex Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:no-reply@fasten.com subject:"Fasten: ride report"',
      (id) => `gmail_${id}`,
      async (key, detail) => {
        const [from, to, price] = parseFastenRideHtml(extractHtmlBody(detail.payload ?? {}));
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: price,
            kktOwner: "Fasten",
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: { items: [{ name: `Поездка: ${from} -> ${to}`, price, quantity: 1, sum: price }] },
          taxi: {
            receiptKey: key,
            date: timestamp(detail),
            tariffClass: "Эконом",
            fromAddress: from,
            toAddress: to,
            distanceKm: 0,
            durationMins: 0,
            fareCost: price,
            tipsCost: 0,
            totalCost: price,
          },
        };
      },
    );
  } catch (error) {
    log("error", "Fasten Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:inform@yoomoney.ru subject:"Информация о платеже" trytek.ru',
      (id) => `gmail_${id}`,
      async (key, detail) => {
        const price = parseTrytekPayment(String(detail.snippet ?? ""));
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: price,
            kktOwner: "Трайтек",
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: { items: [{ name: "Оплата интернета Трайтек", price, quantity: 1, sum: price }] },
        };
      },
    );
  } catch (error) {
    log("error", "Trytek Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:partner@timeweb.ru subject:"На Ваш счёт вебмастера зачислено вознаграждение"',
      (id) => `gmail_timeweb_${id}`,
      async (key, detail) => {
        const [amount, client] = parseTimewebIncome(String(detail.snippet ?? ""));
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: amount,
            kktOwner: "Timeweb (Доход)",
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: {
            items: [
              { name: `Партнерское вознаграждение от клиента ${client}`, price: amount, quantity: 1, sum: amount },
            ],
          },
        };
      },
    );
  } catch (error) {
    log("error", "Timeweb Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:no-reply@spotify.com subject:"Your order confirmation for"',
      (id) => `gmail_spotify_${id}`,
      async (key, detail) => {
        const [plan, usd] = parseSpotifyPlan(header(detail, "subject"));
        const rub = await convertToRub(usd, "$");
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: rub,
            kktOwner: "Spotify",
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: {
            items: [{ name: `Подписка Spotify: ${plan} ($${usd.toFixed(2)})`, price: rub, quantity: 1, sum: rub }],
          },
        };
      },
    );
  } catch (error) {
    log("error", "Spotify Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:stripe.com subject:("Your receipt from" OR "Ваша квитанция" OR "квитанция")',
      (id) => `gmail_stripe_${id}`,
      async (key, detail) => {
        const [merchant, amount, currency] = parseStripeReceipt(
          header(detail, "subject"),
          extractHtmlBody(detail.payload ?? {}),
        );
        const rub = await convertToRub(amount, currency);
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: rub,
            kktOwner: merchant,
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: {
            items: [
              { name: `Платеж ${merchant} (${currency}${amount.toFixed(2)})`, price: rub, quantity: 1, sum: rub },
            ],
          },
        };
      },
    );
  } catch (error) {
    log("error", "Stripe Gmail synchronization failed", { error });
  }

  try {
    total += await processMessages(
      config,
      database,
      notifier,
      'from:noreply@tm.openai.com subject:"ChatGPT — ваш новый план"',
      (id) => `gmail_openai_${id}`,
      async (key, detail) => {
        const rub = await convertToRub(20, "$");
        return {
          receipt: {
            key,
            createdDate: timestamp(detail),
            receiveDate: timestamp(detail),
            totalSum: rub,
            kktOwner: "OpenAI (ChatGPT)",
            kktOwnerInn: "",
            buyer: "",
            ownerPhone: "79639629392",
          },
          fiscalData: { items: [{ name: "Подписка ChatGPT Plus ($20.00)", price: rub, quantity: 1, sum: rub }] },
        };
      },
    );
  } catch (error) {
    log("error", "OpenAI Gmail synchronization failed", { error });
  }

  if (total > 0) for (const userId of config.ALLOWED_USERS) await notifier.updateDashboard(userId);
  log("info", "Gmail synchronization completed", { total });
  return total;
}
