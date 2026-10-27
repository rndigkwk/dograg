"use client";

import { useEffect, useState } from "react";

import { CALENDAR_FILE, careCalendar } from "@/lib/careCalendar";
import { CARE_ITEMS, CARE_PLANNED_KEY, type CareRecord, type Due, loadPlanned, loadRecord, saveRecord, scheduleFor, SOURCE } from "@/lib/careSchedule";
import { browserStorage } from "@/lib/store";

import Icon from "./Icon";

const BADGE: Record<Due["status"], { text: (due: Due) => string; className: string }> = {
  overdue: { text: () => "지났어요", className: "bg-danger/15 text-danger" },
  due: { text: () => "지금 할 때", className: "bg-warn/15 text-warn-strong" },
  soon: { text: (due) => `${due.days}일 남음`, className: "bg-accent/10 text-accent" },
  later: { text: (due) => `${due.days}일 남음`, className: "bg-line/60 text-muted" },
};

const dueText = (due: Due) => (due.from === due.to ? due.from : `${due.from} ~ ${due.to}`);

/** The schedule as an .ics file, saved through a temporary link (lib/careCalendar.ts). */
function CalendarButton({ record, planned }: { record: CareRecord; planned: CareRecord }) {
  const [saved, setSaved] = useState<number | null>(null);
  const file = careCalendar(record, planned);
  return (
    <div className="rounded-lg border border-line p-3 text-sm">
      <button
        type="button"
        disabled={!file}
        onClick={() => {
          if (!file) return;
          const url = URL.createObjectURL(new Blob([file.text], { type: "text/calendar;charset=utf-8" }));
          const link = document.createElement("a");
          link.href = url;
          link.download = CALENDAR_FILE;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
          setSaved(file.count);
        }}
        className="rounded-lg border border-accent px-3 py-1 font-semibold text-accent disabled:border-line disabled:text-muted"
      >
        <Icon name="calendar" size={16} className="mr-1 inline-block align-[-3px]" />캘린더 파일(.ics)로 받기
      </button>
      <p className="mt-1 text-xs text-muted" aria-live="polite">
        {saved !== null
          ? `${saved}개 일정을 담았습니다. 휴대폰이나 구글 캘린더에서 파일을 열면 추가됩니다.`
          : file
            ? "날짜가 있는 항목마다 다음 날짜 하나가 종일 일정으로 들어가고, 전날 저녁에 알림이 옵니다. 날짜를 고친 뒤 다시 받으면 같은 일정이 바뀝니다."
            : "마지막으로 한 날이나 수의사와 정한 날을 입력하면 캘린더로 받을 수 있습니다."}
      </p>
    </div>
  );
}

/** Routine care: when each item was last done, and when the guide says it is next due. */
export default function CareSchedule() {
  const [record, setRecord] = useState<CareRecord | null>(null);
  const [planned, setPlanned] = useState<CareRecord>({});
  const today = new Date();
  const max = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  useEffect(() => {
    setRecord(loadRecord(browserStorage()));
    setPlanned(loadPlanned(browserStorage()));
  }, []);

  const change = (current: CareRecord, id: string, value: string) => {
    const next = { ...current };
    if (value) next[id] = value;
    else delete next[id];
    return next;
  };
  function update(id: string, value: string) {
    const next = change(record ?? {}, id, value);
    setRecord(next);
    saveRecord(browserStorage(), next);
  }
  function plan(id: string, value: string) {
    const next = change(planned, id, value);
    setPlanned(next);
    saveRecord(browserStorage(), next, CARE_PLANNED_KEY);
  }

  return (
    <section aria-label="관리 일정" className="space-y-3">
      <CalendarButton record={record ?? {}} planned={planned} />
      <ul className="space-y-2">
        {CARE_ITEMS.map((item) => {
          const last = record?.[item.id] ?? "";
          const set = planned[item.id] ?? "";
          const due = scheduleFor(item, last || undefined, set || undefined, today);
          const badge = due ? BADGE[due.status] : null;
          return (
            <li key={item.id} className="rounded-lg border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold">{item.label}</p>
                {due && badge ? (
                  <span className={`rounded px-2 py-0.5 text-xs font-semibold ${badge.className}`}>{badge.text(due)}</span>
                ) : null}
              </div>
              <p className="text-xs text-muted">
                지침: {item.wording} ({item.page}쪽)
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                <label className="flex items-center gap-2">
                  마지막으로 한 날
                  <input type="date" value={last} max={max} onChange={(event) => update(item.id, event.target.value)}
                    aria-label={`${item.label} 마지막으로 한 날`} className="rounded border border-line px-2 py-1" />
                </label>
                <label className="flex items-center gap-2">
                  수의사와 정한 다음 날
                  <input type="date" value={set} min={last || undefined} onChange={(event) => plan(item.id, event.target.value)}
                    aria-label={`${item.label} 수의사와 정한 다음 날`} className="rounded border border-line px-2 py-1" />
                </label>
              </div>
              {due ? (
                <p className="mt-1 text-sm">
                  다음: <strong>{dueText(due)}</strong> <span className="text-xs text-muted">({due.planned ? "수의사와 정한 날" : "지침으로 계산한 날"})</span>
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted">
        주기는 {SOURCE.organization}의 「{SOURCE.title}」에 나온 일반적인 기준입니다.{" "}
        <a href={SOURCE.url} target="_blank" rel="noopener noreferrer" className="underline">원문 보기</a>
        {" "}· 반려견의 나이·건강 상태·약 종류에 따라 다르니 실제 일정은 수의사와 정하세요. 수의사와 정한 날을 넣으면 그 날짜를 따르고, 그 뒤에 마지막으로 한 날을 고치면 다시 지침으로 계산합니다. 입력한 날짜는 이 브라우저에만 저장됩니다.
      </p>
    </section>
  );
}
