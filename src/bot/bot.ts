import { existsSync } from "node:fs";
import { Bot, InputFile } from "grammy";
import type { AppConfig } from "../config.js";
import type { OpenDatabase } from "../db/client.js";
import { formatLocalDateTime, parseStoredDate } from "../db/dates.js";
import { getLatestReceipt, getState, setState } from "../db/operations.js";
import { log } from "../logger.js";
import {
  buildFoodReport,
  buildMonthlyStatsReport,
  buildTaxiReport,
  buildWeeklyReport,
  categorizeItems,
  checkSpendingAnomaly,
  getCleanItems,
  sumExpenses,
} from "../services/analytics.js";
import { type FnsNotifier, syncReceiptsFromFns } from "../services/fns.js";
import { formatReceiptHtml } from "../services/formatters.js";
import { syncGmailReceipts } from "../services/gmail.js";
import {
  editRichMessage,
  editTextMessage,
  type InlineKeyboardMarkup,
  sendRichMessage,
  sendTextMessage,
  setBotCommands,
} from "../services/notifications.js";
import { simplifyStoreName } from "../services/rules.js";
import type { AppContext } from "./context.js";

export type BotRuntime = {
  bot: Bot<AppContext>;
  notifier: FnsNotifier;
};

export type Dashboard = {
  html: string;
  markup: InlineKeyboardMarkup;
};

const dashboardMarkup = (): InlineKeyboardMarkup => ({
  inline_keyboard: [
    [
      { text: "📊 Месяц", callback_data: "dashboard_stats" },
      { text: "📅 Неделя", callback_data: "dashboard_week" },
    ],
    [
      { text: "🔄 Обновить", callback_data: "dashboard_sync" },
      { text: "ℹ️ Справка", callback_data: "dashboard_help" },
    ],
  ],
});

function monthName(month: number): string {
  return (
    [
      "Январь",
      "Февраль",
      "Март",
      "Апрель",
      "Май",
      "Июнь",
      "Июль",
      "Август",
      "Сентябрь",
      "Октябрь",
      "Ноябрь",
      "Декабрь",
    ][month] ?? "Неизвестно"
  );
}

export function getDashboard(database: OpenDatabase): Dashboard {
  const now = new Date();
  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const monthCategories = categorizeItems(
    getCleanItems(database, formatLocalDateTime(startOfMonth), formatLocalDateTime(now)),
  );
  const monthTotal = sumExpenses(monthCategories);

  const startOfThisWeek = new Date(now);
  startOfThisWeek.setHours(0, 0, 0, 0);
  startOfThisWeek.setDate(
    startOfThisWeek.getDate() - startOfThisWeek.getDay() + (startOfThisWeek.getDay() === 0 ? -6 : 1),
  );
  const startOfLastWeek = new Date(startOfThisWeek);
  startOfLastWeek.setDate(startOfLastWeek.getDate() - 7);
  const endOfLastWeek = new Date(startOfThisWeek);
  endOfLastWeek.setDate(endOfLastWeek.getDate() - 1);
  const thisWeekCategories = categorizeItems(
    getCleanItems(database, formatLocalDateTime(startOfThisWeek), formatLocalDateTime(now)),
  );
  const lastWeekCategories = categorizeItems(
    getCleanItems(database, formatLocalDateTime(startOfLastWeek), formatLocalDateTime(endOfLastWeek)),
  );
  const thisWeekTotal = sumExpenses(thisWeekCategories);
  const lastWeekTotal = sumExpenses(lastWeekCategories);
  const monthIncome = monthCategories.Доходы ?? 0;

  const latest = getLatestReceipt(database);
  const lastReceipt = latest
    ? `🛍 ${parseStoredDate(latest.date).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${simplifyStoreName(latest.owner)} · <b>${latest.total.toFixed(0)} ₽</b>`
    : "Нет трат";

  const html =
    `📅 <b>${monthName(now.getMonth())}:</b> <code>${monthTotal.toFixed(2)} ₽</code>\n\n` +
    `🗓 <b>Неделя:</b> <code>${thisWeekTotal.toFixed(2)} ₽</code> <i>(vs ${lastWeekTotal.toFixed(0)} ₽)</i>\n\n` +
    (monthIncome > 0 ? `📈 <b>Доходы за месяц:</b> <code>${monthIncome.toFixed(2)} ₽</code>\n\n` : "") +
    `${lastReceipt}\n\n` +
    `<i>Обновлено: ${now.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</i>`;
  return { html, markup: dashboardMarkup() };
}

