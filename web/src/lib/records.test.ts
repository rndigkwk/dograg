import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { AccountRecords, DeviceRecords, mergeThreads, moveDeviceToAccount } from "./records";
import { type KeyValue, NOTICE_KEY, PROFILE_KEY, type Thread, THREADS_KEY } from "./store";

const id = (n: number) => n.toString(16).padStart(32, "0");
const thread = (n: number, day = n): Thread => ({
  id: id(n),
  title: `대화 ${n}`,
  created_at: `2020-01-${String(day).padStart(2, "0")}T00:00:00Z`,
  updated_at: `2020-01-${String(day).padStart(2, "0")}T00:00:00Z`,
  turns: [{ question: `q${n}`, answer: `a${n}`, route: "rag", evidence_ids: [], at: "2020-01-01T00:00:00Z" }],
});

class Memory implements KeyValue {
  items = new Map<string, string>();
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
}

/** The few PostgREST calls AccountRecords makes, on in-memory tables (one signed-in user). */
function fakeSupabase() {
  const tables: Record<string, Record<string, unknown>[]> = { ragdog_user_threads: [], ragdog_user_profile: [] };
  const calls: string[] = [];
  const query = (table: string) => {
    let rows = () => tables[table];
    let action: "select" | "delete" = "select";
    const builder = {
      select: () => builder,
      order: (column: string, { ascending }: { ascending: boolean }) => {
        const before = rows;
        rows = () => [...before()].sort((a, b) => (String(a[column]) < String(b[column]) ? -1 : 1) * (ascending ? 1 : -1));
        return builder;
      },
      limit: (n: number) => {
        const before = rows;
        rows = () => before().slice(0, n);
        return builder;
      },
      delete: () => {
        action = "delete";
        return builder;
      },
      in: (column: string, values: string[]) => {
        const before = rows;
        rows = () => before().filter((row) => values.includes(String(row[column])));
        return builder;
      },
      not: () => builder,
      maybeSingle: async () => ({ data: tables[table][0] ?? null, error: null }),
      upsert: async (row: Record<string, unknown>, { onConflict }: { onConflict: string }) => {
        calls.push(`upsert ${table}`);
        const key = onConflict.split(",").pop()!;
        tables[table] = [...tables[table].filter((r) => r[key] !== row[key]), row];
        return { error: null };
      },
      then: (resolve: (value: { data: unknown; error: null }) => void) => {
        if (action === "delete") {
          const gone = new Set(rows());
          calls.push(`delete ${table} ${gone.size}`);
          tables[table] = tables[table].filter((row) => !gone.has(row));
          resolve({ data: null, error: null });
        } else resolve({ data: rows(), error: null });
      },
    };
    return builder;
  };
  return { client: { from: query } as unknown as SupabaseClient, tables, calls };
}

describe("mergeThreads", () => {
  it("keeps the newest 20 and names the account's threads that fall out", () => {
    const account = Array.from({ length: 15 }, (_, i) => thread(i + 1));
    const device = Array.from({ length: 10 }, (_, i) => thread(i + 101, i + 16));
    const { kept, dropped } = mergeThreads(account, device);
    expect(kept).toHaveLength(20);
    expect(kept[0].id).toBe(id(110));
    expect(dropped).toEqual([1, 2, 3, 4, 5].map(id));
  });
});

describe("AccountRecords", () => {
  it("writes one thread, deletes before adding, and clears only its rows", async () => {
    const fake = fakeSupabase();
    const account = new AccountRecords(fake.client);
    await account.save([], thread(1), []);
    await account.save([], thread(2), [id(1)]);
    expect((await account.threads()).map((t) => t.id)).toEqual([id(2)]);
    expect(fake.calls).toEqual(["upsert ragdog_user_threads", "delete ragdog_user_threads 1", "upsert ragdog_user_threads"]);
    await account.saveProfile({ name: "두부", weight_kg: 999 });
    expect(await account.profile()).toEqual({ name: "두부" }); // checked like the device copy
    await account.clear();
    expect(fake.tables).toEqual({ ragdog_user_threads: [], ragdog_user_profile: [] });
  });
});

describe("moveDeviceToAccount", () => {
  it("adds the device's records to the account, then removes them from the device only", async () => {
    const fake = fakeSupabase();
    const account = new AccountRecords(fake.client);
    await account.save([], thread(1), []);
    const storage = new Memory();
    storage.setItem(THREADS_KEY, JSON.stringify([thread(2), thread(3)]));
    storage.setItem(PROFILE_KEY, JSON.stringify({ name: "두부" }));
    storage.setItem(NOTICE_KEY, "1");
    const kept = await moveDeviceToAccount(new DeviceRecords(storage), account);
    expect(kept.map((t) => t.id)).toEqual([id(3), id(2), id(1)]);
    expect((await account.threads()).length).toBe(3);
    expect(await account.profile()).toEqual({ name: "두부" }); // an empty account takes the device's profile
    expect(storage.getItem(THREADS_KEY)).toBeNull();
    expect(storage.getItem(PROFILE_KEY)).toBeNull();
    expect(storage.getItem(NOTICE_KEY)).toBe("1");
  });

  it("keeps the account's own profile", async () => {
    const fake = fakeSupabase();
    const account = new AccountRecords(fake.client);
    await account.saveProfile({ name: "보리" });
    const storage = new Memory();
    storage.setItem(PROFILE_KEY, JSON.stringify({ name: "두부" }));
    await moveDeviceToAccount(new DeviceRecords(storage), account);
    expect(await account.profile()).toEqual({ name: "보리" });
  });
});
