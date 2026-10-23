import { describe, expect, it } from "vitest";

import { prefetched } from "./prefetch";

describe("prefetched", () => {
  it("gives the value, or null on a failure or a slow answer", async () => {
    expect(await prefetched(async () => 7)).toBe(7);
    expect(await prefetched(async () => Promise.reject(new Error("down")))).toBeNull();
    expect(await prefetched(() => new Promise((resolve) => setTimeout(() => resolve(1), 200)), 20)).toBeNull();
  });
});
