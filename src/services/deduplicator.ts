import type { CleanReceipt } from "../db/operations.js";
import { getForceDeduplicateKeywords } from "./rules.js";

export function filterDuplicateReceipts(receipts: Map<string, CleanReceipt>): Set<string> {
  const sorted = [...receipts.entries()].sort(([, left], [, right]) => left.date.valueOf() - right.date.valueOf());
  const ignored = new Set<string>();
  const forceKeywords = getForceDeduplicateKeywords();

  for (let i = 0; i < sorted.length; i += 1) {
    const firstEntry = sorted[i];
    if (!firstEntry) continue;
    const [key1, first] = firstEntry;
    if (!key1) continue;
    for (let j = i + 1; j < sorted.length; j += 1) {
      const secondEntry = sorted[j];
      if (!secondEntry) continue;
      const [key2, second] = secondEntry;
      if (!key2 || first.owner !== second.owner || Math.abs(first.totalSum - second.totalSum) >= 0.1) continue;
      const days = Math.floor(Math.abs(first.date.valueOf() - second.date.valueOf()) / 86_400_000);
      if (days > 4) continue;

      const names1 = new Set(first.items.filter((item) => item.name !== "Платеж").map((item) => item.name));
      const names2 = new Set(second.items.filter((item) => item.name !== "Платеж").map((item) => item.name));
      const overlap = [...names1].some((name) => names2.has(name));
      const forced = forceKeywords.some((keyword) => [...names1].some((name) => name.toLowerCase().includes(keyword)));
      if (overlap || forced) ignored.add(key1);
    }
  }
  return ignored;
}
