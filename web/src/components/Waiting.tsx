"use client";

import { useEffect, useState } from "react";

import { waitedText, waitingHint } from "@/lib/failure";
import Icon from "./Icon";

/** A waiting line with the seconds so far, a hint when the server is waking or slow, and a stop
 * button when the wait can be cancelled. `started`: the API has answered something already. */
export default function Waiting({ text, started = false, onStop }: { text: string; started?: boolean; onStop?: () => void }) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const begun = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - begun) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const hint = waitingHint(seconds, started);
  return (
    <div role="status" className="text-muted">
      <p>
        <Icon name="clock" size={16} className="mr-1 inline-block align-[-3px]" />{text}
        {seconds >= 3 ? <span className="ml-1 text-sm tabular-nums">({waitedText(seconds)})</span> : null}
      </p>
      {hint ? <p className="mt-1 text-sm">{hint}</p> : null}
      {onStop && seconds >= 3 ? (
        <button type="button" onClick={onStop} className="mt-2 rounded-lg border border-line bg-white px-3 py-1 text-sm text-ink">
          멈추기
        </button>
      ) : null}
    </div>
  );
}

/** A failed load with a button that tries again. */
export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-lg bg-warn/10 p-3">
      <p>{message}</p>
      <button type="button" onClick={onRetry} className="mt-2 rounded-lg border border-line bg-white px-3 py-1 text-sm">
        다시 시도
      </button>
    </div>
  );
}
