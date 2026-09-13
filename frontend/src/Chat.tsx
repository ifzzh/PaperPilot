import { useEffect, useRef, useState } from "react";
import { errorText, isSessionError, request } from "./api";
import { postChat, readChatStream } from "./chat-stream";
import { Markdown, Confirm } from "./ui";
import { AcademicText } from "./MathFormula";
import {
  MessageSquare,
  X,
  ArrowDown,
  Send,
  Plus,
  RefreshCw,
} from "lucide-react";
export type Excerpt = {
  text: string;
  page: number;
  document: string;
  title: string;
  sourceId?: string;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: { label: string; sourceId: string }[];
};
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
    .map((v) => ({
      role: v.role,
      content: v.content,
      sources: Array.isArray(v.sources)
        ? v.sources.filter(
            (s) =>
              /^S[1-9][0-9]{0,2}$/.test(s.label) &&
              typeof s.sourceId === "string",
          )
        : [],
    }));
}
export function Chat({
  paperId,
  onExpired,
  initialSession = "",
  onSessionChange,
  excerpt,
  onClearExcerpt,
  drafts,
  onSource,
  prepareSources,
}: {
  paperId: string;
  onExpired: () => void;
  initialSession?: string;
  onSessionChange?: (id: string) => void;
  excerpt?: Excerpt | null;
  onClearExcerpt?: () => void;
  drafts?: Map<string, string>;
  onSource?: (id: string) => void;
  prepareSources?: (signal: AbortSignal) => Promise<string[]>;
}) {
  const [sessions, setSessions] = useState<Session[]>([]),
    [id, setId] = useState(initialSession);
  const [messages, setMessages] = useState<Message[]>([]),
    [draft, setDraft] = useState(
      drafts?.get(paperId + "|" + initialSession) || "",
    );
  const [pending, setPending] = useState(""),
    [notice, setNotice] = useState("正在加载聊天历史…");
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false);
  const epoch = useRef(0),
    controller = useRef<AbortController | null>(null);
  const stream = useRef<AbortController | null>(null),
    sending = useRef(false);
  const messageHost = useRef<HTMLDivElement>(null),
    follow = useRef(true),
    scrollPositions = useRef(new Map<string, number>()),
    restoreScroll = useRef<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [away, setAway] = useState(false);
  useEffect(() => {
    if (
      restoreScroll.current !== null &&
      messageHost.current &&
      messages.length
    ) {
      messageHost.current.scrollTop = restoreScroll.current;
      restoreScroll.current = null;
    } else if (follow.current && messageHost.current)
      messageHost.current.scrollTop = messageHost.current.scrollHeight;
    else setAway(true);
  }, [messages, pending]);
  useEffect(() => {
    if (initialSession && initialSession !== id) void choose(initialSession);
  }, [initialSession]);
  function editDraft(value: string) {
    setDraft(value);
    drafts?.set(paperId + "|" + id, value);
  }
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
    if (messageHost.current)
      scrollPositions.current.set(id, messageHost.current.scrollTop);
    restoreScroll.current = scrollPositions.current.get(sessionId) ?? null;
    follow.current = restoreScroll.current === null;
    const { c, seq } = begin();
    setId(sessionId);
    setMessages([]);
    setPending("");
    setDraft(drafts?.get(paperId + "|" + sessionId) || "");
    onSessionChange?.(sessionId);
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
    const userMessage: Message = {
      role: "user",
      content:
        (excerpt
          ? `引用《${excerpt.title}》${excerpt.document === "translated" ? "译文" : "原文"}第 ${excerpt.page} 页：\n> ${excerpt.text.replace(/\n/g, "\n> ")}\n\n`
          : "") + draft.trim(),
    };
    onClearExcerpt?.();
    const original = messages;
    let sessionId = id,
      answer = "",
      stopped = false;
    editDraft("");
    follow.current = true;
    setAway(false);
    setMessages([...original, userMessage]);
    const sc = new AbortController();
    stream.current = sc;
    try {
      const sourceIds = excerpt?.sourceId
        ? [excerpt.sourceId]
        : await prepareSources?.(sc.signal);
      if (sc.signal.aborted || !valid(seq))
        throw new DOMException("Aborted", "AbortError");
      const response = await postChat(
        {
          paper_id: paperId,
          messages: [...original, userMessage],
          ...(id ? { session_id: id } : {}),
          ...(sourceIds?.length ? { source_ids: sourceIds } : {}),
        },
        sc.signal,
      );
      await readChatStream(
        response,
        sc.signal,
        (next) => {
          sessionId = next;
          if (valid(seq)) {
            setId(next);
            onSessionChange?.(next);
          }
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
        {id && (
          <button
            aria-label="删除当前会话"
            disabled={busy || loading}
            onClick={() => setDeleting(true)}
          >
            删除
          </button>
        )}
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
        <button
          title="新会话"
          aria-label="新会话"
          onClick={() => void choose("")}
        >
          <Plus size={16} />
        </button>
        <button disabled={busy || loading} onClick={() => void refresh()}>
          刷新历史
        </button>
      </div>
      <div
        className="chat-messages"
        ref={messageHost}
        onScroll={() => {
          const el = messageHost.current!;
          follow.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          if (follow.current) setAway(false);
        }}
      >
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <strong>{m.role === "user" ? "你" : "助手"}</strong>
            <Markdown text={m.content} />
            {!!m.sources?.length && (
              <nav className="source-links" aria-label="回答来源">
                {m.sources.map((s) => (
                  <button key={s.label} onClick={() => onSource?.(s.sourceId)}>
                    [{s.label}] 查看来源
                  </button>
                ))}
              </nav>
            )}
          </div>
        ))}
        {pending && (
          <div className="message assistant">
            <strong>{busy ? "正在接收" : "未确认保存的内容"}</strong>
            <Markdown text={pending} />
          </div>
        )}
        {!messages.length && !pending && (
          <div className="empty-state">
            <MessageSquare size={30} />
            <h3>与论文对话</h3>
            <p>询问方法、结果或局限，也可以选择 PDF 中的文字提问。</p>
          </div>
        )}
      </div>
      {away && (
        <button
          className="follow-latest"
          onClick={() => {
            follow.current = true;
            setAway(false);
            messageHost.current?.scrollTo({
              top: messageHost.current.scrollHeight,
              behavior: "smooth",
            });
          }}
        >
          <ArrowDown size={14} />
          回到最新
        </button>
      )}
      <p className="chat-notice" role="status">
        {notice}
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {excerpt && (
          <div className="excerpt-card">
            <div>
              <span>
                引用 · {excerpt.document === "translated" ? "译文" : "原文"}第{" "}
                {excerpt.page} 页
              </span>
              <button
                type="button"
                aria-label="移除引用"
                onClick={onClearExcerpt}
              >
                <X size={14} />
              </button>
            </div>
            <p><AcademicText text={excerpt.text} /></p>
            {excerpt.sourceId && (
              <small>
                本次将使用已核实的选区及相邻结构段落；回答中只有匹配来源的编号可以跳转。
              </small>
            )}
          </div>
        )}
        {prepareSources && !excerpt && (
          <small>
            未选择文字时，使用当前结构块和相邻段落；不会自动检索或解析全文。
          </small>
        )}
        <label htmlFor="question">你的问题</label>
        <textarea
          id="question"
          value={draft}
          disabled={busy || loading}
          onChange={(e) => editDraft(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              void send();
            }
          }}
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
      {deleting && (
        <Confirm
          title="删除当前会话"
          detail="该会话的问答历史将被删除。"
          onClose={() => setDeleting(false)}
          onConfirm={async () => {
            await request(
              `/api/paper/chat/session?paper_id=${encodeURIComponent(paperId)}&session_id=${encodeURIComponent(id)}`,
              undefined,
              "DELETE",
            );
            drafts?.delete(paperId + "|" + id);
            setSessions((v) => v.filter((s) => s.id !== id));
            await choose("");
          }}
        />
      )}
    </aside>
  );
}
