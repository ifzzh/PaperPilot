import { useEffect, useRef, useState } from "react";
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
  type RenderTask,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { Chat } from "./Chat";
import type { Paper } from "./api";
import "./reader.css";

GlobalWorkerOptions.workerSrc = workerUrl;
const assetRoot = `${import.meta.env.BASE_URL}pdfjs/`;
export function Reader({
  paper,
  translated,
  onVersion,
  onClose,
  onExpired,
}: {
  paper: Paper;
  translated: boolean;
  onVersion: (translated: boolean) => void;
  onClose: () => void;
  onExpired: () => void;
}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null),
    [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1),
    [rotation, setRotation] = useState(0),
    [chat, setChat] = useState(false);
  const [status, setStatus] = useState("正在加载 PDF…"),
    [retry, setRetry] = useState(0);
  const [selection, setSelection] = useState("");
  const host = useRef<HTMLDivElement>(null);
  const url = `/api/paper/${encodeURIComponent(paper.id)}/${translated ? "chinese/" : ""}file`;
  useEffect(() => {
    let active = true;
    setDoc(null);
    setPage(1);
    setRotation(0);
    setSelection("");
    setStatus("正在加载 PDF…");
    // PDF.js 6 removed the eval font compiler. WASM is disabled to preserve script-src self.
    const task = getDocument({
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
    task.onPassword = () => {
      if (active) {
        setStatus("此 PDF 已加密，请使用旧阅读器处理。");
        void task.destroy();
      }
    };
    task.promise
      .then((value) => {
        if (active) {
          setDoc(value);
          setStatus("正在渲染…");
        }
      })
      .catch((error) => {
        if (!active) return;
        if (error?.status === 401 || error?.status === 403) onExpired();
        else
          setStatus(
            error?.status === 404
              ? "PDF 文件不存在或已无法访问。"
              : "无法打开 PDF，文件可能损坏、加密或连接异常。",
          );
      });
    return () => {
      active = false;
      window.getSelection()?.removeAllRanges();
      void task.destroy();
    };
  }, [url, retry]);
  useEffect(() => {
    if (!doc || !host.current) return;
    let active = true,
      render: RenderTask | undefined,
      text: TextLayer | undefined;
    let loadedPage:
      | Awaited<ReturnType<PDFDocumentProxy["getPage"]>>
      | undefined;
    const container = host.current;
    const surface = document.createElement("div");
    surface.className = "pdf-page";
    container.replaceChildren(surface);
    setStatus("正在渲染…");
    setSelection("");
    window.getSelection()?.removeAllRanges();
    let selectListener: (() => void) | undefined;
    let pageCanvas: HTMLCanvasElement | undefined;
    void (async () => {
      loadedPage = await doc.getPage(page);
      if (!active) return;
      const viewport = loadedPage.getViewport({
        scale: zoom,
        rotation: (loadedPage.rotate + rotation) % 360,
      });
      const ratio = Math.min(
        devicePixelRatio || 1,
        2,
        Math.sqrt(16000000 / (viewport.width * viewport.height)),
      );
      const canvas = document.createElement("canvas");
      pageCanvas = canvas;
      canvas.setAttribute("aria-label", `PDF 第 ${page} 页`);
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      surface.style.width = `${viewport.width}px`;
      surface.style.height = `${viewport.height}px`;
      surface.style.setProperty("--total-scale-factor", String(viewport.scale));
      surface.style.setProperty("--scale-round-x", "1px");
      surface.style.setProperty("--scale-round-y", "1px");
      const layer = document.createElement("div");
      layer.className = "textLayer";
      surface.append(canvas, layer);
      render = loadedPage.render({
        canvas,
        viewport,
        transform: [ratio, 0, 0, ratio, 0, 0],
      });
      await render.promise;
      if (!active) return;
      text = new TextLayer({
        textContentSource: await loadedPage.getTextContent(),
        container: layer,
        viewport,
      });
      await text.render();
      if (!active) return;
      setStatus("");
      selectListener = () => {
        const selected = window.getSelection();
        if (
          !selected?.rangeCount ||
          selected.isCollapsed ||
          !layer.contains(selected.anchorNode) ||
          !layer.contains(selected.focusNode)
        ) {
          setSelection("");
          return;
        }
        const origin = surface.getBoundingClientRect();
        const boxes = Array.from(selected.getRangeAt(0).getClientRects())
          .filter((r) => r.width && r.height)
          .map((r) => {
            const first = viewport.convertToPdfPoint(
              r.left - origin.left,
              r.top - origin.top,
            );
            const last = viewport.convertToPdfPoint(
              r.right - origin.left,
              r.bottom - origin.top,
            );
            return [
              Math.min(first[0], last[0]),
              Math.min(first[1], last[1]),
              Math.max(first[0], last[0]),
              Math.max(first[1], last[1]),
            ].map((n) => Number(n.toFixed(2)));
          });
        setSelection(
          JSON.stringify({
            page,
            document: translated ? "translated" : "original",
            boxes,
          }),
        );
      };
      document.addEventListener("selectionchange", selectListener);
    })()
      .finally(() => {
        if (!active) {
          loadedPage?.cleanup();
          TextLayer.cleanup();
          if (pageCanvas) pageCanvas.width = 0;
        }
      })
      .catch(() => {
        if (active) setStatus("页面渲染失败，请重试或使用旧阅读器。");
      });
    return () => {
      active = false;
      render?.cancel();
      text?.cancel();
      if (selectListener)
        document.removeEventListener("selectionchange", selectListener);
      window.getSelection()?.removeAllRanges();
      container.replaceChildren();
      if (render)
        void render.promise
          .catch(() => {})
          .then(() => {
            loadedPage?.cleanup();
            if (pageCanvas) pageCanvas.width = 0;
            TextLayer.cleanup();
          });
      else loadedPage?.cleanup();
      TextLayer.cleanup();
    };
  }, [doc, page, zoom, rotation]);
  return (
    <main className="reader-workspace">
      <div className="reader-heading">
        <div>
          <p className="eyebrow">实验阅读器</p>
          <h1>{paper.title}</h1>
        </div>
        <button onClick={onClose}>返回详情</button>
      </div>
      <div className="reader-toolbar">
        <label>
          文档{" "}
          <select
            aria-label="文档版本"
            value={translated ? "translated" : "original"}
            onChange={(e) => onVersion(e.target.value === "translated")}
          >
            <option value="original">原文</option>
            {(paper.translated || translated) && (
              <option value="translated">译文</option>
            )}
          </select>
        </label>
        <button
          disabled={!doc || page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          上一页
        </button>
        <label>
          页码{" "}
          <input
            aria-label="页码"
            type="number"
            min={1}
            max={doc?.numPages || 1}
            value={page}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (Number.isInteger(n) && n >= 1 && n <= (doc?.numPages || 1))
                setPage(n);
            }}
          />
        </label>
        <span>/ {doc?.numPages || "—"}</span>
        <button
          disabled={!doc || page >= doc.numPages}
          onClick={() => setPage((p) => p + 1)}
        >
          下一页
        </button>
        <label>
          缩放{" "}
          <select
            aria-label="缩放"
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          >
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map((n) => (
              <option value={n} key={n}>
                {n * 100}%
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={!doc}
          onClick={() => setRotation((r) => (r + 90) % 360)}
        >
          旋转
        </button>
        <a
          href={`/viewer/${encodeURIComponent(paper.id)}${translated ? "?chinese=true" : ""}`}
        >
          旧阅读器 ↗
        </a>
        <button aria-pressed={chat} onClick={() => setChat((v) => !v)}>
          {chat ? "收起问答 / 返回阅读" : "论文问答"}
        </button>
      </div>
      <div className={`reader-body ${chat ? "with-chat" : ""}`}>
        <section className="pdf-panel" aria-label="PDF 阅读">
          <div role="status" className="pdf-status">
            {status}
            {status.includes("失败") ||
            status.includes("无法") ||
            status.includes("不存在") ? (
              <button onClick={() => setRetry((v) => v + 1)}>
                重新加载 PDF
              </button>
            ) : null}
          </div>
          <div className="pdf-scroll" ref={host} />
          <details className="coordinates">
            <summary>选区坐标（验证用，不保存）</summary>
            <output data-testid="selection-coordinates">
              {selection || "选择 PDF 文本后查看页面坐标。"}
            </output>
          </details>
        </section>
        {chat && (
          <Chat key={paper.id} paperId={paper.id} onExpired={onExpired} />
        )}
      </div>
    </main>
  );
}
