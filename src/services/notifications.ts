export type InlineButton = { text: string; callback_data: string };
export type InlineKeyboardMarkup = { inline_keyboard: InlineButton[][] };
export type TelegramApi = {
  callApi?: (method: string, payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  raw?: Record<string, unknown>;
};

export type TelegramMessage = { message_id?: number };

function rawApi(api: unknown): TelegramApi {
  return api as TelegramApi;
}

async function callApi(
  api: unknown,
  method: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const telegramApi = rawApi(api);
  if (telegramApi.callApi) return telegramApi.callApi(method, payload);
  const rawMethod = telegramApi.raw?.[method];
  if (typeof rawMethod !== "function") throw new Error(`Telegram API method is unavailable: ${method}`);
  return (rawMethod as (payload: Record<string, unknown>) => Promise<Record<string, unknown>>)(payload);
}

export async function sendRichMessage(
  api: unknown,
  chatId: number,
  html: string,
  replyMarkup?: InlineKeyboardMarkup,
): Promise<TelegramMessage | undefined> {
  const payload: Record<string, unknown> = {
    chat_id: chatId,
    rich_message: { html },
  };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  try {
    return (await callApi(api, "sendRichMessage", payload)) as TelegramMessage;
  } catch {
    return undefined;
  }
}

export async function editRichMessage(
  api: unknown,
  chatId: number,
  messageId: number,
  html: string,
  replyMarkup?: InlineKeyboardMarkup,
): Promise<void> {
  const payload: Record<string, unknown> = {
    chat_id: chatId,
    message_id: messageId,
    rich_message: { html },
  };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  try {
    await callApi(api, "editMessageText", payload);
  } catch {
    return;
  }
}

export async function sendTextMessage(
  api: unknown,
  chatId: number,
  text: string,
  replyMarkup?: InlineKeyboardMarkup,
): Promise<TelegramMessage | undefined> {
  try {
    const payload: Record<string, unknown> = { chat_id: chatId, text, parse_mode: "HTML" };
    if (replyMarkup) payload.reply_markup = replyMarkup;
    return (await callApi(api, "sendMessage", payload)) as TelegramMessage;
  } catch {
    return undefined;
  }
}

export async function editTextMessage(
  api: unknown,
  chatId: number,
  messageId: number,
  text: string,
  replyMarkup?: InlineKeyboardMarkup,
): Promise<void> {
  const payload: Record<string, unknown> = { chat_id: chatId, message_id: messageId, text, parse_mode: "HTML" };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  try {
    await callApi(api, "editMessageText", payload);
  } catch {
    return;
  }
}

export async function setBotCommands(api: unknown): Promise<void> {
  await callApi(api, "setMyCommands", {
    commands: [
      { command: "menu", description: "Главное меню трат" },
      { command: "stats", description: "Аналитика трат за месяц (с графиком)" },
      { command: "taxi", description: "Аналитика поездок на такси (с графиком)" },
      { command: "food", description: "Аналитика трат на еду за текущий месяц" },
      { command: "find", description: "Поиск чеков по названию товара (/find сыр)" },
      { command: "backup", description: "Создать резервную копию базы данных" },
    ],
  });
}
