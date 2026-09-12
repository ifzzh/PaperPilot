import { useEffect, useRef, useState, type ReactNode } from "react";
import { X, LoaderCircle, AlertCircle } from "lucide-react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { request, errorText, csrfHeaders, ApiError } from "./api";
export const api = <T = any,>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
  keepalive = false,
) => request(path, signal, method, body, keepalive) as Promise<T>;
export async function upload(
  path: string,
  body: FormData,
  signal?: AbortSignal,
) {
  const r = await fetch(path, {
    method: "POST",
    body,
    signal,
    credentials: "same-origin",
    headers: csrfHeaders(),
  });
  if (r.status === 401)
    window.dispatchEvent(new Event("ipaper-session-expired"));
  let data: any;
  try {
    data = await r.json();
  } catch {
    throw new ApiError(r.status, "invalid_response");
  }
  if (!r.ok || data.error || data.success === false)
    throw new ApiError(r.status, data.error || "request_failed");
  return data;
}
export function useResource<T>(path: string | null, initial: T) {
  const [data, setData] = useState(initial),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [revision, refresh] = useState(0);
  useEffect(() => {
    if (!path) return;
    const c = new AbortController();
    setLoading(true);
    setError("");
    api<T>(path, "GET", undefined, c.signal)
      .then((value) => {
        if (!c.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [path, revision]);
  return {
    data,
    setData,
    error,
    loading,
    refresh: () => refresh((n) => n + 1),
  };
}
export function Status({
  error,
  loading,
  retry,
}: {
  error?: string;
  loading?: boolean;
  retry?: () => void;
}) {
  return error ? (
    <div role="alert" className="notice error">
      <AlertCircle size={16} />
      {error}
      {retry && <button onClick={retry}>重试</button>}
    </div>
  ) : loading ? (
    <div className="loading" role="status">
      <LoaderCircle size={18} className="spin" />
      正在加载…
    </div>
  ) : null;
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    const old = document.activeElement;
    return () => {
      ref.current?.close();
      if (old instanceof HTMLElement) old.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "modal wide" : "modal"}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button className="icon-button" aria-label="关闭" onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
export function Markdown({ text }: { text: string }) {
  const html = DOMPurify.sanitize(
    marked.parse(text, { async: false }) as string,
    {
      FORBID_TAGS: ["style", "iframe", "form", "video", "audio", "object"],
      FORBID_ATTR: ["style"],
    },
  );
  const template = document.createElement("template");
  template.innerHTML = html;
  for (const img of template.content.querySelectorAll("img")) {
    const src = img.getAttribute("src") || "";
    if (
      !/^\/api\/paper\/[^/]+\/analysis\/image(?:\?|$)|^\/static\/images\//.test(
        src,
      )
    )
      img.remove();
  }
  for (const a of template.content.querySelectorAll("a")) {
    const href = a.getAttribute("href") || "";
    if (!/^(https?:\/\/|\/(?!\/)|#)/i.test(href)) a.removeAttribute("href");
    else {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
  }
  return (
    <div
      className="markdown"
      dangerouslySetInnerHTML={{ __html: template.innerHTML }}
    />
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function dateText(value: string) {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const d = new Date(value);
  if (Number.isNaN(d.getTime()))
    return /^\d{4}-\d{2}-\d{2}/.exec(value)?.[0] || "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
export function Confirm({
  title,
  detail,
  onConfirm,
  onClose,
}: {
  title: string;
  detail: string;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <p>{detail}</p>
      <Status error={error} />
      <footer>
        <button onClick={onClose}>取消</button>
        <button
          className="danger"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } catch (e) {
              setError(errorText(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在处理…" : "确认"}
        </button>
      </footer>
    </Modal>
  );
}
