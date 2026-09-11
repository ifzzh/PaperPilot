export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "这篇论文不存在或已无法访问。";
    if (error.status === 429) return "请求较多，请稍后重试。";
    if (error.code === "csrf_failed") return "安全令牌失效，请重新登录。";
  }
  return "暂时无法加载，请检查连接后重试。";
}
export function isSessionError(error: unknown) {
  return (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "password_change_required")
  );
}
export async function request(
  path: string,
  signal?: AbortSignal,
  method = "GET",
  body?: unknown,
  keepalive = false,
): Promise<unknown> {
  const headers = new Headers({ Accept: "application/json" });
  if (method !== "GET") {
    for (const [key, value] of Object.entries(csrfHeaders()))
      headers.set(key, value);
  }
  if (body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    method,
    headers,
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
    keepalive,
  });
  if (
    response.status === 401 &&
    !path.startsWith("/api/auth/") &&
    typeof window !== "undefined"
  )
    window.dispatchEvent(new Event("paperpilot-session-expired"));
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(response.status, "invalid_response");
  }
  const obj = data as Record<string, unknown> | null;
  if (
    obj?.error === "password_change_required" &&
    typeof window !== "undefined"
  )
    window.dispatchEvent(new Event("paperpilot-session-expired"));
  if (!response.ok || obj?.success === false || obj?.error) {
    throw new ApiError(
      response.status,
      typeof obj?.error === "string" ? obj.error : "request_failed",
    );
  }
  return data;
}
export type User = {
  id: string;
  username: string;
  role?: string;
  must_change_password?: boolean;
};
export type Paper = {
  id: string;
  title: string;
  authors: string;
  year: string;
  abstract: string;
  starred: boolean;
  translated: boolean;
  translation: string;
  analysis: string;
  published: string;
  arxiv_url?: string;
  github?: string;
  homepage?: string;
  notes?: string;
  affiliation?: string;
  journal?: string;
  has_analysis_result?: boolean;
  category_id?: string;
};
function text(v: unknown): string {
  return typeof v === "string" ? v : "";
}
export function paperFrom(data: unknown): Paper {
  if (
    !data ||
    typeof data !== "object" ||
    typeof (data as Record<string, unknown>).id !== "string"
  )
    throw new ApiError(200, "invalid_paper");
  const p = data as Record<string, unknown>;
  return {
    id: text(p.id),
    title:
      text(p.title) ||
      text(p.original_filename) ||
      text(p.filename) ||
      "未命名论文",
    authors: text(p.authors),
    year: text(p.year),
    abstract: text(p.abstract),
    starred: p.starred === true,
    translated: p.has_chinese_version === true,
    translation: text(p.translation_status),
    analysis: text(p.analysis_status),
    published: text(p.arxiv_published_date),
    arxiv_url: text(p.arxiv_url),
    github: text(p.github),
    homepage: text(p.homepage),
    notes: text(p.notes),
    affiliation: text(p.affiliation),
    journal: text(p.journal),
    has_analysis_result: p.has_analysis_result === true,
    category_id: text(p.category_id),
  };
}
export async function session(signal: AbortSignal): Promise<User | null> {
  const data = (await request("/api/auth/session", signal)) as {
    authenticated?: boolean;
    user?: User & { must_change_password?: boolean };
  };
  if (
    !data?.authenticated ||
    data.user?.must_change_password ||
    typeof data.user?.id !== "string" ||
    typeof data.user.username !== "string"
  )
    return null;
  return { id: data.user.id, username: data.user.username };
}
export async function papers(signal: AbortSignal) {
  const data = await request("/api/papers/all", signal);
  if (!Array.isArray(data)) throw new ApiError(200, "invalid_list");
  return data.map(paperFrom);
}
export function publicationDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T|$)/.exec(value);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : "";
}

export function csrfHeaders(): Record<string, string> {
  const cookie = document.cookie
    .split(";")
    .map((v) => v.trim())
    .find((v) => v.startsWith("paperpilot_csrf="));
  if (!cookie) return {};
  try {
    return {
      "X-CSRF-Token": decodeURIComponent(
        cookie.slice("paperpilot_csrf=".length),
      ),
    };
  } catch {
    return {};
  }
}
