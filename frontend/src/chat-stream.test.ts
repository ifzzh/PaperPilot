import { describe, it, expect } from "vitest";
import { readChatStream } from "./chat-stream";
function response(parts: Uint8Array[]) {
  return new Response(
    new ReadableStream({
      start(c) {
        parts.forEach((p) => c.enqueue(p));
        c.close();
      },
    }),
    { headers: { "Content-Type": "text/plain" } },
  );
}
const bytes = (s: string) => new TextEncoder().encode(s);
describe("existing mixed chat wire format", () => {
  it("handles every byte split including UTF-8 and combined header/body without losing newlines", async () => {
    const input = bytes(
      '{"session_id":"abc"}\n你好\n{"text":"body"}\nError: llm_request_failed',
    );
    for (let split = 1; split < input.length; split++) {
      let id = "",
        text = "";
      await readChatStream(
        response([input.slice(0, split), input.slice(split)]),
        new AbortController().signal,
        (v) => (id = v),
        (v) => (text += v),
      );
      expect(id).toBe("abc");
      expect(text).toBe('你好\n{"text":"body"}\nError: llm_request_failed');
    }
  });
  it("rejects missing/invalid/oversized header and non-text responses", async () => {
    for (const value of [
      "Error: llm_request_failed",
      "{}\nbody",
      "null\nbody",
      '{"session_id":1}\n',
      "a".repeat(8193),
    ])
      await expect(
        readChatStream(
          response([bytes(value)]),
          new AbortController().signal,
          () => {},
          () => {},
        ),
      ).rejects.toThrow();
    await expect(
      readChatStream(
        new Response("{}", { headers: { "Content-Type": "application/json" } }),
        new AbortController().signal,
        () => {},
        () => {},
      ),
    ).rejects.toThrow("invalid_stream");
  });
  it("propagates HTTP and read errors, cancels the reader on abort", async () => {
    await expect(
      readChatStream(
        new Response('{"error":"password_change_required"}', { status: 403 }),
        new AbortController().signal,
        () => {},
        () => {},
      ),
    ).rejects.toThrow("password_change_required");
    const c = new AbortController();
    let canceled = false;
    const r = new Response(
      new ReadableStream({
        start(s) {
          s.enqueue(bytes('{"session_id":"a"}\n'));
        },
        cancel() {
          canceled = true;
        },
      }),
      { headers: { "Content-Type": "text/plain" } },
    );
    await expect(
      readChatStream(
        r,
        c.signal,
        () => c.abort(),
        () => {},
      ),
    ).rejects.toThrow();
    expect(canceled).toBe(true);
    const broken = new Response(
      new ReadableStream({
        start(s) {
          s.error(new Error("broken"));
        },
      }),
      { headers: { "Content-Type": "text/plain" } },
    );
    await expect(
      readChatStream(
        broken,
        new AbortController().signal,
        () => {},
        () => {},
      ),
    ).rejects.toThrow("broken");
  });
});
