import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  errorText,
  paperFrom,
  papers,
  request,
  session,
  publicationDate,
} from "./api";
afterEach(() => vi.unstubAllGlobals());
const reply = (body: unknown, status = 200) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
describe("API boundary", () => {
  it("does not retain server paths or arbitrary metadata", () => {
    const p = paperFrom({
      id: "x",
      title: "<img onerror=evil()>",
      file_path: "/private",
      extra: { secret: "x" },
      has_chinese_version: true,
    });
    expect(p.title).toBe("<img onerror=evil()>");
    expect(p.translated).toBe(true);
    expect(p).not.toHaveProperty("file_path");
    expect(p).not.toHaveProperty("extra");
  });
  it("normalizes both HTTP and business errors", async () => {
    reply({ success: false, error: "internal path details" });
    await expect(request("/api/test")).rejects.toBeInstanceOf(ApiError);
    expect(errorText(new ApiError(500, "sensitive"))).not.toContain(
      "sensitive",
    );
    reply({ error: "missing" }, 404);
    await expect(request("/api/test")).rejects.toMatchObject({ status: 404 });
  });
  it("rejects non JSON and malformed list/session responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>failure</html>", { status: 502 }),
        ),
    );
    await expect(request("/api/test")).rejects.toMatchObject({
      status: 502,
      code: "invalid_response",
    });
    reply({ data: [] });
    await expect(papers(new AbortController().signal)).rejects.toBeInstanceOf(
      ApiError,
    );
    reply({
      authenticated: true,
      user: { id: "a", username: "reader", must_change_password: true },
    });
    expect(await session(new AbortController().signal)).toBeNull();
  });
  it("forwards cancellation and current CSRF using same-origin credentials", async () => {
    vi.stubGlobal("document", {
      cookie: "other=1; paperpilot_csrf=hello%2Bworld",
    });
    reply({ success: true });
    const c = new AbortController();
    await request("/api/auth/session", c.signal, "DELETE");
    const options = vi.mocked(fetch).mock.calls[0][1]!;
    expect(options.signal).toBe(c.signal);
    expect(options.credentials).toBe("same-origin");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "hello+world",
    );
  });
  it("keeps list order and deterministic publication dates", async () => {
    reply([{ id: "b" }, { id: "a" }]);
    expect(
      (await papers(new AbortController().signal)).map((p) => p.id),
    ).toEqual(["b", "a"]);
    expect(publicationDate("2026-09-10T00:00:00Z")).toBe("2026-09-10");
    expect(publicationDate("09/10/2026")).toBe("");
  });
});
