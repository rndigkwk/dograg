"use client";

import { useEffect, useState } from "react";

import { CARE_ITEMS, type CareRecord, type Due, loadRecord, nextDue, saveRecord, SOURCE } from "@/lib/careSchedule";
import { browserStorage } from "@/lib/store";

const BADGE: Record<Due["status"], { text: (due: Due) => string; className: string }> = {
  overdue: { text: () => "지났어요", className: "bg-danger/15 text-danger" },
  due: { text: () => "지금 할 때", className: "bg-warn/15 text-warn-strong" },
  soon: { text: (due) => `${due.days}일 남음`, className: "bg-accent/10 text-accent" },
  later: { text: (due) => `${due.days}일 남음`, className: "bg-line/60 text-muted" },
};

const dueText = (due: Due) => (due.from === due.to ? due.from : `${due.from} ~ ${due.to}`);

/** Routine care: when each item was last done, and when the guide says it is next due. */
export default function CareSchedule() {
  const [record, setRecord] = useState<CareRecord | null>(null);
  const today = new Date();
  const max = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  useEffect(() => setRecord(loadRecord(browserStorage())), []);

  function update(id: string, value: string) {
    const next = { ...(record ?? {}) };
    if (value) next[id] = value;
    else delete next[id];
    setRecord(next);
    saveRecord(browserStorage(), next);
  }

  return (
    <section aria-label="관리 일정" className="space-y-3">
      <ul className="space-y-2">
        {CARE_ITEMS.map((item) => {
          const last = record?.[item.id] ?? "";
          const due = last ? nextDue(item, last, today) : null;
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
                {due ? <span>다음: <strong>{dueText(due)}</strong></span> : null}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted">
        주기는 {SOURCE.organization}의 「{SOURCE.title}」에 나온 일반적인 기준입니다.{" "}
        <a href={SOURCE.url} target="_blank" rel="noopener noreferrer" className="underline">원문 보기</a>
        {" "}· 반려견의 나이·건강 상태·약 종류에 따라 다르니 실제 일정은 수의사와 정하세요. 입력한 날짜는 이 브라우저에만 저장됩니다.
      </p>
    </section>
  );
}
