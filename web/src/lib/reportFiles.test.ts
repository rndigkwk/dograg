import { describe, expect, it } from "vitest";

import { plainInline, toDocx, toPlainText } from "./reportFiles";

const REPORT = [
  "# 방문 준비 보고서",
  "",
  "## 보호자가 말한 증상 정리",
  "- 4살 말티즈가 **어제부터** 설사를 했습니다. ①",
  "- 체중은 3.2kg입니다.",
  "",
  "## 수의사에게 물어볼 질문",
  "1. 어떤 검사가 필요한가요?",
  "2. 예상 비용은 얼마인가요?",
  "",
  "출처: [KB 보고서](https://example.test/kb) p.12, 5\\~10%",
].join("\n");

describe("toPlainText", () => {
  it("drops the Markdown marks and keeps the structure", () => {
    const text = toPlainText(REPORT);
    expect(text).toContain("[방문 준비 보고서]");
    expect(text).toContain("• 4살 말티즈가 어제부터 설사를 했습니다. ①");
    expect(text).toContain("1. 어떤 검사가 필요한가요?\r\n2. 예상 비용은 얼마인가요?");
    expect(text).toContain("출처: KB 보고서 (https://example.test/kb) p.12, 5~10%");
    expect(text).not.toMatch(/\*\*|^#/m);
    expect(text.endsWith("\r\n")).toBe(true);
  });

  it("unescapes and unwraps inline marks", () => {
    expect(plainInline("**굵게** `코드` \\* 별")).toBe("굵게 코드 * 별");
  });
});

describe("toDocx", () => {
  it("makes a Word file (a zip with the document text)", async () => {
    const blob = await toDocx(REPORT);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(String.fromCharCode(bytes[0], bytes[1])).toBe("PK"); // .docx is a zip
    expect(bytes.length).toBeGreaterThan(3000);
  });
});
