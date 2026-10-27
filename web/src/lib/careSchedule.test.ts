import { describe, expect, it } from "vitest";

import { CARE_ITEMS, CARE_PLANNED_KEY, CARE_SCHEDULE_KEY, cleanPlanned, cleanRecord, dueItems, loadPlanned, loadRecord, nextDue, saveRecord, scheduleFor } from "./careSchedule";

const item = (id: string) => CARE_ITEMS.find((entry) => entry.id === id)!;
const day = (value: string) => new Date(`${value}T09:00:00`);

class MemoryStorage {
  data = new Map<string, string>();
  getItem = (key: string) => this.data.get(key) ?? null;
  setItem = (key: string, value: string) => void this.data.set(key, value);
  removeItem = (key: string) => void this.data.delete(key);
}

describe("nextDue", () => {
  it("adds the guide's interval: monthly heartworm, 3 to 6 months of deworming, 2 to 3 weeks of nails", () => {
    expect(nextDue(item("heartworm"), "2026-09-15", day("2026-10-01"))).toMatchObject({ from: "2026-10-15", to: "2026-10-15" });
    expect(nextDue(item("deworming"), "2026-06-10", day("2026-07-01"))).toMatchObject({ from: "2026-09-10", to: "2026-12-10" });
    expect(nextDue(item("nails"), "2026-10-01", day("2026-10-02"))).toMatchObject({ from: "2026-10-15", to: "2026-10-22" });
  });

  it("keeps a month end a month end", () => {
    expect(nextDue(item("heartworm"), "2026-01-31", day("2026-02-01"))?.from).toBe("2026-02-28");
    expect(nextDue(item("vaccine"), "2024-02-29", day("2024-03-01"))?.from).toBe("2025-02-28");
  });

  it("says overdue only after the latest date, due inside the window, soon within a week before it", () => {
    const deworming = item("deworming"); // 2026-04-01 + 3 to 6 months: 07-01 to 10-01
    expect(nextDue(deworming, "2026-04-01", day("2026-08-15"))?.status).toBe("due");
    expect(nextDue(deworming, "2026-04-01", day("2026-10-01"))?.status).toBe("due");
    expect(nextDue(deworming, "2026-04-01", day("2026-10-02"))?.status).toBe("overdue");
    expect(nextDue(deworming, "2026-04-01", day("2026-06-20"))?.status).toBe("later");
    expect(nextDue(item("heartworm"), "2026-09-20", day("2026-10-15"))).toMatchObject({ status: "soon", days: 5 });
    expect(nextDue(item("heartworm"), "2026-09-01", day("2026-10-01"))).toMatchObject({ status: "due", days: 0 });
    expect(nextDue(item("heartworm"), "2026-09-01", day("2026-10-05"))).toMatchObject({ status: "overdue", days: -4 });
    expect(nextDue(item("vaccine"), "2026-03-01", day("2026-10-19"))?.status).toBe("later");
  });

  it("gives nothing for a date that is not real", () => {
    expect(nextDue(item("nails"), "2026-02-30")).toBeNull();
    expect(nextDue(item("nails"), "어제")).toBeNull();
  });
});

describe("stored record", () => {
  it("keeps known items with real past dates only", () => {
    expect(cleanRecord({ nails: "2026-10-01", rabies: "2026-12-01", unknown: "2026-01-01", vaccine: 3 }, day("2026-10-19")))
      .toEqual({ nails: "2026-10-01" });
    expect(cleanRecord("garbage")).toEqual({});
  });

  it("saves, reads back and clears", () => {
    const storage = new MemoryStorage();
    saveRecord(storage, { heartworm: "2026-10-01" });
    expect(loadRecord(storage, day("2026-10-19"))).toEqual({ heartworm: "2026-10-01" });
    saveRecord(storage, {});
    expect(storage.getItem(CARE_SCHEDULE_KEY)).toBeNull();
    storage.setItem(CARE_SCHEDULE_KEY, "{not json");
    expect(loadRecord(storage)).toEqual({});
  });
});

describe("dueItems", () => {
  it("lists only the items due now or overdue", () => {
    const record = { rabies: "2025-09-01", vaccine: "2026-10-01", deworming: "2026-06-10", nails: "2026-10-15" };
    expect(dueItems(record, day("2026-10-20")).map((item) => item.id)).toEqual(["deworming", "rabies"]);
    expect(dueItems({}, day("2026-10-20"))).toEqual([]);
  });
});

describe("dates set with the vet", () => {
  it("follow the set date instead of the guide's, until the item is done after it", () => {
    const heartworm = item("heartworm");
    // Guide: 2026-10-01 + 1 month = 11-01. The vet said 11-10.
    expect(scheduleFor(heartworm, "2026-10-01", "2026-11-10", day("2026-11-03"))).toMatchObject({ from: "2026-11-10", to: "2026-11-10", status: "soon", planned: true });
    expect(scheduleFor(heartworm, undefined, "2026-11-10", day("2026-11-03"))?.planned).toBe(true);
    // Done on 11-10: the set date is used up, the guide counts from the new last date.
    const after = scheduleFor(heartworm, "2026-11-10", "2026-11-10", day("2026-11-11"));
    expect(after?.from).toBe("2026-12-10");
    expect(after?.planned).toBeUndefined();
    expect(scheduleFor(heartworm, undefined, undefined)).toBeNull();
  });

  it("put a set date into the report's due items", () => {
    expect(dueItems({ vaccine: "2026-03-01" }, day("2026-10-20")).map((i) => i.id)).toEqual([]);
    expect(dueItems({ vaccine: "2026-03-01" }, day("2026-10-20"), { vaccine: "2026-10-15" }).map((i) => i.id)).toEqual(["vaccine"]);
  });

  it("are stored apart, future dates kept, unknown ones dropped", () => {
    const storage = new MemoryStorage();
    saveRecord(storage, { rabies: "2027-01-05" }, CARE_PLANNED_KEY);
    expect(loadPlanned(storage)).toEqual({ rabies: "2027-01-05" });
    expect(storage.getItem(CARE_SCHEDULE_KEY)).toBeNull();
    expect(cleanPlanned({ rabies: "2027-02-30", nope: "2027-01-01", nails: "2026-12-01" })).toEqual({ nails: "2026-12-01" });
  });
});
