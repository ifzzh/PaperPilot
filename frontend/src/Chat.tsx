import { useEffect, useRef, useState } from "react";
import { errorText, isSessionError, request } from "./api";
import { postChat, readChatStream } from "./chat-stream";

type Message = { role: "user" | "assistant"; content: string };
type Session = { id: string; title: string };
function messagesFrom(value: unknown): Message[] {
  if (!Array.isArray(value)) throw new Error("invalid history");
  return value
    .filter(
      (v): v is Message =>
        v &&
        ["user", "assistant"].includes(v.role) &&
        typeof v.content === "string",
    )
    .map((v) => ({ role: v.role, content: v.content }));
}
export function Chat({
  paperId,
  onExpired,
}: {
  paperId: string;
  onExpired: () => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]),
    [id, setId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]),
    [draft, setDraft] = useState("");
  const [pending, setPending] = useState(""),
    [notice, setNotice] = useState("正在加载聊天历史…");
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false);
  const epoch = useRef(0),
    controller = useRef<AbortController | null>(null);
  const stream = useRef<AbortController | null>(null),
    sending = useRef(false);
  function begin() {
    controller.current?.abort();
    stream.current?.abort();
    sending.current = false;
    setBusy(false);
    const c = new AbortController();
    controller.current = c;
    return { c, seq: ++epoch.current };
  }
  function valid(seq: number) {
    return seq === epoch.current;
  }
  function expire() {
    epoch.current++;
    controller.current?.abort();
    stream.current?.abort();
    onExpired();
  }
  function fail(e: unknown) {
    if (isSessionError(e)) expire();
    else setNotice(errorText(e));
  }
  async function list(signal: AbortSignal, seq: number) {
    const data = (await request(
      `/api/paper/chat/sessions?paper_id=${encodeURIComponent(paperId)}`,
      signal,
    )) as { sessions: Session[] };
    if (!Array.isArray(data.sessions)) throw new Error("invalid sessions");
    if (valid(seq))
      setSessions(
        data.sessions
          .filter(
            (s) => typeof s.id === "string" && typeof s.title === "string",
          )
          .map((s) => ({ id: s.id, title: s.title })),
      );
  }
  async function history(sessionId: string, signal: AbortSignal) {
    const data = (await request(
      `/api/paper/chat/session?paper_id=${encodeURIComponent(paperId)}&session_id=${encodeURIComponent(sessionId)}`,
      signal,
    )) as { session: { messages: unknown } };
    return messagesFrom(data.session.messages);
  }
  async function choose(sessionId: string) {
    const { c, seq } = begin();
    setId(sessionId);
    setMessages([]);
    setPending("");
    setDraft("");
    setLoading(true);
    setNotice("");
    try {
      if (sessionId) {
        const result = await history(sessionId, c.signal);
        if (valid(seq)) setMessages(result);
      }
    } catch (e) {
      if (valid(seq) && !c.signal.aborted) fail(e);
    } finally {
      if (valid(seq)) setLoading(false);
    }
  }
  async function refresh() {
    const { c, seq } = begin();
    setLoading(true);
    setNotice("");
    setPending("");
    try {
      await list(c.signal, seq);
      if (id) {
        const result = await history(id, c.signal);
        if (valid(seq)) setMessages(result);
      }
    } catch (e) {
      if (valid(seq) && !c.signal.aborted) fail(e);
    } finally {
      if (valid(seq)) setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    return () => {
      epoch.current++;
      controller.current?.abort();
      stream.current?.abort();
    };
  }, [paperId]);
  async function send() {
    if (sending.current || loading || !draft.trim()) return;
    const { c, seq } = begin();
    sending.current = true;
    setBusy(true);
    setNotice("");
    setPending("");
    const userMessage: Message = { role: "user", content: draft.trim() };
    const original = messages;
    let sessionId = id,
      answer = "",
      stopped = false;
    setDraft("");
    setMessages([...original, userMessage]);
    const sc = new AbortController();
    stream.current = sc;
    try {
      const response = await postChat(
        {
          paper_id: paperId,
          messages: [...original, userMessage],
          ...(id ? { session_id: id } : {}),
        },
        sc.signal,
      );
      await readChatStream(
        response,
        sc.signal,
        (next) => {
          sessionId = next;
          if (valid(seq)) setId(next);
        },
        (text) => {
          answer += text;
          if (valid(seq)) setPending(answer);
        },
      );
    } catch (e) {
      stopped = sc.signal.aborted;
      if (valid(seq) && !stopped) {
        if (isSessionError(e)) {
          expire();
          return;
        }
        setNotice("请求或连接异常；不会自动重发。");
      }
    } finally {
      if (valid(seq)) {
        try {
          await list(c.signal, seq);
          if (sessionId) {
            const saved = await history(sessionId, c.signal);
            if (valid(seq)) {
              const confirmed =
                saved.length >= original.length + 2 &&
                saved[original.length]?.role === "user" &&
                saved[original.length]?.content === userMessage.content &&
                saved[original.length + 1]?.role === "assistant" &&
                saved[original.length + 1]?.content === answer;
              setMessages(saved);
              if (confirmed) {
                setPending("");
                setNotice(
                  stopped
                    ? "已停止接收；历史中已有保存的回答。"
                    : "已读取服务端保存的历史。",
                );
              } else
                setNotice(
                  stopped
                    ? "已停止接收，服务端可能继续处理；回答未确认保存。可稍后刷新历史。"
                    : "回答未确认保存，可刷新历史核对；不会自动重发。",
                );
            }
          } else if (valid(seq))
            setNotice("未获得会话编号，请刷新历史核对；不会自动重发。");
        } catch (e) {
          if (valid(seq) && !c.signal.aborted) {
            if (isSessionError(e)) expire();
            else setNotice("历史核对失败，回答未确认保存。请刷新历史。");
          }
        }
        if (valid(seq)) {
          sending.current = false;
          setBusy(false);
        }
      }
    }
  }
  return (
    <aside className="chat-panel" aria-label="论文问答">
      <div className="chat-actions">
        <select
          aria-label="聊天会话"
          value={id}
          onChange={(e) => void choose(e.target.value)}
        >
          <option value="">新会话</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>
        <button onClick={() => void choose("")}>新会话</button>
        <button disabled={busy || loading} onClick={() => void refresh()}>
          刷新历史
        </button>
      </div>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <strong>{m.role === "user" ? "你" : "助手"}</strong>
            <p>{m.content}</p>
          </div>
        ))}
        {pending && (
          <div className="message assistant">
            <strong>{busy ? "正在接收" : "未确认保存的内容"}</strong>
            <p>{pending}</p>
          </div>
        )}
        {!messages.length && !pending && <p>围绕当前论文开始提问。</p>}
      </div>
      <p className="chat-notice" role="status">
        {notice}
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label htmlFor="question">你的问题</label>
        <textarea
          id="question"
          value={draft}
          disabled={busy || loading}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
        />
        <div className="chat-actions">
          <button
            className="primary"
            disabled={busy || loading || !draft.trim()}
          >
            发送
          </button>
          {busy && (
            <button type="button" onClick={() => stream.current?.abort()}>
              停止接收
            </button>
          )}
        </div>
      </form>
      <p className="footnote">
        停止接收或切换会话不会确认服务端取消。失败后请先核对历史。
      </p>
    </aside>
  );
}
