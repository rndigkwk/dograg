// Where a guardian's conversations and dog profile live (ADR-0008 P4):
//   signed out -> this browser (localStorage, lib/store.ts), as before;
//   signed in  -> their account (Supabase tables ragdog_user_threads / ragdog_user_profile, row level
//                 security: their own rows only, scripts/sql/user_records.sql). Nothing new is written
//                 to the browser while signed in, so a shared computer keeps no copy after sign-out.

import type { SupabaseClient } from "@supabase/supabase-js";

import { cleanProfile, isEmpty, loadProfile, type PetProfile, saveProfile } from "./profile";
import { clearDevice, type KeyValue, loadThreads, MAX_THREADS, PROFILE_KEY, saveThreads, type Thread, THREADS_KEY } from "./store";

export interface Records {
  readonly where: "device" | "account";
  threads(): Promise<Thread[]>;
  /** Writes the list after a change: `changed` was added or updated, `removed` were dropped or deleted. */
  save(threads: Thread[], changed: Thread | null, removed: string[]): Promise<void>;
  profile(): Promise<PetProfile | null>;
  saveProfile(profile: PetProfile | null): Promise<void>;
  clear(): Promise<void>;
}

export class DeviceRecords implements Records {
  readonly where = "device";
  constructor(private storage: KeyValue | null) {}
  async threads() {
    return loadThreads(this.storage);
  }
  async save(threads: Thread[]) {
    saveThreads(this.storage, threads);
  }
  async profile() {
    return loadProfile(this.storage);
  }
  async saveProfile(profile: PetProfile | null) {
    saveProfile(this.storage, profile);
  }
  async clear() {
    clearDevice(this.storage);
  }
  /** After moving them to the account: the conversations and profile, not the notice flag. */
  async clearRecords() {
    for (const key of [THREADS_KEY, PROFILE_KEY]) this.storage?.removeItem(key);
  }
}

type ThreadRow = { thread_id: string; title: string; turns: Thread["turns"]; created_at: string; updated_at: string };

const toThread = (row: ThreadRow): Thread => ({ id: row.thread_id, title: row.title, turns: row.turns ?? [], created_at: row.created_at, updated_at: row.updated_at });
const toRow = (thread: Thread): ThreadRow => ({ thread_id: thread.id, title: thread.title, turns: thread.turns, created_at: thread.created_at, updated_at: thread.updated_at });

export class AccountRecords implements Records {
  readonly where = "account";
  constructor(private client: SupabaseClient) {}

  async threads() {
    const { data, error } = await this.client.from("ragdog_user_threads").select("thread_id,title,turns,created_at,updated_at").order("updated_at", { ascending: false }).limit(MAX_THREADS);
    if (error) throw error;
    return (data as ThreadRow[]).map(toThread);
  }

  async save(_threads: Thread[], changed: Thread | null, removed: string[]) {
    // Deletes first: the table holds 20 conversations at most (a trigger refuses the 21st).
    if (removed.length) {
      const { error } = await this.client.from("ragdog_user_threads").delete().in("thread_id", removed);
      if (error) throw error;
    }
    if (changed) {
      // user_id is filled by the database (default auth.uid()) and checked by row level security.
      const { error } = await this.client.from("ragdog_user_threads").upsert(toRow(changed), { onConflict: "user_id,thread_id" });
      if (error) throw error;
    }
  }

  async profile() {
    const { data, error } = await this.client.from("ragdog_user_profile").select("profile").maybeSingle();
    if (error) throw error;
    const profile = cleanProfile(data?.profile);
    return isEmpty(profile) ? null : profile;
  }

  async saveProfile(profile: PetProfile | null) {
    const clean = cleanProfile(profile);
    const request = isEmpty(clean)
      ? this.client.from("ragdog_user_profile").delete().not("user_id", "is", null)
      : this.client.from("ragdog_user_profile").upsert({ profile: clean, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    const { error } = await request;
    if (error) throw error;
  }

  /** "계정의 기록 모두 지우기": every row of this account (row level security limits it to theirs). */
  async clear() {
    for (const table of ["ragdog_user_threads", "ragdog_user_profile"]) {
      const { error } = await this.client.from(table).delete().not("user_id", "is", null);
      if (error) throw error;
    }
  }
}

/** The account's list after moving this device's conversations into it: newest MAX_THREADS kept. */
export function mergeThreads(account: Thread[], device: Thread[]): { kept: Thread[]; dropped: string[] } {
  const byId = new Map(account.map((t) => [t.id, t]));
  for (const t of device) {
    const mine = byId.get(t.id);
    if (!mine || mine.updated_at < t.updated_at) byId.set(t.id, t);
  }
  const all = [...byId.values()].sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
  const kept = all.slice(0, MAX_THREADS);
  const keptIds = new Set(kept.map((t) => t.id));
  return { kept, dropped: account.filter((t) => !keptIds.has(t.id)).map((t) => t.id) };
}

/** Moves this device's records into the account, then removes them from the device (only after success). */
export async function moveDeviceToAccount(device: DeviceRecords, account: AccountRecords): Promise<Thread[]> {
  const [accountThreads, deviceThreads, accountProfile, deviceProfile] = await Promise.all([
    account.threads(),
    device.threads(),
    account.profile(),
    device.profile(),
  ]);
  const { kept, dropped } = mergeThreads(accountThreads, deviceThreads);
  const keptIds = new Set(kept.map((t) => t.id));
  await account.save(kept, null, dropped);
  for (const thread of deviceThreads) if (keptIds.has(thread.id)) await account.save(kept, thread, []);
  // The account's profile wins when it has one; the device's fills an empty account.
  if (!accountProfile && deviceProfile) await account.saveProfile(deviceProfile);
  await device.clearRecords();
  return kept;
}
