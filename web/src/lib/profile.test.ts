import { describe, expect, it } from "vitest";

import { cleanProfile, describeAge, isEmpty, loadProfile, profileSummary, saveProfile, splitItems } from "./profile";
import { type KeyValue, PROFILE_KEY } from "./store";

const today = new Date("2026-10-16T00:00:00Z");

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

describe("cleanProfile", () => {
  it("keeps valid fields and drops what PetProfile would refuse", () => {
    expect(
      cleanProfile(
        {
          name: "  두부\n",
          breed: "말티즈".repeat(20),
          birth_month: "2023-04-17",
          weight_kg: 400,
          neutered: "yes",
          conditions: ["슬개골 탈구", "슬개골 탈구", " ", 3],
          medications: "약",
          extra: "x",
        },
        today,
      ),
    ).toEqual({ name: "두부", breed: "말티즈".repeat(10), birth_month: "2023-04-01", conditions: ["슬개골 탈구"] });
    expect(cleanProfile({ birth_month: "2027-01" }, today)).toEqual({});
    expect(isEmpty({ name: " " })).toBe(true);
  });

  it("splits comma or line separated items", () => {
    expect(splitItems("심장약, 관절 영양제\n 유산균 ,")).toEqual(["심장약", "관절 영양제", "유산균"]);
  });
});

describe("storage", () => {
  it("saves without empty fields and clears an empty profile", () => {
    const storage = new Memory();
    saveProfile(storage, { name: "두부", conditions: [], neutered: true });
    expect(storage.getItem(PROFILE_KEY)).toBe('{"name":"두부","neutered":true}');
    expect(loadProfile(storage)).toEqual({ name: "두부", neutered: true });
    saveProfile(storage, {});
    expect(storage.getItem(PROFILE_KEY)).toBeNull();
    storage.setItem(PROFILE_KEY, "{broken");
    expect(loadProfile(storage)).toBeNull();
  });
});

describe("profileSummary", () => {
  it("reads like the Streamlit sidebar", () => {
    expect(describeAge("2026-05-01", today)).toBe("5개월 (자견)");
    expect(describeAge("2023-04-01", today)).toBe("약 3살 (성견)");
    expect(describeAge("2016-01-01", today)).toBe("약 10살 (노령견)");
    expect(profileSummary({ name: "두부", birth_month: "2023-04-01", weight_kg: 3.5, neutered: false, medications: ["심장약"] }, today)).toBe(
      "이름: 두부 · 나이: 약 3살 (성견) · 체중: 3.5kg · 중성화: 안 함 · 복용약: 심장약",
    );
  });
});
