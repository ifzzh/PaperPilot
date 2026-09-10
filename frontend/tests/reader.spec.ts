import { test, expect } from "@playwright/test";

test("real PDF lifecycle, coordinate round trips, streaming history and responsive views", async ({
  page,
  context,
  browser,
}, info) => {
  const result = await page.request.post("/api/auth/login", {
    data: { username: "reader_pdf", password: "workbench-test-pass" },
  });
  expect(result.ok()).toBeTruthy();
  const outside: string[] = [],
    violations: string[] = [],
    errors: string[] = [];
  page.on("request", (r) => {
    if (!r.url().startsWith("http://127.0.0.2:7191")) outside.push(r.url());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.exposeFunction("recordViolation", (s: string) =>
    violations.push(s),
  );
  await page.addInitScript(() =>
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as any).recordViolation(e.violatedDirective),
    ),
  );
  const workers: string[] = [];
  page.on("worker", (w) => workers.push(w.url()));
  await page.setViewportSize({ width: 1440, height: 1000 });
  const start = Date.now();
  await page.goto("/workbench?paper=c-0&view=reader&document=original");
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  console.log(
    "PDF cold first page ms",
    Date.now() - start,
    "browser",
    browser.version(),
  );
  expect(workers.some((url) => url.includes("pdf.worker"))).toBe(true);
  await expect(page.locator(".pdf-page canvas")).toHaveCount(1);
  expect(
    await page.locator(".pdf-page canvas").evaluate((c: HTMLCanvasElement) =>
      c
        .getContext("2d")!
        .getImageData(0, 0, c.width, c.height)
        .data.some((v, i) => i % 4 !== 3 && v < 200),
    ),
  ).toBe(true);
  const select = async () => {
    await page
      .locator(".textLayer span")
      .filter({ hasText: "中文文本选择" })
      .evaluate((el) => {
        const r = document.createRange();
        r.selectNodeContents(el);
        const s = window.getSelection()!;
        s.removeAllRanges();
        s.addRange(r);
      });
    await expect(page.getByTestId("selection-coordinates")).toContainText(
      "boxes",
    );
    return JSON.parse(
      (await page.getByTestId("selection-coordinates").textContent()) || "{}",
    );
  };
  const first = await select();
  await page.getByLabel("缩放", { exact: true }).selectOption("1.5");
  await expect(page.locator(".pdf-status")).toBeEmpty();
  const scaled = await select();
  for (let i = 0; i < 4; i++)
    expect(Math.abs(first.boxes[0][i] - scaled.boxes[0][i])).toBeLessThan(1);
  await page.getByRole("button", { name: "旋转", exact: true }).click();
  await expect(page.locator(".pdf-status")).toBeEmpty();
  const rotated = await select();
  for (let i = 0; i < 4; i++)
    expect(Math.abs(first.boxes[0][i] - rotated.boxes[0][i])).toBeLessThan(1);
  await page.getByLabel('页码',{exact:true}).fill('2');
  await expect(page.locator('.textLayer')).toContainText('page 2');
  await expect(page.locator('.textLayer')).toContainText('中文文本选择');
  const flip = Date.now();
  await page.getByLabel("页码", { exact: true }).fill("100");
  await expect(page.locator(".textLayer")).toContainText("page 100");
  console.log("PDF jump to page 100 ms", Date.now() - flip);
  await expect(page.locator(".pdf-page canvas")).toHaveCount(1);
  const version = Date.now();
  await page.getByLabel("文档版本").selectOption("translated");
  await expect(page.locator(".textLayer")).toContainText("合成译文");
  console.log("PDF switch version ms", Date.now() - version);
  await expect(page).toHaveURL(/document=translated/);
  await page.getByLabel("缩放", { exact: true }).selectOption("0.75");
  await expect(page.locator(".pdf-status")).toBeEmpty();
  await page.getByRole("button", { name: "论文问答", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "发送", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".chat-notice")).toBeEmpty();
  await page.getByLabel("你的问题").fill("hello");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-notice")).toHaveText(
    "已读取服务端保存的历史。",
  );
  await expect(page.locator(".chat-messages")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  expect(await page.locator(".chat-messages img").count()).toBe(0);
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.screenshot({
        path: info.outputPath(`${theme}-${width}-reader-chat.png`),
        fullPage: true,
      });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("文档版本").selectOption("original");
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  const warm = Date.now();
  await page.reload();
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  console.log("PDF warm reload ms", Date.now() - warm);
  await page.getByRole("button", { name: "论文问答", exact: true }).click();
  await page.getByLabel("聊天会话").selectOption({ label: "hello" });
  await expect(page.locator(".chat-messages")).toContainText("这是合成回答");
  await page.getByRole("button", { name: "新会话", exact: true }).click();
  await page.getByLabel("你的问题").fill("mid-failure");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".chat-notice")).toContainText("未确认保存");
  await page.getByRole("button", { name: "新会话", exact: true }).click();
  await page.getByLabel("你的问题").fill("slow");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止接收" })).toBeVisible();
  await page.getByRole("button", { name: "停止接收" }).click();
  await expect(page.locator(".chat-notice")).toContainText(
    "服务端可能继续处理",
  );
  await page.getByRole("button", { name: "收起问答 / 返回阅读" }).click();
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.screenshot({
        path: info.outputPath(`${theme}-${width}-reader.png`),
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  }
  console.log(
    "PDF JS heap estimate before close",
    await page.evaluate(
      () => (performance as any).memory?.usedJSHeapSize ?? null,
    ),
  );
  expect(outside).toEqual([]);
  expect(violations).toEqual([]);
  expect(errors).toEqual([]);
  const resources = await page.evaluate(() =>
    performance.getEntriesByType("resource").map((e) => ({
      name: e.name,
      bytes: (e as PerformanceResourceTiming).transferSize,
    })),
  );
  console.log("PDF resources", JSON.stringify(resources));
  await page.getByRole("button", { name: "返回详情", exact: true }).click();
  await expect(page.locator(".pdf-page canvas")).toHaveCount(0);
  await expect.poll(() => page.workers().length).toBe(0);
  await expect(page.locator("canvas")).toHaveCount(0);
  console.log(
    "PDF after close workers",
    page.workers().length,
    "JS heap estimate",
    await page.evaluate(
      () => (performance as any).memory?.usedJSHeapSize ?? null,
    ),
  );
  for (const [id, word] of [
    ["c-1", "加密"],
    ["c-2", "无法打开"],
    ["c-3", "不存在"],
  ]) {
    await page.goto(`/workbench?paper=${id}&view=reader&document=original`);
    await expect(page.locator(".pdf-status")).toContainText(word);
  }
  await page.goto("/workbench?paper=c-0&view=reader&document=original");
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  const other = await context.newPage();
  await other.goto("/workbench");
  await page.bringToFront();
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(other.getByText("会话已清除", { exact: true })).toBeVisible();
  await expect(page.locator(".pdf-page canvas")).toHaveCount(0);
});

