import { describe, expect, it } from "vitest";

import {
  clearDevice,
  type KeyValue,
  loadThreads,
  MAX_THREADS,
  MAX_TURNS_PER_THREAD,
  messagesOf,
  NOTICE_KEY,
  PROFILE_KEY,
  recordTurn,
  saveThreads,
  takeNotice,
  type Thread,
  THREADS_KEY,
} from "./store";

class Memory implements KeyValue {
  items = new Map<string, string>();
  quota = Infinity;
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    if (value.length > this.quota) throw new Error("QuotaExceededError");
    this.items.set(key, value);
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
}

const id = (n: number) => n.toString(16).padStart(32, "0");
const thread = (n: number, extra: Partial<Thread> = {}): Thread => ({
  id: id(n),
  title: `대화 ${n}`,
  created_at: `2020-01-${String(n).padStart(2, "0")}T00:00:00Z`,
  updated_at: `2020-01-${String(n).padStart(2, "0")}T00:00:00Z`,
  turns: [{ question: `q${n}`, answer: `a${n}`, route: "rag", evidence_ids: [], at: "2026-10-01T00:00:00Z" }],
  ...extra,
});

describe("loadThreads", () => {
  it("drops broken, repeated and hand-edited records and sorts newest first", () => {
    const storage = new Memory();
    storage.setItem(
      THREADS_KEY,
      JSON.stringify([
        thread(1),
        thread(3),
        thread(3),
        { id: "not-hex", turns: [] },
        { ...thread(2), turns: [{ question: 1 }] },
        { ...thread(4), route: "x", turns: [{ question: " q\u0000 ", answer: "a", route: "hack" }] },
      ]),
    );
    const threads = loadThreads(storage);
    expect(threads.map((t) => t.id)).toEqual([id(4), id(3), id(1)]);
    expect(threads[0].turns[0]).toMatchObject({ question: "q", route: "none" });
  });

  it("returns nothing for missing or unreadable storage", () => {
    expect(loadThreads(null)).toEqual([]);
    const storage = new Memory();
    storage.setItem(THREADS_KEY, "{not json");
    expect(loadThreads(storage)).toEqual([]);
  });
});

describe("recordTurn", () => {
  it("starts a thread titled by the question, then adds to it", () => {
    const first = recordTurn([], null, "  말티즈가\n설사를 해요 그리고 아주 긴 질문이 계속 이어집니다 ", { role: "assistant", content: "답", route: "rag" });
    expect(first.threads).toHaveLength(1);
    expect(first.threads[0].title).toBe("말티즈가 설사를 해요 그리고 아주 긴 질문이 계속 이어");
    const second = recordTurn(first.threads, first.id, "또", { role: "assistant", content: "답2" });
    expect(second.id).toBe(first.id);
    expect(second.threads[0].turns.map((t) => t.route)).toEqual(["rag", "none"]);
  });

  it("keeps the newest turns and threads within the limits", () => {
    let state = { threads: [] as Thread[], id: null as string | null };
    for (let i = 0; i < MAX_TURNS_PER_THREAD + 5; i++) state = recordTurn(state.threads, state.id, `q${i}`, { role: "assistant", content: "a" });
    expect(state.threads[0].turns).toHaveLength(MAX_TURNS_PER_THREAD);
    expect(state.threads[0].turns[0].question).toBe("q5");
    const many = Array.from({ length: MAX_THREADS }, (_, i) => thread(i + 1));
    const added = recordTurn(many, null, "새 질문", { role: "assistant", content: "a" });
    expect(added.threads).toHaveLength(MAX_THREADS);
    expect(added.threads[0].id).toBe(added.id);
    expect(added.threads.some((t) => t.id === id(1))).toBe(false);
  });
});

describe("saveThreads", () => {
  it("drops the oldest threads when the browser is out of room", () => {
    const storage = new Memory();
    const threads = [thread(1), thread(2), thread(3)];
    storage.quota = JSON.stringify([thread(3), thread(2)]).length;
    expect(saveThreads(storage, threads)).toBe(true);
    expect(loadThreads(storage).map((t) => t.id)).toEqual([id(3), id(2)]);
    expect(saveThreads(null, threads)).toBe(false);
  });
});

describe("messagesOf", () => {
  it("turns stored turns into chat messages", () => {
    expect(messagesOf(thread(1))).toEqual([
      { role: "user", content: "q1" },
      { role: "assistant", content: "a1", route: "rag" },
    ]);
    expect(messagesOf(undefined)).toEqual([]);
  });
});

describe("notice and clearing", () => {
  it("shows the notice once, and clearing keeps the question-limit id", () => {
    const storage = new Memory();
    expect(takeNotice(storage)).toBe(true);
    expect(takeNotice(storage)).toBe(false);
    storage.setItem(THREADS_KEY, "[]");
    storage.setItem(PROFILE_KEY, "{}");
    storage.setItem("ragdog:v1:client", id(9));
    clearDevice(storage);
    expect([...storage.items.keys()]).toEqual(["ragdog:v1:client"]);
    expect(storage.getItem(NOTICE_KEY)).toBeNull();
  });
});
