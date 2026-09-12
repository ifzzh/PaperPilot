import { useState } from "react";
import { BookOpen, ArrowRight, LockKeyhole } from "lucide-react";
import { api, Field, Status } from "./ui";
import { ApiError, type User } from "./api";
export function Auth({
  user,
  onAuthenticated,
  onLogout,
}: {
  user: User | null;
  onAuthenticated: (u: User) => void;
  onLogout: () => void;
}) {
  const [mode, setMode] = useState<"login" | "register" | "reset">("login"),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [code, setCode] = useState(""),
    [next, setNext] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const changing = !!user;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (changing) {
        const r = await api("/api/auth/change-password", "POST", {
          current_password: password,
          new_password: next,
        });
        setPassword("");
        setNext("");
        onAuthenticated(r.user);
      } else if (mode === "login") {
        const r = await api("/api/auth/login", "POST", { username, password });
        setPassword("");
        onAuthenticated(r.user);
      } else if (mode === "register") {
        await api("/api/auth/register", "POST", {
          username,
          password,
          invite_code: code,
        });
        setCode("");
        setPassword("");
        setMode("login");
        setMessage("账号已创建，请登录。");
      } else {
        await api("/api/auth/reset-password", "POST", {
          reset_code: code,
          new_password: password,
        });
        setPassword("");
        setCode("");
        setMode("login");
        setMessage("密码已重置，请登录。");
      }
    } catch (err) {
      const known: Record<string, string> = {
        invalid_credentials: "账号或密码不正确。",
        registration_failed: "注册未成功，请检查账号、密码和邀请码。",
        invalid_current_password: "当前密码不正确。",
        invalid_password: "密码需为8–128位。",
      };
      setError(
        err instanceof ApiError
          ? known[err.code] || "操作未成功，请检查输入或稍后重试。"
          : "无法连接服务，请重试。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <section className="auth-story">
        <div className="brand">
          <span className="brand-mark">P</span>iPaper
        </div>
        <div>
          <span className="eyebrow">阅读 · 理解 · 发现</span>
          <h1>
            让每一篇论文，
            <br />
            连接新的思考。
          </h1>
          <p>文献整理、PDF 阅读与论文问答，在一个专注的空间里完成。</p>
          <div className="auth-illustration">
            <BookOpen size={82} strokeWidth={1} />
            <span>你的文献，你的研究空间</span>
          </div>
        </div>
        <small>本地部署 · 安全会话 · 用户数据隔离</small>
      </section>
      <section className="auth-form">
        <div className="auth-card">
          <LockKeyhole size={28} />
          <h2>
            {changing
              ? "设置新密码"
              : mode === "login"
                ? "欢迎回来"
                : mode === "register"
                  ? "创建账号"
                  : "重置密码"}
          </h2>
          <p>
            {changing
              ? "首次登录需要更新密码。"
              : "登录你的 iPaper 研究空间。"}
          </p>
          <form onSubmit={submit}>
            {!changing && mode !== "reset" && (
              <Field label="账号">
                <input
                  autoComplete="username"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </Field>
            )}
            {!changing && mode !== "login" && (
              <Field label={mode === "register" ? "邀请码" : "重置码"}>
                <input
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  autoComplete="off"
                />
              </Field>
            )}
            <Field
              label={
                changing ? "当前密码" : mode === "reset" ? "新密码" : "密码"
              }
            >
              <input
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                minLength={8}
                maxLength={128}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            {changing && (
              <Field label="新密码">
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                />
              </Field>
            )}
            <Status error={error} />
            {message && (
              <p role="status" className="notice">
                {message}
              </p>
            )}
            <button className="primary full" disabled={busy}>
              {busy
                ? "正在处理…"
                : changing
                  ? "保存新密码"
                  : mode === "login"
                    ? "登录"
                    : mode === "register"
                      ? "注册"
                      : "重置密码"}
              <ArrowRight size={16} />
            </button>
          </form>
          <div className="auth-links">
            {changing ? (
              <button onClick={onLogout}>退出登录</button>
            ) : (
              <>
                {mode !== "login" && (
                  <button onClick={() => setMode("login")}>登录已有账号</button>
                )}
                {mode !== "register" && (
                  <button onClick={() => setMode("register")}>
                    使用邀请码注册
                  </button>
                )}
                {mode !== "reset" && (
                  <button onClick={() => setMode("reset")}>忘记密码</button>
                )}
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
