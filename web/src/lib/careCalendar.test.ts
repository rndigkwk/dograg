import { describe, expect, it } from "vitest";

import { careCalendar } from "./careCalendar";

const now = new Date("2026-10-27T09:00:00");
const unfold = (text: string) => text.replace(/\r\n /g, "");

describe("careCalendar", () => {
  it("makes one all-day event per item with a date, with a reminder the evening before", () => {
    const file = careCalendar({ heartworm: "2026-10-20", deworming: "2026-09-01" }, { rabies: "2026-12-05" }, now)!;
    expect(file.count).toBe(3);
    const text = unfold(file.text);
    expect(text.startsWith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")).toBe(true);
    expect(text.endsWith("END:VCALENDAR\r\n")).toBe(true);
    expect(text).toContain("UID:care-heartworm@ragdog\r\nDTSTAMP:20261027T");
    expect(text).toContain("DTSTART;VALUE=DATE:20261120\r\nDTEND;VALUE=DATE:20261121\r\nSUMMARY:심장사상충 예방약\r\n");
    // A range from the guide starts on its first day and says the range; a set date says so.
    expect(text).toContain("DTSTART;VALUE=DATE:20261201\r\n");
    expect(text).toContain("3~6개월 간격)으로 계산한 날입니다: 2026-12-01 ~ 2027-03-01");
    expect(text).toContain("SUMMARY:광견병 추가접종\r\nDESCRIPTION:수의사와 정한 날입니다.");
    expect(text).toContain("TRIGGER:-PT3H");
  });

  it("puts a date already past on today, marked 지남 only when overdue", () => {
    const text = unfold(careCalendar({ heartworm: "2026-09-01", deworming: "2026-06-01" }, {}, now)!.text);
    expect(text).toContain("DTSTART;VALUE=DATE:20261027\r\nDTEND;VALUE=DATE:20261028\r\nSUMMARY:심장사상충 예방약 (지남)");
    expect(text).toContain("SUMMARY:내부 기생충 구충제\r\n"); // 09-01 ~ 12-01: due, not late
  });

  it("escapes text, folds long lines at 75 octets without splitting a character, and is null when empty", () => {
    const file = careCalendar({ checkup: "2026-10-01" }, {}, now)!.text;
    const encoder = new TextEncoder();
    for (const line of file.split("\r\n")) expect(encoder.encode(line).length).toBeLessThanOrEqual(75);
    expect(unfold(file)).toContain("DESCRIPTION:동물사랑배움터 지침(1년에 한 번 이상)으로 계산한 날입니다. 실제 일정은 수의사와 정하세요. 마지막으로 한 날: 2026-10-01. 라그도그 관리 일정에서 내보냄.");
    expect(file).not.toContain("�");
    expect(careCalendar({}, {}, now)).toBeNull();
  });
});
