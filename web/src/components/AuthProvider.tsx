"use client";

import type { Session } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useState } from "react";

import { supabase } from "@/lib/supabase";

type Auth = { session: Session | null; ready: boolean };

const AuthContext = createContext<Auth>({ session: null, ready: false });

/** The signed-in session for every page; null when signed out. */
export function useAuth(): Auth {
  return useContext(AuthContext);
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<Auth>({ session: null, ready: false });

  useEffect(() => {
    const client = supabase();
    client.auth.getSession().then(({ data }) => setAuth({ session: data.session, ready: true }));
    const { data } = client.auth.onAuthStateChange((_event, session) => setAuth({ session, ready: true }));
    return () => data.subscription.unsubscribe();
  }, []);

  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}
