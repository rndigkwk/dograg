// The care schedule as a calendar file (.ics, RFC 5545), made in the browser (2026-10-27): each item
// with a next date becomes one all-day event with a reminder the evening before. Only the next date:
// when the item is done and its date changed here, the guardian downloads the file again, and the
// event's fixed UID lets a calendar replace the old one instead of adding a second.

import { CARE_ITEMS, type CareRecord, formatDate, scheduleFor, SOURCE } from "./careSchedule";

export const CALENDAR_FILE = "ragdog-care.ics";

/** RFC 5545 TEXT: backslash, semicolon, comma and newline escaped. */
const escapeText = (text: string) => text.replace(/[\\;,]/g, (c) => `\\${c}`).replace(/\r?\n/g, "\\n");

/** Lines longer than 75 octets folded with CRLF and a space, never inside a UTF-8 character. */
function fold(line: string): string {
  const encoder = new TextEncoder();
  const parts: string[] = [];
  let current = "";
  let size = 0;
  for (const char of line) {
    const bytes = encoder.encode(char).length;
    // The first line holds 75 octets; a continuation line's leading space takes one of its 75.
    if (size + bytes > (parts.length ? 74 : 75)) {
      parts.push(current);
      current = "";
      size = 0;
    }
    current += char;
    size += bytes;
  }
  parts.push(current);
  return parts.join("\r\n ");
}

const compact = (date: string) => date.replaceAll("-", "");

function nextDay(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return formatDate(new Date(Date.UTC(year, month - 1, day + 1)));
}

/** The events, one per item with a next date. A date already past goes on today (marked 지남 once the
 * guide's latest date has passed too), so the calendar still shows it. Null when there is nothing. */
export function careCalendar(record: CareRecord, planned: CareRecord, now = new Date()): { text: string; count: number } | null {
  const today = formatDate(new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())));
  const stamp = `${now.toISOString().replace(/[-:]/g, "").slice(0, 15)}Z`;
  const events: string[][] = [];
  for (const item of CARE_ITEMS) {
    const due = scheduleFor(item, record[item.id], planned[item.id], now);
    if (!due) continue;
    const late = due.status === "overdue";
    const date = due.from < today ? today : due.from;
    const basis = due.planned
      ? "수의사와 정한 날입니다."
      : `${SOURCE.organization} 지침(${item.wording})으로 계산한 날입니다${due.from === due.to ? "" : `: ${due.from} ~ ${due.to}`}. 실제 일정은 수의사와 정하세요.`;
    const last = record[item.id] ? ` 마지막으로 한 날: ${record[item.id]}.` : "";
    events.push([
      "BEGIN:VEVENT",
      `UID:care-${item.id}@ragdog`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${compact(date)}`,
      `DTEND;VALUE=DATE:${compact(nextDay(date))}`,
      `SUMMARY:${escapeText(`${item.label}${late ? " (지남)" : ""}`)}`,
      `DESCRIPTION:${escapeText(`${basis}${last} 라그도그 관리 일정에서 내보냄.`)}`,
      "TRANSP:TRANSPARENT",
      "BEGIN:VALARM",
      "ACTION:DISPLAY",
      `DESCRIPTION:${escapeText(item.label)}`,
      "TRIGGER:-PT3H", // 21:00 the evening before
      "END:VALARM",
      "END:VEVENT",
    ]);
  }
  if (!events.length) return null;
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RagDog//Care schedule//KO", "CALSCALE:GREGORIAN", "X-WR-CALNAME:반려견 관리 일정", ...events.flat(), "END:VCALENDAR"];
  return { text: `${lines.map(fold).join("\r\n")}\r\n`, count: events.length };
}
