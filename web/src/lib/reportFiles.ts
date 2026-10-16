// The visit-prep report as files a guardian can open anywhere (2026-10-16): Markdown for those who use
// it, plain text (.txt) and Word (.docx) for everyone else. The report is the team's Markdown
// (team/core/citations.py readable_report): headings, "- " and "1. " lists, **bold**, [links](url).

type Block = { kind: "heading"; level: number; text: string } | { kind: "bullet" | "number"; text: string } | { kind: "paragraph"; text: string } | { kind: "blank" };

export function blocks(markdown: string): Block[] {
  return markdown.replace(/\r\n/g, "\n").split("\n").map((line): Block => {
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) return { kind: "heading", level: heading[1].length, text: heading[2].trim() };
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bullet) return { kind: "bullet", text: bullet[1] };
    const number = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (number) return { kind: "number", text: number[1] };
    return line.trim() ? { kind: "paragraph", text: line.trim() } : { kind: "blank" };
  });
}

/** Inline Markdown as plain words: **bold** and `code` lose their marks, [text](url) keeps the url. */
export function plainInline(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\\([\\`*_{}[\]()#+\-.!~])/g, "$1");
}

export function toPlainText(markdown: string): string {
  let number = 0;
  const lines = blocks(markdown).map((block) => {
    if (block.kind !== "number") number = 0;
    switch (block.kind) {
      case "heading":
        return block.level <= 2 ? `\n[${plainInline(block.text)}]` : `\n${plainInline(block.text)}`;
      case "bullet":
        return `• ${plainInline(block.text)}`;
      case "number":
        number += 1;
        return `${number}. ${plainInline(block.text)}`;
      case "paragraph":
        return plainInline(block.text);
      default:
        return "";
    }
  });
  // Windows Notepad and phones both read UTF-8 with CRLF line ends.
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim().replace(/\n/g, "\r\n") + "\r\n";
}

/** The report as a Word document (headings, lists, bold kept). The library loads only when asked. */
export async function toDocx(markdown: string): Promise<Blob> {
  const { Document, HeadingLevel, Packer, Paragraph, TextRun } = await import("docx");
  const runs = (text: string) =>
    text
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
      .split(/(\*\*[^*]+\*\*)/)
      .filter(Boolean)
      .map((part) => (part.startsWith("**") && part.endsWith("**") ? new TextRun({ text: plainInline(part.slice(2, -2)), bold: true }) : new TextRun(plainInline(part))));
  const levels = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3, HeadingLevel.HEADING_4];
  const children = blocks(markdown)
    .filter((block) => block.kind !== "blank")
    .map((block) => {
      if (block.kind === "heading") return new Paragraph({ heading: levels[Math.min(block.level, 4) - 1], children: runs(block.text) });
      if (block.kind === "bullet") return new Paragraph({ bullet: { level: 0 }, children: runs(block.text) });
      if (block.kind === "number") return new Paragraph({ numbering: { reference: "report-numbers", level: 0 }, children: runs(block.text) });
      return new Paragraph({ children: runs(block.kind === "paragraph" ? block.text : "") });
    });
  const document = new Document({
    creator: "라그도그",
    title: "방문 준비 보고서",
    styles: { default: { document: { run: { font: "Malgun Gothic", size: 22 } } } },
    numbering: { config: [{ reference: "report-numbers", levels: [{ level: 0, format: "decimal", text: "%1.", alignment: "left" }] }] },
    sections: [{ children }],
  });
  return Packer.toBlob(document);
}

export const REPORT_FILE = "방문준비보고서";

export function saveFile(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
