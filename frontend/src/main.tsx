import "vite/modulepreload-polyfill";
import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState, lazy, Suspense } from "react";
import {
  errorText,
  isSessionError,
  paperFrom,
  papers,
  publicationDate,
  request,
  session,
  type Paper,
  type User,
} from "./api";
import "./style.css";
const Reader = lazy(() =>
  import("./Reader").then((module) => ({ default: module.Reader })),
);

type State<T> = {
  status: "loading" | "ready" | "error";
  data?: T;
  error?: string;
};
const selectedFromUrl = () =>
  new URLSearchParams(location.search).get("paper") || "";
function StateMessage({
  title,
  detail,
  retry,
}: {
  title: string;
  detail?: string;
  retry?: () => void;
}) {
  return (
    <div className="state" role="status">
      <span className="state-symbol" aria-hidden="true">
        ◇
      </span>
      <h2>{title}</h2>
      {detail && <p>{detail}</p>}
      {retry && <button onClick={retry}>重新加载</button>}
    </div>
  );
}
const statusNames: Record<string, string> = {
  idle: "未开始",
  queued: "排队中",
  pending: "等待中",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  paused: "已暂停",
  interrupted: "已中断",
};
function Badges({ paper }: { paper: Paper }) {
  return (
    <span className="badges">
      {paper.starred && <span className="badge favorite">★ 已收藏</span>}
      <span className={`badge ${paper.analysis === "failed" ? "failure" : ""}`}>
        解析 / 分析 · {statusNames[paper.analysis] || "状态未知"}
      </span>
      <span
        className={`badge ${paper.translation === "failed" ? "failure" : ""}`}
      >
        翻译 · {statusNames[paper.translation] || "状态未知"}
      </span>
    </span>
  );
}
function App() {
  const [user, setUser] = useState<User | null>(null);
  const [auth, setAuth] = useState<"checking" | "ready" | "locked" | "error">(
    "checking",
  );
  const [notice, setNotice] = useState("请返回旧版登录后进入工作台。");
  const [list, setList] = useState<State<Paper[]>>({ status: "loading" });
  const [detail, setDetail] = useState<State<Paper>>({ status: "loading" });
  const [selected, setSelected] = useState(selectedFromUrl);
  const [reader, setReader] = useState(
    () => new URLSearchParams(location.search).get("view") === "reader",
  );
  const [translated, setTranslated] = useState(
    () => new URLSearchParams(location.search).get("document") === "translated",
  );
  function readerRoute(open: boolean, translatedVersion = translated) {
    const query = new URLSearchParams({ paper: selected });
    if (open) {
      query.set("view", "reader");
      query.set("document", translatedVersion ? "translated" : "original");
    }
    history.pushState(null, "", `/workbench?${query}`);
    setReader(open);
    setTranslated(translatedVersion);
  }
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  // Invalidate every pending response when authentication changes.
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const controllers = useRef(new Set<AbortController>());
  const listController = useRef<AbortController | null>(null);
  const listGeneration = useRef(0);
  const detailController = useRef<AbortController | null>(null);
  const channel = useRef<BroadcastChannel | null>(null);
  const locked = useRef(false);
  const live = useRef(true);
  function cancelAll() {
    generation.current++;
    detailGeneration.current++;
    controllers.current.forEach((c) => c.abort());
    controllers.current.clear();
  }
  function newController() {
    const c = new AbortController();
    controllers.current.add(c);
    return c;
  }
  function lock(message: string, broadcast = true) {
    locked.current = true;
    cancelAll();
    setUser(null);
    setList({ status: "loading" });
    setDetail({ status: "loading" });
    setAuth("locked");
    setNotice(message);
    setSelected("");
    setPage(1);
    history.replaceState(null, "", "/workbench");
    if (broadcast) channel.current?.postMessage("session-cleared");
  }
  async function loadList(epoch: number) {
    listController.current?.abort();
    const c = newController();
    listController.current = c;
    const seq = ++listGeneration.current;
    setList({ status: "loading" });
    setPage(1);
    try {
      const data = await papers(c.signal);
      if (
        !c.signal.aborted &&
        epoch === generation.current &&
        seq === listGeneration.current &&
        live.current
      )
        setList({ status: "ready", data });
    } catch (e) {
      if (!c.signal.aborted && epoch === generation.current && live.current) {
        if (isSessionError(e)) lock("登录已失效，请返回旧版重新登录。");
        else setList({ status: "error", error: errorText(e) });
      }
    } finally {
      controllers.current.delete(c);
    }
  }
  async function checkSession() {
    if (locked.current) return;
    cancelAll();
    const epoch = generation.current;
    const c = newController();
    setAuth("checking");
    setList({ status: "loading" });
    setDetail({ status: "loading" });
    setUser(null);
    try {
      const next = await session(c.signal);
      if (epoch !== generation.current || !live.current) return;
      if (!next) {
        lock("登录已失效或需要修改密码，请返回旧版继续。");
        return;
      }
      setUser(next);
      setAuth("ready");
      setPage(1);
      void loadList(epoch);
    } catch (e) {
      if (!c.signal.aborted && epoch === generation.current && live.current) {
        if (isSessionError(e)) lock("登录已失效，请返回旧版重新登录。");
        else setAuth("error");
      }
    } finally {
      controllers.current.delete(c);
    }
  }
  async function loadDetail(id: string) {
    detailController.current?.abort();
    const c = newController();
    detailController.current = c;
    const epoch = generation.current,
      seq = ++detailGeneration.current;
    setDetail({ status: "loading" });
    try {
      const data = paperFrom(
        await request(`/api/paper/${encodeURIComponent(id)}`, c.signal),
      );
      if (
        !c.signal.aborted &&
        epoch === generation.current &&
        seq === detailGeneration.current &&
        live.current
      )
        setDetail({ status: "ready", data });
    } catch (e) {
      if (
        !c.signal.aborted &&
        epoch === generation.current &&
        seq === detailGeneration.current &&
        live.current
      ) {
        if (isSessionError(e)) lock("登录已失效，请返回旧版重新登录。");
        else setDetail({ status: "error", error: errorText(e) });
      }
    } finally {
      controllers.current.delete(c);
    }
  }
  useEffect(() => {
    live.current = true;
    if ("BroadcastChannel" in window) {
      channel.current = new BroadcastChannel("paperpilot-workbench-session");
      channel.current.onmessage = (e) => {
        if (e.data === "session-cleared")
          lock("当前工作台会话已清除，请返回旧版确认登录状态。", false);
      };
    }
    void checkSession();
    const focus = () => {
      if (document.visibilityState === "visible") void checkSession();
    };
    const pop = () => {
      setSelected(selectedFromUrl());
      const query = new URLSearchParams(location.search);
      setReader(query.get("view") === "reader");
      setTranslated(query.get("document") === "translated");
    };
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) void checkSession();
    };
    window.addEventListener("pageshow", restored);
    window.addEventListener("focus", focus);
    window.addEventListener("popstate", pop);
    return () => {
      live.current = false;
      cancelAll();
      channel.current?.close();
      window.removeEventListener("focus", focus);
      window.removeEventListener("popstate", pop);
      window.removeEventListener("pageshow", restored);
    };
  }, []);
  useEffect(() => {
    if (auth === "ready" && selected) void loadDetail(selected);
    return () => {
      detailController.current?.abort();
      detailGeneration.current++;
    };
  }, [selected, auth]);
  function select(id: string) {
    if (id === selected) return;
    setDetail({ status: "loading" });
    history.pushState(
      null,
      "",
      id ? `/workbench?paper=${encodeURIComponent(id)}` : "/workbench",
    );
    setSelected(id);
    setReader(false);
  }
  async function logout() {
    lock("正在退出登录…");
    setBusy(true);
    try {
      await request("/api/auth/session", undefined, "DELETE");
      location.assign("/");
    } catch (e) {
      if (isSessionError(e)) location.assign("/");
      else
        setNotice(
          "本页数据已清除，但退出请求未成功。请重试退出，或返回旧版处理。",
        );
    } finally {
      if (live.current) setBusy(false);
    }
  }
  const rows = list.data || [],
    totalPages = Math.max(1, Math.ceil(rows.length / 50));
  const paper = detail.data;
  return (
    <>
      <header className="topbar">
        <a className="brand" href="/workbench">
          <span className="brand-icon" aria-hidden="true">
            P
          </span>
          PaperPilot <span className="experiment">实验工作台</span>
        </a>
        <nav aria-label="账号导航">
          <span className="username">{user?.username}</span>
          <a href="/">返回旧版</a>
          <button
            className="quiet"
            onClick={() => void logout()}
            disabled={busy}
          >
            退出登录
          </button>
        </nav>
      </header>
      {auth !== "ready" ? (
        <main className="gate">
          <StateMessage
            title={
              auth === "checking"
                ? "正在验证登录状态"
                : auth === "error"
                  ? "无法连接认证服务"
                  : "会话已清除"
            }
            detail={
              auth === "locked"
                ? notice
                : auth === "error"
                  ? "请检查连接后重试。"
                  : "正在安全地连接你的文献库。"
            }
            retry={auth === "error" ? () => void checkSession() : undefined}
          />
          {auth === "locked" && (
            <div className="gate-actions">
              <a className="button primary" href="/">
                返回旧版登录
              </a>
              <button disabled={busy} onClick={() => void logout()}>
                重试退出
              </button>
            </div>
          )}
        </main>
      ) : reader && paper && detail.status === "ready" ? (
        <Suspense fallback={<main className="gate">正在加载阅读器…</main>}>
          <Reader
            key={`${user?.id}:${paper.id}`}
            paper={paper}
            translated={translated}
            onVersion={(v) => readerRoute(true, v)}
            onClose={() => readerRoute(false)}
            onExpired={() => lock("登录已失效，请返回旧版重新登录。")}
          />
        </Suspense>
      ) : (
        <main className="workspace">
          <div className="page-heading">
            <div>
              <p className="eyebrow">你的研究，从这里继续</p>
              <h1>
                文献库{" "}
                <span className="count">
                  {list.status === "ready" ? rows.length : "—"}
                </span>
              </h1>
            </div>
            <p className="heading-note">浏览、选择，然后开始阅读。</p>
          </div>
          <div className={`panels ${selected ? "has-selection" : ""}`}>
            <section className="library" aria-label="文献列表">
              <div className="panel-heading">
                <h2>全部文献</h2>
                <button
                  className="quiet"
                  onClick={() => {
                    setPage(1);
                    void loadList(generation.current);
                  }}
                >
                  刷新列表
                </button>
              </div>
              {list.status === "loading" ? (
                <StateMessage title="正在加载文献" />
              ) : list.status === "error" ? (
                <StateMessage
                  title="文献加载失败"
                  detail={list.error}
                  retry={() => void loadList(generation.current)}
                />
              ) : rows.length === 0 ? (
                <StateMessage
                  title="文献库还是空的"
                  detail="可以返回旧版上传论文，或从 Daily arXiv 加入文献。"
                />
              ) : (
                <>
                  <ul className="paper-list">
                    {rows.slice((page - 1) * 50, page * 50).map((p) => (
                      <li key={p.id}>
                        <button
                          className={`paper-row ${selected === p.id ? "selected" : ""}`}
                          aria-current={selected === p.id ? "true" : undefined}
                          onClick={() => select(p.id)}
                        >
                          <span className="paper-heading">{p.title}</span>
                          <span className="metadata">
                            {p.authors || "作者信息待补充"}
                            {p.year && ` · ${p.year}`}
                          </span>
                          <Badges paper={p} />
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="pagination">
                    <button
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      上一页
                    </button>
                    <span aria-live="polite">
                      第 {page} / {totalPages} 页
                    </span>
                    <button
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      下一页
                    </button>
                  </div>
                </>
              )}
            </section>
            <section className="detail" aria-label="论文详情">
              <div className="panel-heading">
                <h2>论文详情</h2>
                {selected && (
                  <button className="quiet" onClick={() => select("")}>
                    返回列表
                  </button>
                )}
              </div>
              {!selected ? (
                <StateMessage
                  title="选择一篇论文"
                  detail="在左侧选择文献，查看摘要和处理状态。"
                />
              ) : detail.status === "loading" ? (
                <StateMessage title="正在加载详情" />
              ) : detail.status === "error" ? (
                <StateMessage
                  title="暂时无法查看论文"
                  detail={detail.error}
                  retry={() => void loadDetail(selected)}
                />
              ) : (
                paper && (
                  <article>
                    <p className="eyebrow">文献预览</p>
                    <h2 className="detail-title">{paper.title}</h2>
                    <p className="authors">
                      {paper.authors || "作者信息待补充"}
                    </p>
                    <p className="metadata">
                      {paper.year || "年份待补充"}
                      {publicationDate(paper.published) &&
                        ` · 发布于 ${publicationDate(paper.published)}`}
                    </p>
                    <Badges paper={paper} />
                    <div className="reading-actions">
                      <button onClick={() => readerRoute(true, false)}>
                        工作台阅读
                      </button>
                      <a
                        className="button primary"
                        href={`/viewer/${encodeURIComponent(paper.id)}`}
                      >
                        打开原文 <span aria-hidden="true">↗</span>
                      </a>
                      {paper.translated && (
                        <a
                          className="button"
                          href={`/viewer/${encodeURIComponent(paper.id)}?chinese=true`}
                        >
                          打开译文
                        </a>
                      )}
                    </div>
                    <div className="abstract">
                      <h3>摘要</h3>
                      <p>
                        {paper.abstract ||
                          "暂无摘要，可以返回旧版补充论文信息。"}
                      </p>
                    </div>
                    <p className="footnote">阅读将在现有阅读器中打开。</p>
                  </article>
                )
              )}
            </section>
          </div>
          <footer>PaperPilot · 实验功能，欢迎继续探索</footer>
        </main>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
