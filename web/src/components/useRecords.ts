"use client";

import { useMemo, useState, useEffect } from "react";

import { AccountRecords, DeviceRecords, type Records } from "@/lib/records";
import { browserStorage, type KeyValue } from "@/lib/store";
import { supabase } from "@/lib/supabase";

import { useAuth } from "./AuthProvider";

/** The records of whoever is using the page: their account when signed in, else this browser.
 * null until the browser storage and the session are known (nothing is read or written before). */
export function useRecords(): { records: Records | null; storage: KeyValue | null } {
  const { session, ready } = useAuth();
  const [storage, setStorage] = useState<KeyValue | null | undefined>(undefined);
  useEffect(() => setStorage(browserStorage()), []);
  const userId = session?.user.id ?? null;
  const records = useMemo<Records | null>(() => {
    if (!ready || storage === undefined) return null;
    return userId ? new AccountRecords(supabase()) : new DeviceRecords(storage);
  }, [ready, storage, userId]);
  return { records, storage: storage ?? null };
}
