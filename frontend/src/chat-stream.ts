import { ApiError, csrfHeaders } from "./api";

/** The existing wire format is one JSON header line, followed by plain text. */
export async function readChatStream(
  response: Response,
  signal: AbortSignal,
  onSession: (id: string) => void,
  onText: (text: string) => void,
): Promise<void> {
  if (!response.ok) {
    let code = "chat_failed";
    try {
      const data = await response.json();
      if (typeof data.error === "string") code = data.error;
    } catch {
      /* generic HTTP error */
    }
    throw new ApiError(response.status, code);
  }
  if (
    !response.body ||
    !response.headers.get("content-type")?.startsWith("text/plain")
  )
    throw new ApiError(200, "invalid_stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let header = "",
    hasHeader = false;
  const abort = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", abort, { once: true });
  function consume(text: string) {
    if (hasHeader) {
      if (text) onText(text);
      return;
    }
    header += text;
    const newline = header.indexOf("\n");
    if ((newline < 0 ? header.length : newline) > 8192)
      throw new ApiError(200, "invalid_stream_header");
    if (newline < 0) return;
    let meta;
    try {
      meta = JSON.parse(header.slice(0, newline));
    } catch {
      throw new ApiError(200, "invalid_stream_header");
    }
    if (
      typeof meta?.session_id !== "string" ||
      !meta.session_id.trim() ||
      meta.session_id.length > 256
    )
      throw new ApiError(200, "invalid_stream_header");
    hasHeader = true;
    onSession(meta.session_id);
    const remainder = header.slice(newline + 1);
    header = "";
    if (remainder) onText(remainder);
  }
  try {
    signal.throwIfAborted();
    while (true) {
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      consume(decoder.decode(value, { stream: true }));
    }
    consume(decoder.decode());
    if (!hasHeader) throw new ApiError(200, "invalid_stream_header");
  } finally {
    signal.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export function postChat(body: unknown, signal: AbortSignal) {
  return fetch("/api/paper/chat", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...csrfHeaders(),
      "Content-Type": "application/json",
      Accept: "text/plain",
    },
    body: JSON.stringify(body),
    signal,
  });
}
