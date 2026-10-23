"use client";

import { useState } from "react";

import { cleanProfile, type PetProfile, profileSummary, splitItems } from "@/lib/profile";
import Icon from "./Icon";

const NEUTERED = [
  ["모름", null],
  ["함", true],
  ["안 함", false],
] as const;

/** "우리 아이 정보": the dog's profile, kept in this browser (src/conversation_ui.py render_profile_sidebar). */
export default function ProfileForm({ profile, onSave }: { profile: PetProfile | null; onSave: (profile: PetProfile | null) => void }) {
  const current = profile ?? {};
  const [error, setError] = useState(false);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? "");
    const weight = Number(field("weight_kg"));
    const neutered = NEUTERED.find(([label]) => label === field("neutered"))?.[1] ?? null;
    const draft: PetProfile = {
      name: field("name"),
      breed: field("breed"),
      birth_month: field("birth_month") ? `${field("birth_month")}-01` : null,
      weight_kg: weight > 0 ? weight : null,
      neutered,
      conditions: splitItems(field("conditions")),
      medications: splitItems(field("medications")),
      allergies: splitItems(field("allergies")),
      procedures: splitItems(field("procedures")),
    };
    const clean = cleanProfile(draft);
    // A typed birth month or weight that the profile refuses (future month, 150kg) is an input error.
    if ((draft.birth_month && !clean.birth_month) || (field("weight_kg") && weight !== 0 && !clean.weight_kg)) {
      setError(true);
      return;
    }
    setError(false);
    onSave(clean);
  }

  const input = "w-full rounded-lg border border-line bg-white px-2 py-1";
  return (
    <details className="rounded-lg border border-line bg-white p-3 text-sm">
      <summary className="cursor-pointer font-bold"><Icon name="heart" size={16} className="mr-1 inline-block align-[-3px]" />우리 아이 정보</summary>
      <p className="mt-2 text-muted">{profile ? profileSummary(profile) : "입력하면 질문에 나이가 없어도 나이에 맞는 상담 자료를 먼저 찾습니다."}</p>
      {/* Keyed by the stored profile: a saved suggestion refills the form. */}
      <form key={JSON.stringify(current)} onSubmit={submit} className="mt-3 space-y-2">
        <label className="block">이름<input name="name" defaultValue={current.name ?? ""} maxLength={30} className={input} /></label>
        <label className="block">견종<input name="breed" defaultValue={current.breed ?? ""} maxLength={30} className={input} /></label>
        <label className="block">
          태어난 달 (대략)
          <input name="birth_month" type="month" min="1990-01" defaultValue={current.birth_month?.slice(0, 7) ?? ""} className={input} />
        </label>
        <label className="block">
          체중 (kg)
          <input name="weight_kg" type="number" min="0" max="149.9" step="0.1" defaultValue={current.weight_kg ?? ""} className={input} />
        </label>
        <fieldset>
          <legend>중성화</legend>
          <div className="flex gap-3">
            {NEUTERED.map(([label, value]) => (
              <label key={label} className="flex items-center gap-1">
                <input type="radio" name="neutered" value={label} defaultChecked={(current.neutered ?? null) === value} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="block">지병 (쉼표로 구분)<input name="conditions" defaultValue={current.conditions?.join(", ") ?? ""} className={input} /></label>
        <label className="block">복용약 (쉼표로 구분)<input name="medications" defaultValue={current.medications?.join(", ") ?? ""} className={input} /></label>
        <label className="block">알레르기 (쉼표로 구분)<input name="allergies" defaultValue={current.allergies?.join(", ") ?? ""} className={input} /></label>
        <label className="block">
          수술·시술 이력 (쉼표로 구분)
          <input name="procedures" defaultValue={current.procedures?.join(", ") ?? ""} className={input} />
        </label>
        {error ? <p className="text-danger">입력값을 확인해 주세요.</p> : null}
        <div className="flex gap-2">
          <button type="submit" className="rounded-lg bg-accent px-3 py-1 font-semibold text-white">저장</button>
          {profile ? (
            <button type="button" onClick={() => onSave(null)} className="rounded-lg border border-line px-3 py-1">
              정보 지우기
            </button>
          ) : null}
        </div>
      </form>
    </details>
  );
}