function backMarkup(): InlineKeyboardMarkup {
  return { inline_keyboard: [[{ text: "◀️ Назад", callback_data: "dashboard_back" }]] };
}

function foodMarkup(): InlineKeyboardMarkup {
  return {
    inline_keyboard: [
      [{ text: "🛒 Детализация продуктов", callback_data: "dashboard_food_stats" }],
      [{ text: "◀️ Назад", callback_data: "dashboard_back" }],
    ],
  };
}

async function updateDashboardIfExists(bot: Bot<AppContext>, database: OpenDatabase, chatId: number): Promise<void> {
  const messageId = getState(database, `dashboard_message_id_${chatId}`);
  if (!messageId) return;
  const dashboard = getDashboard(database);
  await editTextMessage(bot.api, chatId, Number(messageId), dashboard.html, dashboard.markup);
}

async function sendDashboard(bot: Bot<AppContext>, database: OpenDatabase, chatId: number): Promise<void> {
  const dashboard = getDashboard(database);
  const oldMessageId = getState(database, `dashboard_message_id_${chatId}`);
  if (oldMessageId) {
    try {
      await bot.api.deleteMessage(chatId, Number(oldMessageId));
    } catch {
      // The old dashboard may already have been deleted by the user.
    }
  }
  const sent = await sendTextMessage(bot.api, chatId, dashboard.html, dashboard.markup);
  if (sent?.message_id) setState(database, `dashboard_message_id_${chatId}`, String(sent.message_id));
}

async function runSync(config: AppConfig, database: OpenDatabase, notifier: FnsNotifier): Promise<number> {
  const fnsCount = await syncReceiptsFromFns(config, database, notifier);
  const gmailCount = await syncGmailReceipts(config, database, notifier);
  return Math.max(0, fnsCount) + Math.max(0, gmailCount);
}

function commandArgs(ctx: AppContext): string {
  const text = ctx.message?.text ?? "";
  return text.replace(/^\/\S+(?:@\S+)?\s*/u, "").trim();
}

function helpText(): string {
  return (
    "👋 <b>Finance Bot: Справка по командам</b>\n\n" +
    "• Нажмите <b>🔄 Обновить</b> для синхронизации с ФНС.\n" +
    "• Нажмите <b>📊 Месяц</b> или введите <code>/stats</code> для выгрузки структуры трат.\n" +
    "• Введите <code>/food</code> для детальной статистики расходов на продукты.\n" +
    "• Введите <code>/taxi</code> для подробного лога и аналитики поездок.\n" +
    "• Введите <code>/backup</code> для бэкапа базы данных.\n" +
    "• Нажмите <b>📅 Неделя</b> для сравнения с прошлой неделей.\n\n" +
    "🔍 <b>Для поиска товара</b> используйте текстовую команду: \n<code>/find сыр</code>"
  );
}

function searchResults(database: OpenDatabase, query: string): string | undefined {
  const allRows = database.sqlite
    .query(
      "SELECT r.created_date, r.kkt_owner, i.name, i.price FROM items i JOIN receipts r ON i.receipt_key = r.key WHERE i.name LIKE ?",
    )
    .all(`%${query}%`) as Array<{ created_date?: string; kkt_owner?: string; name?: string; price?: number }>;
  const rows = allRows
    .sort((left, right) => parseStoredDate(right.created_date).valueOf() - parseStoredDate(left.created_date).valueOf())
    .slice(0, 10);
  if (rows.length === 0) return undefined;

  let html = `<h1>🔍 Результаты поиска «${query}»</h1><table bordered striped><tr><th>Дата</th><th>Магазин</th><th>Товар</th><th>Цена</th></tr>`;
  for (const row of rows) {
    const date = parseStoredDate(row.created_date);
    html += `<tr><td>${date.toLocaleDateString("ru-RU")}</td><td>${simplifyStoreName(row.kkt_owner)}</td><td>${(row.name ?? "").slice(0, 25)}...</td><td><b>${(row.price ?? 0).toFixed(2)} ₽</b></td></tr>`;
  }
  return `${html}</table><footer>Показаны последние 10 покупок</footer>`;
}

