import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { plainTildes } from "@/lib/chat";

/** Model text as Markdown; "~" stays a range ("5~10알"), not strikethrough. */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[[remarkGfm, { singleTilde: false }]]}>{plainTildes(text)}</ReactMarkdown>
    </div>
  );
}
