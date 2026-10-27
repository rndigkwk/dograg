import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { plainTildes } from "@/lib/chat";

/** A citation link (linkCitations): opens its evidence card in the same answer instead of navigating. */
function CitationLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="text-accent underline"
      onClick={(event) => {
        event.preventDefault(); // not a page anchor: the same number is on every answer's cards
        const card = event.currentTarget.closest("[data-answer]")?.querySelector<HTMLDetailsElement>(`[data-cite="${href.slice("#cite-".length)}"]`);
        if (!card) return;
        card.open = true;
        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
        card.querySelector("summary")?.focus();
      }}
    >
      {children}
    </a>
  );
}

const components: Components = {
  a: ({ href, children }) =>
    href?.startsWith("#cite-") ? <CitationLink href={href}>{children}</CitationLink> : <a href={href}>{children}</a>,
};

/** Model text as Markdown; "~" stays a range ("5~10알"), not strikethrough. */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[[remarkGfm, { singleTilde: false }]]} components={components}>{plainTildes(text)}</ReactMarkdown>
    </div>
  );
}
