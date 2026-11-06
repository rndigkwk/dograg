// The health answer's "지금 할 일" list (src/tools/health.py rules 15 and 16), cut out so the answer
// shows it as a checklist (2026-11-06 guardian-view mockup). Pure, tested in todo.test.ts.

/** The heading as the model writes it: "지금 할 일", "**지금 할 일**", "### 지금 할 일:" (seen in saved answers). */
const HEADING = /^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*지금 할 일\s*:?\s*(?:\*\*)?\s*:?\s*$/;
const ITEM = /^\s*[-*]\s+(.+)$/;

export type TodoParts = { before: string; items: string[]; after: string };

/** The answer split around its first "지금 할 일" list, or null when it has none (only a heading, or no heading). */
export function splitTodo(text: string): TodoParts | null {
  const lines = text.split("\n");
  const start = lines.findIndex((line) => HEADING.test(line));
  if (start < 0) return null;
  let end = start + 1;
  while (end < lines.length && !lines[end].trim()) end += 1;
  const items: string[] = [];
  for (; end < lines.length; end += 1) {
    const item = ITEM.exec(lines[end]);
    if (!item) break;
    items.push(item[1].trim());
  }
  if (!items.length) return null;
  return { before: lines.slice(0, start).join("\n").trimEnd(), items, after: lines.slice(end).join("\n").trimStart() };
}
