import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.js";
import { RuntimeSupervisor } from "../src/runtime/supervisor.js";

describe("runtime foundation", () => {
  test("accepts HTTP-only configuration without a Telegram token", () => {
    const config = loadConfig({ BOT_MODE: "http-only", TELEGRAM_BOT_TOKEN: "", ALLOWED_USERS: "1,2" });
    expect(config.BOT_MODE).toBe("http-only");
    expect(config.ALLOWED_USERS).toEqual([1, 2]);
  });

  test("stops registered resources in reverse order", async () => {
    const events: string[] = [];
    const supervisor = new RuntimeSupervisor();
    supervisor.register({
      stop: () => {
        events.push("first");
      },
    });
    supervisor.register({
      stop: async () => {
        events.push("second");
      },
    });
    await supervisor.stop();
    expect(events).toEqual(["second", "first"]);
  });
});
