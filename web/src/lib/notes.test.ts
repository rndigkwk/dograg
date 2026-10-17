import { describe, expect, it } from "vitest";

import { cleanNote, forChat, isNotesFull, type Note, noteDate, notesEnabled } from "./notes";

const note = (id: string, created_at: string, text = `노트 ${id}`): Note => ({ id, note: text, created_at, thread_id: null });

describe("notes", () => {
  it("are off unless the account turned them on", () => {
    expect(notesEnabled(null)).toBe(false);
    expect(notesEnabled({ user: { user_metadata: {} } } as never)).toBe(false);
    expect(notesEnabled({ user: { user_metadata: { consultation_notes: true } } } as never)).toBe(true);
    expect(notesEnabled({ user: { user_metadata: { consultation_notes: "true" } } } as never)).toBe(false);
  });

  it("send the latest five with a question, dated", () => {
    const notes = ["01", "05", "03", "07", "02", "06", "04"].map((d) => note(d, `2026-10-${d}T03:00:00Z`));
    const sent = forChat(notes);
    expect(sent.map((n) => n.text)).toEqual(["노트 07", "노트 06", "노트 05", "노트 04", "노트 03"]);
    expect(sent[0].date).toMatch(/^2026-10-0[67]$/); // local date of 10-07 03:00 UTC
  });

  it("keep one line of at most 300 characters", () => {
    expect(cleanNote("  설사\n이틀째  ")).toBe("설사 이틀째");
    expect(cleanNote("가".repeat(400))).toHaveLength(300);
  });

  it("know the database's refusal of a 31st note", () => {
    expect(isNotesFull({ code: "23514", message: "too many notes" })).toBe(true);
    expect(isNotesFull({ code: "23514", message: "new row violates check constraint" })).toBe(false);
    expect(isNotesFull(new Error("network"))).toBe(false);
  });

  it("dates as YYYY-MM-DD", () => {
    expect(noteDate("2026-10-17T12:00:00Z")).toMatch(/^2026-10-1[78]$/);
  });
});
