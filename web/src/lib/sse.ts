// Server-Sent Events read from a fetch response (the API's /chat is a POST, which EventSource
// cannot send). The API writes "event: <kind>\ndata: <json>\n\n" (api/chat.py event()).

export type StreamEvent = { kind: string; data: unknown };

/** The complete events in `buffer`, and what is left for the next chunk. */
export function takeEvents(buffer: string): { events: StreamEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const block of blocks) {
    let kind = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) kind = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length) events.push({ kind, data: JSON.parse(data.join("\n")) });
  }
  return { events, rest };
}

/** Each event of a streamed response, in order, as it arrives. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder(); // stream: true keeps a character split across chunks for the next one
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, rest } = takeEvents(buffer + decoder.decode(value, { stream: true }));
    buffer = rest;
    yield* events;
  }
  yield* takeEvents(buffer + "\n\n").events;
}
