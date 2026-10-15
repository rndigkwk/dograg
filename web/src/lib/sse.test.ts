import { describe, expect, it } from "vitest";

import { readEvents, takeEvents } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("takeEvents", () => {
  it("reads complete events and keeps the unfinished one", () => {
    const { events, rest } = takeEvents('event: step\ndata: {"message":"찾는 중"}\n\nevent: token\ndata: {"te');
    expect(events).toEqual([{ kind: "step", data: { message: "찾는 중" } }]);
    expect(rest).toBe('event: token\ndata: {"te');
  });

  it("accepts CRLF line ends", () => {
    expect(takeEvents('event: token\r\ndata: {"text":"a"}\r\n\r\n').events).toEqual([{ kind: "token", data: { text: "a" } }]);
  });
});

describe("readEvents", () => {
  it("joins events split across chunks, including inside a Korean character", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"설사"}\n\nevent: result\ndata: {"route":"rag"}\n\n');
    const split = [bytes.slice(0, 27), bytes.slice(27, 40), bytes.slice(40)];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        split.forEach((part) => controller.enqueue(part));
        controller.close();
      },
    });
    const got = [];
    for await (const event of readEvents(body)) got.push(event);
    expect(got).toEqual([
      { kind: "token", data: { text: "설사" } },
      { kind: "result", data: { route: "rag" } },
    ]);
  });

  it("reads a last event without the closing blank line", async () => {
    const got = [];
    for await (const event of readEvents(streamOf(['event: error\ndata: {"message":"x"}']))) got.push(event);
    expect(got).toEqual([{ kind: "error", data: { message: "x" } }]);
  });
});