function registerHandlers(
  bot: Bot<AppContext>,
  config: AppConfig,
  database: OpenDatabase,
  notifier: FnsNotifier,
): void {
  bot.use(async (ctx, next) => {
    ctx.config = config;
    ctx.database = database;
    if (config.ALLOWED_USERS.length > 0 && (!ctx.from || !config.ALLOWED_USERS.includes(ctx.from.id))) {
      if (ctx.callbackQuery) await ctx.answerCallbackQuery({ text: "🔒 Доступ ограничен.", show_alert: true });
      else if (ctx.message)
        await ctx.reply("🔒 Доступ ограничен. Этот бот является персональным финансовым ассистентом.");
      return;
    }
    await next();
  });

  bot.command(["start", "help", "menu"], (ctx) => sendDashboard(bot, database, ctx.chat.id));

  bot.command("sync", async (ctx) => {
    const status = await ctx.reply("🔄 Запускаю синхронизацию с ФНС и почтой...");
    try {
      const total = await runSync(config, database, notifier);
      await ctx.api.editMessageText(
        ctx.chat.id,
        status.message_id,
        `✅ Синхронизация успешно завершена! Добавлено новых чеков: <b>${total}</b>.`,
        { parse_mode: "HTML" },
      );
    } catch (error) {
      log("error", "Manual synchronization failed", { error });
      await ctx.api.editMessageText(
        ctx.chat.id,
        status.message_id,
        "❌ Произошла ошибка при подключении к ФНС или почте.",
      );
    }
  });

  bot.command("week", (ctx) => sendRichMessage(bot.api, ctx.chat.id, buildWeeklyReport(database)));

  bot.command("food", async (ctx) => {
    const html = buildFoodReport(database);
    if (html)
      await sendRichMessage(bot.api, ctx.chat.id, html, {
        inline_keyboard: [[{ text: "📊 Назад к общей статистике", callback_data: "dashboard_stats" }]],
      });
    else await ctx.reply("🛒 В этом месяце расходов на продукты питания пока нет.");
  });

  bot.command("taxi", async (ctx) => {
    const report = buildTaxiReport(database);
    if (!report.html) {
      await ctx.reply("🚕 Расходов на такси в этом месяце пока нет.");
      return;
    }
    if (report.chartUrl) await ctx.replyWithPhoto(report.chartUrl);
    await sendRichMessage(bot.api, ctx.chat.id, report.html);
  });

  bot.command("backup", async (ctx) => {
    await ctx.reply("📦 Подготавливаю резервную копию базы данных...");
    if (!existsSync(database.path)) {
      await ctx.reply("❌ Файл базы данных не найден.");
      return;
    }
    try {
      await ctx.replyWithDocument(new InputFile(database.path), {
        caption: `Резервная копия базы данных (${new Date().toLocaleString("ru-RU")})`,
      });
    } catch (error) {
      log("error", "Database backup delivery failed", { error });
      await ctx.reply("❌ Не удалось отправить файл базы данных.");
    }
  });

  bot.command("find", async (ctx) => {
    const query = commandArgs(ctx);
    if (!query) {
      await ctx.reply("🔍 Введите поисковый запрос, например: <code>/find сыр</code>", { parse_mode: "HTML" });
      return;
    }
    const html = searchResults(database, query);
    if (!html) await ctx.reply(`🔍 По запросу «${query}» ничего не найдено.`);
    else await sendRichMessage(bot.api, ctx.chat.id, html);
  });

  bot.command("stats", async (ctx) => {
    const report = buildMonthlyStatsReport(database);
    if (!report.html) {
      await ctx.reply("📊 В этом месяце расходов пока нет.");
      return;
    }
    if (report.chartUrl) await ctx.replyWithPhoto(report.chartUrl);
    await sendRichMessage(bot.api, ctx.chat.id, report.html, foodMarkup());
  });

  bot.callbackQuery(/^dashboard_/, async (ctx) => {
    const data = ctx.callbackQuery.data;
    const message = ctx.callbackQuery.message;
    if (!message || !("chat" in message) || !("message_id" in message)) {
      await ctx.answerCallbackQuery();
      return;
    }
    const chatId = message.chat.id;
    const messageId = message.message_id;
    try {
      if (data === "dashboard_sync") {
        await ctx.answerCallbackQuery({ text: "🔄 Запущена синхронизация..." });
        const total = await runSync(config, database, notifier);
        const dashboard = getDashboard(database);
        await editTextMessage(bot.api, chatId, messageId, dashboard.html, dashboard.markup);
        log("info", "Dashboard synchronization completed", { chatId, total });
        return;
      }

      await ctx.answerCallbackQuery();
      if (data === "dashboard_stats") {
        const report = buildMonthlyStatsReport(database);
        if (report.html) {
          const html = report.chartUrl ? `<a href="${report.chartUrl}">&#8203;</a>${report.html}` : report.html;
          await editRichMessage(bot.api, chatId, messageId, html, foodMarkup());
        } else {
          await editTextMessage(bot.api, chatId, messageId, "📊 В этом месяце расходов пока нет.", backMarkup());
        }
      } else if (data === "dashboard_food_stats") {
        const html = buildFoodReport(database);
        if (html) {
          await editRichMessage(bot.api, chatId, messageId, html, {
            inline_keyboard: [
              [{ text: "📊 Назад к общей статистике", callback_data: "dashboard_stats" }],
              [{ text: "🏠 В меню", callback_data: "dashboard_back" }],
            ],
          });
        } else {
          await editTextMessage(
            bot.api,
            chatId,
            messageId,
            "🛒 В этом месяце расходов на продукты питания пока нет.",
            backMarkup(),
          );
        }
      } else if (data === "dashboard_week") {
        await editRichMessage(bot.api, chatId, messageId, buildWeeklyReport(database), backMarkup());
      } else if (data === "dashboard_help") {
        await editTextMessage(bot.api, chatId, messageId, helpText(), backMarkup());
      } else if (data === "dashboard_back") {
        const dashboard = getDashboard(database);
        await editTextMessage(bot.api, chatId, messageId, dashboard.html, dashboard.markup);
      }
    } catch (error) {
      log("error", "Dashboard callback failed", { data, error });
    }
  });
}

