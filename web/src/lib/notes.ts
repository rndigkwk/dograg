// "지난 상담 기억" (ADR-0009): consultation notes a signed-in guardian chose to keep. They live in the
// account (Supabase table ragdog_user_notes, row level security: own rows only,
// scripts/sql/user_notes.sql); the browser reads and writes them with the user's session. With the
// setting on, the latest five go with each question (api/chat.py ChatRequest.notes). Off by default.

import type { Session, SupabaseClient } from "@supabase/supabase-js";

export type Note = { id: string; note: string; created_at: string; thread_id: string | null };
export type ChatNote = { date: string; text: string };

export const MAX_NOTES = 30;
export const NOTES_PER_QUESTION = 5;
export const NOTE_MAX_CHARS = 300;
const SETTING = "consultation_notes"; // in the account's user_metadata

/** Whether this account turned "지난 상담 기억 사용" on (off unless chosen). */
export function notesEnabled(session: Session | null): boolean {
  return session?.user.user_metadata?.[SETTING] === true;
}

export async function setNotesEnabled(client: SupabaseClient, on: boolean): Promise<void> {
  const { error } = await client.auth.updateUser({ data: { [SETTING]: on } });
  if (error) throw error;
}

export async function listNotes(client: SupabaseClient): Promise<Note[]> {
  const { data, error } = await client.from("ragdog_user_notes").select("note_id,note,created_at,thread_id").order("created_at", { ascending: false }).limit(MAX_NOTES);
  if (error) throw error;
  return (data as { note_id: string; note: string; created_at: string; thread_id: string | null }[]).map((row) => ({
    id: row.note_id,
    note: row.note,
    created_at: row.created_at,
    thread_id: row.thread_id,
  }));
}

/** Saves a note (user_id is filled and checked by the database). Refused past 30: delete one first. */
export async function addNote(client: SupabaseClient, note: string, threadId: string | null): Promise<void> {
  const { error } = await client.from("ragdog_user_notes").insert({ note: cleanNote(note), thread_id: threadId });
  if (error) throw error;
}

export async function removeNote(client: SupabaseClient, id: string): Promise<void> {
  const { error } = await client.from("ragdog_user_notes").delete().eq("note_id", id);
  if (error) throw error;
}

export async function removeAllNotes(client: SupabaseClient): Promise<void> {
  // Row level security limits the delete to this user's rows; the filter only satisfies PostgREST.
  const { error } = await client.from("ragdog_user_notes").delete().not("note_id", "is", null);
  if (error) throw error;
}

export function cleanNote(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, NOTE_MAX_CHARS);
}

/** The local date of a stored note, as the API wants it ("2026-10-17"). */
export function noteDate(createdAt: string): string {
  const day = new Date(createdAt);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** What goes with a question: the latest five, newest first. */
export function forChat(notes: Note[]): ChatNote[] {
  return [...notes]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, NOTES_PER_QUESTION)
    .map((note) => ({ date: noteDate(note.created_at), text: note.note }));
}
