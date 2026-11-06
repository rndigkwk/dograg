import { describe, expect, it } from "vitest";

import { splitTodo } from "./todo";

describe("splitTodo", () => {
  it("cuts the list out from under each heading form the model writes", () => {
    for (const heading of ["지금 할 일", "**지금 할 일**", "### 지금 할 일", "지금 할 일:", "**지금 할 일:**"]) {
      const parts = splitTodo(`설사가 이어지면 탈수가 걱정됩니다 [사례 1].\n\n${heading}\n- 물을 조금씩 자주 주세요 [사례 1].\n- 변 상태를 적어 두세요.\n\n피가 섞이면 병원에 가세요.`);
      expect(parts, heading).toEqual({
        before: "설사가 이어지면 탈수가 걱정됩니다 [사례 1].",
        items: ["물을 조금씩 자주 주세요 [사례 1].", "변 상태를 적어 두세요."],
        after: "피가 섞이면 병원에 가세요.",
      });
    }
  });

  it("allows a blank line between the heading and the list", () => {
    expect(splitTodo("지금 할 일\n\n- 쉬게 해 주세요")?.items).toEqual(["쉬게 해 주세요"]);
  });

  it("leaves other lists and headings alone", () => {
    expect(splitTodo("### 집에서 지켜볼 점\n- 식욕")).toBeNull();
    expect(splitTodo("지금 할 일은 물을 주는 것입니다.\n- 물")).toBeNull();
    expect(splitTodo("**지금 할 일**\n바로 병원에 가세요.")).toBeNull();
    expect(splitTodo("구토가 계속되면 병원에 가세요.")).toBeNull();
  });
});
