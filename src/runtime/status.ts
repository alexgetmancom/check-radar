export type BotMode = "polling" | "webhook" | "http-only";

export type RuntimeStatus = {
  botReady: boolean;
  botError: string | null;
};

export function createRuntimeStatus(botMode: BotMode): RuntimeStatus {
  return { botReady: botMode !== "polling", botError: null };
}
