// Supabase Auth in the browser (ADR-0008 P4): Google sign-in with the PKCE flow.
//
// The publishable key is public by design: it lets the browser reach Supabase as `anon` or, signed in,
// as `authenticated`, and row level security decides what each may touch (scripts/sql/user_records.sql:
// a user's own rows only; the search and app tables are closed to both). The service_role key never
// comes here.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://ffdahevkdymdaxcexkth.supabase.co";
const PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "sb_publishable_5p-drHOPlhDJDDUQ0G-jbg_yUEdekII";

let client: SupabaseClient | null = null;

/** The one browser client (it holds the session and refreshes its token). */
export function supabase(): SupabaseClient {
  client ??= createClient(SUPABASE_URL, PUBLISHABLE_KEY, {
    auth: {
      flowType: "pkce", // the code from Google is useless without the verifier kept in this browser
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true, // the callback page's ?code= is exchanged on load
    },
  });
  return client;
}

// Where to go after signing in: this site's own paths only, never a full URL (no open redirect).
const RETURN_KEY = "ragdog:v1:auth_return";

export function safeReturnPath(path: string | null | undefined): string {
  if (!path || !path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\") || path.startsWith("/auth/")) return "/";
  return path;
}

export async function signInWithGoogle(): Promise<void> {
  try {
    sessionStorage.setItem(RETURN_KEY, safeReturnPath(window.location.pathname + window.location.search));
  } catch {
    // storage blocked: back to the home page after sign-in
  }
  const { error } = await supabase().auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
  if (error) throw error;
}

/** The path saved before sign-in, once (the callback page reads it). */
export function takeReturnPath(): string {
  try {
    const path = sessionStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    return safeReturnPath(path);
  } catch {
    return "/";
  }
}

export async function signOut(): Promise<void> {
  // scope "local": this browser only; the user's other devices stay signed in.
  await supabase().auth.signOut({ scope: "local" });
}

/** Deletes the signed-in account and, with it, its records (scripts/sql/delete_my_account.sql:
 * the database function can only delete the caller). Then this browser forgets the session. */
export async function deleteAccount(): Promise<void> {
  const { error } = await supabase().rpc("delete_my_account");
  if (error) throw error;
  await supabase().auth.signOut({ scope: "local" }); // the session no longer exists on the server
}