test("strict style CSP experiment and no-Range fallback", async ({
  page,
}, info) => {
  const login = await page.request.post("/api/auth/login", {
    data: { username: "reader_pdf", password: "workbench-test-pass" },
  });
  expect(login.ok()).toBeTruthy();
  const violations: string[] = [];
  await page.exposeFunction("styleReport", (v: string) => violations.push(v));
  await page.addInitScript(() =>
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as any).styleReport(e.violatedDirective),
    ),
  );
  await page.route("**/workbench?**", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      headers: {
        ...response.headers(),
        "content-security-policy": response
          .headers()
          [
            "content-security-policy"
          ].replace("style-src 'self' 'unsafe-inline'", "style-src 'self'"),
      },
    });
  });
  let fullBytes = 0,
    requests = 0;
  await page.route("**/api/paper/c-0/file", async (route) => {
    const response = await route.fetch({
      headers: Object.fromEntries(
        Object.entries(route.request().headers()).filter(
          ([key]) => key.toLowerCase() !== "range",
        ),
      ),
    });
    const body = await response.body();
    fullBytes += body.length;
    requests++;
    await route.fulfill({
      status: 200,
      headers: {
        ...response.headers(),
        "accept-ranges": "none",
        "content-length": String(body.length),
      },
      body,
    });
  });
  await page.goto("/workbench?paper=c-0&view=reader&document=original");
  await expect(page.locator(".textLayer")).toContainText("中文文本选择");
  await page.keyboard.press("Tab");
  expect(
    await page
      .locator(":focus")
      .evaluate((el) => getComputedStyle(el).outlineStyle),
  ).not.toBe("none");
  await page.screenshot({
    path: info.outputPath("strict-style-reader.png"),
    fullPage: true,
  });
  console.log(
    "strict-style CSP experiment",
    JSON.stringify(violations),
    "no-Range bytes",
    fullBytes,
    "requests",
    requests,
  );
  expect(violations.filter((v) => v.startsWith("script"))).toEqual([]);
  expect(requests).toBe(1);
});
