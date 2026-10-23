import { describe, expect, it } from "vitest";

import { HttpError } from "./api";
import { COLD_HINT, failureMessage, OFFLINE, SERVER, SLOW_HINT, waitedText, waitingHint } from "./failure";

describe("failureMessage", () => {
  it("tells a lost connection from a server failure", () => {
    expect(failureMessage(new Error("x"), "기본", false)).toBe(OFFLINE);
    expect(failureMessage(new TypeError("Failed to fetch"), "기본", true)).toBe(OFFLINE);
    expect(failureMessage(new HttpError(503), "기본", true)).toBe(SERVER);
  });

  it("keeps the page's own wording otherwise", () => {
    expect(failureMessage(new HttpError(400), "기본", true)).toBe("기본");
    expect(failureMessage(new Error("x"), "기본", true)).toBe("기본");
  });
});

describe("waiting", () => {
  it("counts seconds, then minutes", () => {
    expect(waitedText(9)).toBe("9초");
    expect(waitedText(75)).toBe("1분 15초");
  });

  it("explains a waking server only before anything came back, and a slow one after a minute", () => {
    expect(waitingHint(5, false)).toBeNull();
    expect(waitingHint(10, false)).toBe(COLD_HINT);
    expect(waitingHint(10, true)).toBeNull();
    expect(waitingHint(61, true)).toBe(SLOW_HINT);
  });
});
