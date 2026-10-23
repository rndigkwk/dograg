"use client";

import { lazy, Suspense } from "react";

// react-markdown and remark-gfm were in the first load of the chat, report and visit pages, where
// they render only once an answer arrives. They now come in their own chunk; until it is there the
// text shows as it is (2026-10-23, docs/wiki/web-frontend.md).
const MarkdownBody = lazy(() => import("./MarkdownBody"));

/** Model text as Markdown; "~" stays a range ("5~10알"), not strikethrough. */
export default function Markdown({ text }: { text: string }) {
  return (
    <Suspense fallback={<div className="markdown whitespace-pre-wrap">{text}</div>}>
      <MarkdownBody text={text} />
    </Suspense>
  );
}
