import { expect, test } from "bun:test";
import { sendTextMessage, setBotCommands } from "../src/services/notifications.js";

test("Telegram notification helpers support grammY raw APIs", async () => {
  const calls: string[] = [];
  const api = {
    raw: {
      setMyCommands: async () => {
        calls.push("setMyCommands");
        return {};
      },
      sendMessage: async () => {
        calls.push("sendMessage");
        return { message_id: 42 };
      },
    },
  };

  await setBotCommands(api);
  const message = await sendTextMessage(api, 1, "Test");

  expect(calls).toEqual(["setMyCommands", "sendMessage"]);
  expect(message).toEqual({ message_id: 42 });
});