export function createNoopNotifier(): FnsNotifier {
  return {
    notifyText: async () => undefined,
    notifyRich: async () => undefined,
    notifyNewReceipt: async () => undefined,
    updateDashboard: async () => undefined,
  };
}

export function createBot(config: AppConfig, database: OpenDatabase): BotRuntime {
  if (!config.TELEGRAM_BOT_TOKEN) throw new Error("TELEGRAM_BOT_TOKEN is required to create a Telegram bot");
  const bot = new Bot<AppContext>(config.TELEGRAM_BOT_TOKEN, { client: { apiRoot: config.TELEGRAM_API_ROOT } });
  const notifier: FnsNotifier = {
    notifyText: async (userId, text) => {
      await sendTextMessage(bot.api, userId, text);
    },
    notifyRich: async (userId, html) => {
      await sendRichMessage(bot.api, userId, html);
    },
    notifyNewReceipt: async (userId, receipt, fiscalData, ownerPhone) => {
      await sendRichMessage(bot.api, userId, formatReceiptHtml(receipt, fiscalData, ownerPhone));
      const anomaly = checkSpendingAnomaly(database);
      if (anomaly) {
        const [todayTotal, average, ratio] = anomaly;
        await sendRichMessage(
          bot.api,
          userId,
          `<h1>⚠️ Аномалия трат за день!</h1><p>Сегодня вы потратили уже <b>${todayTotal.toFixed(2)} ₽</b>.</p><blockquote>Это в <b>${ratio.toFixed(1)} раз(а)</b> превышает ваш средний дневной расход за месяц (${average.toFixed(2)} ₽).</blockquote>`,
        );
      }
    },
    updateDashboard: (userId) => updateDashboardIfExists(bot, database, userId),
  };
  registerHandlers(bot, config, database, notifier);
  bot.catch((error) => {
    log("error", "Telegram update failed", { updateId: error.ctx.update.update_id, error: error.error });
  });
  return { bot, notifier };
}

export async function configureBot(bot: Bot<AppContext>): Promise<void> {
  await setBotCommands(bot.api);
}
