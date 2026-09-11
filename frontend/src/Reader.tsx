import { useEffect, useRef, useState, type RefObject } from "react";
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
  type RenderTask,
} from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import {
  PanelLeft,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  RotateCw,
  Expand,
  BookOpen,
  X,
  Quote,
  LoaderCircle,
} from "lucide-react";
import { Chat, type Excerpt } from "./Chat";
import { api, Modal, Field, Status } from "./ui";
import { type Paper, errorText } from "./api";
GlobalWorkerOptions.workerSrc = workerUrl;
const assetRoot = `${import.meta.env.BASE_URL}pdfjs/`;
type Position = {
  document: "original" | "translated";
  page: number;
  offset: number;
  zoom: number | "width" | "page";
  rotation: number;
  fingerprint: string;
  sessionId?: string | null;
};
function PdfPage({
  doc,
  number,
  scale,
  rotation,
  root,
  onReady,
  thumbnail = false,
}: {
  doc: PDFDocumentProxy;
  number: number;
  scale: number;
  rotation: number;
  root: RefObject<HTMLDivElement | null>;
  onReady?: (n: number) => void;
  thumbnail?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    [visible, setVisible] = useState(false),
    [height, setHeight] = useState(792 * scale),
    [error, setError] = useState("");
  useEffect(() => {
    const h = host.current!;
    h.style.height = `${height}px`;
    h.style.width = thumbnail ? "100%" : "fit-content";
  }, [height, thumbnail]);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries[0].isIntersecting),
      { root: root.current, rootMargin: thumbnail ? "250px" : "900px" },
    );
    observer.observe(host.current!);
    return () => observer.disconnect();
  }, [root]);
  useEffect(() => {
    if (!visible) return;
    let active = true,
      render: RenderTask | undefined,
      text: TextLayer | undefined,
      canvas: HTMLCanvasElement | undefined;
    let pdfPage: any;
    const el = host.current!;
    setError("");
    void (async () => {
      pdfPage = await doc.getPage(number);
      if (!active) return;
      const vp = pdfPage.getViewport({
        scale,
        rotation: (pdfPage.rotate + rotation) % 360,
      });
      setHeight(vp.height);
      const surface = document.createElement("div");
      surface.className = "pdf-page";
      surface.style.width = `${vp.width}px`;
      surface.style.height = `${vp.height}px`;
      surface.style.setProperty("--total-scale-factor", String(vp.scale));
      surface.style.setProperty("--scale-round-x", "1px");
      surface.style.setProperty("--scale-round-y", "1px");
      canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", `PDF 第 ${number} 页`);
      const ratio = Math.min(
        devicePixelRatio || 1,
        2,
        Math.sqrt(16000000 / (vp.width * vp.height)),
      );
      canvas.width = Math.floor(vp.width * ratio);
      canvas.height = Math.floor(vp.height * ratio);
      canvas.style.width = `${vp.width}px`;
      canvas.style.height = `${vp.height}px`;
      surface.append(canvas);
      el.replaceChildren(surface);
      render = pdfPage.render({
        canvas,
        viewport: vp,
        transform: [ratio, 0, 0, ratio, 0, 0],
      });
      await render!.promise;
      if (!active) return;
      if (!thumbnail) {
        const layer = document.createElement("div");
        layer.className = "textLayer";
        surface.append(layer);
        text = new TextLayer({
          textContentSource: await pdfPage.getTextContent(),
          container: layer,
          viewport: vp,
        });
        await text.render();
        if (!active) return;
      }
      surface.dataset.rendered = "true";
      onReady?.(number);
    })().catch((e) => {
      if (active && e?.name !== "RenderingCancelledException") {
        setError("此页渲染失败，点击页码重新加载。");
        el.replaceChildren();
      }
    });
    return () => {
      active = false;
      render?.cancel();
      text?.cancel();
      el.replaceChildren();
      void Promise.resolve(render?.promise)
        .catch(() => {})
        .then(() => {
          if (canvas) canvas.width = 0;
          pdfPage?.cleanup();
        });
    };
  }, [doc, number, scale, rotation, visible]);
  return (
    <div
      className={"page-host " + (thumbnail ? "thumbnail-page" : "")}
      data-page={thumbnail ? undefined : number}
      ref={host}
      aria-label={`第 ${number} 页`}
    >
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
export function Reader({
  preferences,
  onPreferences,
  paper,
  translated,
  onVersion,
  onClose,
  onExpired,
  drafts,
}: {
  preferences: any;
  onPreferences: (v: Record<string, unknown>) => void;
  paper: Paper;
  translated: boolean;
  onVersion: (v: boolean) => void;
  onClose: () => void;
  onExpired: () => void;
  drafts?: Map<string, string>;
}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null),
    [page, setPage] = useState(1),
    [zoom, setZoom] = useState<Position["zoom"]>("width"),
    [rotation, setRotation] = useState(0),
    [thumbs, setThumbs] = useState(
      () =>
        !matchMedia("(max-width:640px)").matches &&
        preferences.thumbnailOpen !== false,
    ),
    [chat, setChat] = useState(true),
    [mobileChat, setMobileChat] = useState(false),
    [status, setStatus] = useState("正在加载 PDF…"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [retry, setRetry] = useState(0),
    [scale, setScale] = useState(1),
    [password, setPassword] = useState(""),
    [passwordNeeded, setPasswordNeeded] = useState(false),
    [excerpt, setExcerpt] = useState<Excerpt | null>(null),
    [selection, setSelection] = useState<Excerpt | null>(null),
    [sessionId, setSessionId] = useState("");
  const [pageInput, setPageInput] = useState("1");
  useEffect(() => setPageInput(String(page)), [page]);
  const host = useRef<HTMLDivElement>(null),
    thumbRoot = useRef<HTMLDivElement>(null),
    workspace = useRef<HTMLDivElement>(null),
    passwordCallback = useRef<((v: string) => void) | null>(null),
    baseSize = useRef({ width: 612, height: 792 }),
    restore = useRef<Position | null>(null),
    point = useRef<Position | null>(null),
    latestSaved = useRef(""),
    positionLoaded = useRef(false),
    destroying = useRef<Promise<void>>(Promise.resolve()),
    alive = useRef(true);
  useEffect(() => {
    if (preferences.chatWidth)
      workspace.current?.style.setProperty(
        "--chat-width",
        preferences.chatWidth + "px",
      );
  }, [preferences.chatWidth]);
  const variant = translated ? "translated" : "original",
    url = `/api/paper/${encodeURIComponent(paper.id)}/${translated ? "chinese/" : ""}file`,
    positionUrl = `/api/paper/${encodeURIComponent(paper.id)}/reading-position`;
  async function save(keepalive = false) {
    const p = point.current;
    if (
      !positionLoaded.current ||
      !p ||
      JSON.stringify(p) === latestSaved.current
    )
      return;
    const snapshot = JSON.stringify(p);
    try {
      await api(positionUrl, "PUT", p, undefined, keepalive);
      latestSaved.current = snapshot;
    } catch (e) {
      if (alive.current) setNotice("阅读位置保存失败，请保持页面并稍后重试。");
    }
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    let task: ReturnType<typeof getDocument> | undefined;
    setDoc(null);
    setError("");
    setStatus("正在加载 PDF…");
    setSelection(null);
    setExcerpt(null);
    setPassword("");
    setPasswordNeeded(false);
    setNotice("");
    point.current = null;
    positionLoaded.current = false;
    latestSaved.current = "";
    void (async () => {
      await destroying.current;
      if (!active) return;
      const positions = api<Record<string, Position>>(
        positionUrl,
        "GET",
        undefined,
        controller.signal,
      )
        .then((value) => {
          if (active) positionLoaded.current = true;
          return value;
        })
        .catch((e) => {
          if (active && !controller.signal.aborted)
            setNotice(
              "阅读位置暂时无法加载，本次阅读不会覆盖已保存位置；请重新加载重试。",
            );
          return {} as Record<string, Position>;
        });
      task = getDocument({
        url,
        withCredentials: true,
        cMapUrl: assetRoot + "cmaps/",
        cMapPacked: true,
        standardFontDataUrl: assetRoot + "standard_fonts/",
        wasmUrl: assetRoot + "wasm/",
        useWasm: false,
        useSystemFonts: false,
        disableAutoFetch: true,
        disableStream: true,
        rangeChunkSize: 65536,
      });
      task.onPassword = (update: (value: string) => void, reason: number) => {
        if (active) {
          passwordCallback.current = update;
          setPasswordNeeded(true);
          setStatus(
            reason === 2 ? "密码不正确，请重试。" : "此 PDF 需要密码。",
          );
        }
      };
      const value = await task.promise;
      if (!active) return;
      const saved = (await positions)[variant];
      const first = await value.getPage(1);
      if (!active) return;
      const vp = first.getViewport({ scale: 1 });
      baseSize.current = { width: vp.width, height: vp.height };
      const valid =
        saved?.fingerprint === value.fingerprints[0] &&
        saved.page <= value.numPages;
      const initial: Position = valid
        ? saved
        : {
            document: variant,
            page: 1,
            offset: 0,
            zoom: "width",
            rotation: 0,
            fingerprint: value.fingerprints[0] || "unknown",
          };
      if (saved && !valid) setNotice("文档已变化，已从第一页开始阅读。");
      restore.current = initial;
      point.current = initial;
      setPage(initial.page);
      setZoom(initial.zoom);
      setRotation(initial.rotation);
      setSessionId(initial.sessionId || "");
      setDoc(value);
      setStatus("正在渲染…");
      setPasswordNeeded(false);
    })().catch((e) => {
      if (!active) return;
      setStatus("");
      if (e?.status === 401 || e?.status === 403) {
        onExpired();
        return;
      }
      const messages: Record<string, string> = {
        MissingPDFException: "PDF 文件不存在。",
        InvalidPDFException: "PDF 内容无法解析。",
        PasswordException: "PDF 密码不正确。",
      };
      setError(
        messages[e?.name] ||
          (e?.status === 404
            ? "PDF 文件不存在或已无法访问。"
            : "PDF 加载失败，请检查连接并重新加载。"),
      );
      console.error("PDF load failed", { name: e?.name, status: e?.status });
    });
    return () => {
      active = false;
      controller.abort();
      passwordCallback.current = null;
      window.getSelection()?.removeAllRanges();
      void save();
      destroying.current = task?.destroy().catch(() => {}) || Promise.resolve();
    };
  }, [url, retry]);
  useEffect(() => {
    if (!doc) return;
    const size = () => {
      const el = host.current;
      if (!el) return;
      const odd = rotation % 180 !== 0;
      const w = odd ? baseSize.current.height : baseSize.current.width,
        h = odd ? baseSize.current.width : baseSize.current.height;
      setScale(
        typeof zoom === "number"
          ? zoom
          : zoom === "width"
            ? Math.max(0.25, (el.clientWidth - 48) / w)
            : Math.max(
                0.25,
                Math.min((el.clientWidth - 48) / w, (el.clientHeight - 40) / h),
              ),
      );
    };
    const obs = new ResizeObserver(size);
    if (host.current) obs.observe(host.current);
    size();
    return () => obs.disconnect();
  }, [doc, zoom, rotation, chat, thumbs]);
  function jump(n: number, offset = 0) {
    const el = host.current?.querySelector<HTMLElement>(
      `.page-host[data-page="${n}"]`,
    );
    if (!el || !host.current) return;
    host.current.scrollTop +=
      el.getBoundingClientRect().top -
      host.current.getBoundingClientRect().top +
      offset * el.clientHeight -
      20;
    setPage(n);
  }
  useEffect(() => {
    if (doc) {
      const id = requestAnimationFrame(() =>
        jump(restore.current?.page || page, restore.current?.offset || 0),
      );
      return () => cancelAnimationFrame(id);
    }
  }, [doc]);
  useEffect(() => {
    if (point.current)
      point.current = {
        ...point.current,
        zoom,
        rotation,
        sessionId: sessionId || null,
      };
  }, [zoom, rotation, sessionId]);
  useEffect(() => {
    const t = setInterval(() => void save(), 3000);
    const hide = () => {
      if (document.visibilityState === "hidden") void save(true);
    };
    const leave = () => void save(true);
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", hide);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("pagehide", leave);
    };
  }, [positionUrl]);
  useEffect(() => {
    const t = setInterval(() => {
      if (
        doc &&
        document.visibilityState === "visible" &&
        document.hasFocus() &&
        !(mobileChat && matchMedia("(max-width:640px)").matches)
      ) {
        void api(
          `/api/paper/${encodeURIComponent(paper.id)}/read-time`,
          "POST",
          { increment: 30 },
        ).catch(() => {});
        void api("/api/settings/reading-history/record", "POST", {
          minutes: 0.5,
          paper_id: paper.id,
        }).catch(() => {});
      }
    }, 30000);
    return () => clearInterval(t);
  }, [doc, paper.id, mobileChat]);
  useEffect(() => {
    const changed = () => {
      const s = window.getSelection();
      if (
        !s?.rangeCount ||
        s.isCollapsed ||
        !host.current?.contains(s.anchorNode) ||
        !host.current.contains(s.focusNode)
      ) {
        setSelection(null);
        return;
      }
      const element =
        s.anchorNode instanceof Element
          ? s.anchorNode
          : s.anchorNode?.parentElement;
      const n = Number(
        element?.closest("[data-page]")?.getAttribute("data-page") || page,
      );
      const text = s.toString().trim().slice(0, 12000);
      if (text)
        setSelection({ text, page: n, document: variant, title: paper.title });
    };
    document.addEventListener("selectionchange", changed);
    return () => document.removeEventListener("selectionchange", changed);
  }, [paper.id, variant, page]);
  function onScroll() {
    if (!host.current || !doc || restore.current) return;
    const top = host.current.getBoundingClientRect().top + 40;
    let best: HTMLElement | null = null;
    for (const el of host.current.querySelectorAll<HTMLElement>(
      ".page-host[data-page]",
    )) {
      if (el.getBoundingClientRect().top <= top) best = el;
      else break;
    }
    if (best) {
      const n = Number(best.dataset.page);
      setPage(n);
      point.current = {
        document: variant,
        page: n,
        offset: Math.max(
          0,
          Math.min(
            1,
            (top - best.getBoundingClientRect().top) / best.clientHeight,
          ),
        ),
        zoom,
        rotation,
        fingerprint: doc.fingerprints[0] || "unknown",
        sessionId: sessionId || null,
      };
    }
  }
  function pageReady(n: number) {
    setStatus("");
    if (restore.current?.page === n) {
      jump(n, restore.current.offset);
      restore.current = null;
    }
  }
  const resized = useRef<(() => void) | null>(null);
  useEffect(() => () => resized.current?.(), []);
  function resize(e: React.PointerEvent) {
    const start = e.clientX,
      w =
        workspace.current
          ?.querySelector(".reader-chat")
          ?.getBoundingClientRect().width || 380;
    const move = (event: PointerEvent) =>
      workspace.current?.style.setProperty(
        "--chat-width",
        Math.max(300, Math.min(640, w + start - event.clientX)) + "px",
      );
    const stop = () => {
      onPreferences({
        chatWidth: Math.round(
          workspace.current
            ?.querySelector(".reader-chat")
            ?.getBoundingClientRect().width || 380,
        ),
      });
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    resized.current = stop;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }
  return (
    <main
      className={
        "reader-workspace " +
        (chat ? "with-chat " : "") +
        (thumbs ? "with-thumbnails " : "") +
        (mobileChat ? "mobile-chat" : "")
      }
      ref={workspace}
    >
      <div className="reader-toolbar">
        <button
          className="icon-button"
          aria-label="显示缩略图"
          aria-pressed={thumbs}
          onClick={() => {
            setThumbs((v) => !v);
            onPreferences({ thumbnailOpen: !thumbs });
          }}
        >
          <PanelLeft size={18} />
        </button>
        <span className="reader-document-title" title={paper.title}>
          {paper.title}
        </span>
        <label>
          <span className="sr-only">文档版本</span>
          <select
            aria-label="文档版本"
            value={variant}
            onChange={(e) => {
              void save();
              onVersion(e.target.value === "translated");
            }}
          >
            <option value="original">原文</option>
            {(paper.translated || translated) && (
              <option value="translated">译文</option>
            )}
          </select>
        </label>
        <div className="toolbar-separator" />
        <button
          className="icon-button"
          aria-label="上一页"
          disabled={!doc || page <= 1}
          onClick={() => jump(page - 1)}
        >
          <ChevronLeft size={17} />
        </button>
        <input
          aria-label="页码"
          className="page-number"
          type="number"
          value={pageInput}
          min={1}
          max={doc?.numPages || 1}
          onChange={(e) => setPageInput(e.target.value)}
          onBlur={() => {
            const n = Number(pageInput);
            if (Number.isInteger(n) && n > 0 && n <= (doc?.numPages || 1))
              jump(n);
            else setPageInput(String(page));
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
        />
        <span className="page-count">/ {doc?.numPages || "—"}</span>
        <button
          className="icon-button"
          aria-label="下一页"
          disabled={!doc || page >= doc.numPages}
          onClick={() => jump(page + 1)}
        >
          <ChevronRight size={17} />
        </button>
        <select
          aria-label="缩放"
          value={zoom}
          onChange={(e) => {
            const v = e.target.value;
            setZoom(v === "width" || v === "page" ? v : Number(v));
          }}
        >
          <option value="width">适合宽度</option>
          <option value="page">适合页面</option>
          {[0.5, 0.75, 1, 1.25, 1.5, 2, 3].map((v) => (
            <option value={v} key={v}>
              {v * 100}%
            </option>
          ))}
        </select>
        <button
          className="icon-button"
          aria-label="旋转"
          onClick={() => setRotation((v) => (v + 90) % 360)}
          disabled={!doc}
        >
          <RotateCw size={17} />
        </button>
        <button
          aria-pressed={chat}
          className="chat-toggle"
          onClick={() => {
            if (matchMedia("(max-width:640px)").matches) {
              setChat(true);
              setMobileChat((v) => !v);
            } else {
              setChat((v) => !v);
              setMobileChat(false);
            }
          }}
        >
          <MessageSquare size={17} />
          <span>{mobileChat ? "返回阅读" : "论文问答"}</span>
        </button>
      </div>
      <div className="reader-body">
        {thumbs && (
          <aside className="thumbnail-sidebar" ref={thumbRoot}>
            <div className="section-label">页面缩略图</div>
            {doc &&
              Array.from({ length: doc.numPages }, (_, i) => (
                <button
                  className={
                    page === i + 1 ? "thumbnail selected" : "thumbnail"
                  }
                  key={i}
                  onClick={() => jump(i + 1)}
                  aria-label={`跳到第 ${i + 1} 页`}
                >
                  <PdfPage
                    doc={doc}
                    number={i + 1}
                    scale={0.16}
                    rotation={0}
                    root={thumbRoot}
                    thumbnail
                  />
                  <span>{i + 1}</span>
                </button>
              ))}
          </aside>
        )}
        <section className="pdf-panel" aria-label="PDF 阅读">
          <div className="pdf-status" role="status">
            {status}
          </div>
          {error && (
            <div className="pdf-error">
              <BookOpen size={38} />
              <h2>暂时无法打开文档</h2>
              <p role="alert">{error}</p>
              <button onClick={() => setRetry((n) => n + 1)}>
                重新加载 PDF
              </button>
            </div>
          )}
          {notice && (
            <div className="notice">
              {notice}
              <button
                onClick={() => {
                  if (positionLoaded.current) void save();
                  else setRetry((n) => n + 1);
                  setNotice("");
                }}
              >
                {positionLoaded.current ? "重试保存" : "重新加载位置"}
              </button>
            </div>
          )}
          <div className="pdf-scroll" ref={host} onScroll={onScroll}>
            {doc &&
              Array.from({ length: doc.numPages }, (_, i) => (
                <PdfPage
                  key={`${doc.fingerprints[0]}-${i}`}
                  doc={doc}
                  number={i + 1}
                  scale={scale}
                  rotation={rotation}
                  root={host}
                  onReady={pageReady}
                />
              ))}
          </div>
          {selection && (
            <div className="selection-actions">
              <Quote size={16} />
              <span>已选择 {selection.text.length} 字</span>
              <button
                className="primary"
                onClick={() => {
                  setExcerpt(selection);
                  setChat(true);
                  setMobileChat(matchMedia("(max-width:640px)").matches);
                  setSelection(null);
                  window.getSelection()?.removeAllRanges();
                }}
              >
                选区提问
              </button>
              <button
                className="icon-button"
                aria-label="关闭选区操作"
                onClick={() => {
                  setSelection(null);
                  window.getSelection()?.removeAllRanges();
                }}
              >
                <X size={15} />
              </button>
            </div>
          )}
        </section>
        {chat && (
          <>
            <div
              className="resize-handle"
              role="separator"
              aria-label="调整问答宽度"
              aria-orientation="vertical"
              tabIndex={0}
              onPointerDown={resize}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                  const w =
                    workspace.current
                      ?.querySelector(".reader-chat")
                      ?.getBoundingClientRect().width || 380;
                  workspace.current?.style.setProperty(
                    "--chat-width",
                    Math.max(
                      300,
                      Math.min(640, w + (e.key === "ArrowLeft" ? 20 : -20)),
                    ) + "px",
                  );
                  onPreferences({
                    chatWidth: Math.max(
                      300,
                      Math.min(640, w + (e.key === "ArrowLeft" ? 20 : -20)),
                    ),
                  });
                }
              }}
            />
            <section className="reader-chat">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">PAPER ASSISTANT</span>
                  <h2>论文问答</h2>
                </div>
                <button
                  className="icon-button"
                  aria-label="收起问答"
                  onClick={() => {
                    setChat(false);
                    setMobileChat(false);
                  }}
                >
                  <X size={17} />
                </button>
              </div>
              <Chat
                key={paper.id}
                paperId={paper.id}
                onExpired={onExpired}
                initialSession={sessionId}
                onSessionChange={(id) => {
                  setSessionId(id);
                  if (point.current) {
                    point.current = { ...point.current, sessionId: id || null };
                    void save();
                  }
                }}
                excerpt={excerpt}
                onClearExcerpt={() => setExcerpt(null)}
                drafts={drafts}
              />
            </section>
          </>
        )}
      </div>
      {passwordNeeded && (
        <Modal
          title="输入 PDF 密码"
          onClose={() => {
            setPasswordNeeded(false);
            setPassword("");
            setError("已取消输入密码，可重新加载 PDF。");
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              passwordCallback.current?.(password);
              setPassword("");
              setPasswordNeeded(false);
            }}
          >
            <p>{status}</p>
            <Field label="文档密码">
              <input
                type="password"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            <button className="primary">打开 PDF</button>
          </form>
        </Modal>
      )}
    </main>
  );
}
