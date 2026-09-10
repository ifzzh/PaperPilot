import { test, expect } from "@playwright/test";

async function login(page, username = "reader_one") {
  const response = await page.request.post("/api/auth/login", {
    data: { username, password: "workbench-test-pass" },
  });
  expect(response.ok()).toBeTruthy();
}

test("real list, pagination, deep link, safe text and reader links", async ({
  page,
  browser,
}, info) => {
  await login(page);
  console.log("Browser:", browser.version());
  const start = Date.now();
  await page.goto("/workbench");
  await expect(page.locator(".paper-row")).toHaveCount(50);
  console.log("1000-paper first-page ms:", Date.now() - start);
  console.log(
    "Performance sample:",
    await page.evaluate(() => ({
      listBytes: (
        performance
          .getEntriesByType("resource")
          .find((e) =>
            e.name.endsWith("/api/papers/all"),
          ) as PerformanceResourceTiming
      )?.decodedBodySize,
      heapBytes: (performance as any).memory?.usedJSHeapSize,
      platform: navigator.platform,
      viewport: [innerWidth, innerHeight],
    })),
  );
  await expect(
    page.getByRole("heading", { name: "选择一篇论文" }),
  ).toBeVisible();
  const turn = Date.now();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 2 / 20 页")).toBeVisible();
  console.log("pagination ms:", Date.now() - turn);
  await page.goto("/workbench?paper=a-0");
  await expect(page.locator(".detail-title")).toContainText("Learning to read");
  await expect(page.getByRole("link", { name: "打开原文" })).toHaveAttribute(
    "href",
    "/viewer/a-0",
  );
  await expect(page.getByRole("link", { name: "打开译文" })).toHaveAttribute(
    "href",
    "/viewer/a-0?chinese=true",
  );
  await page.reload();
  await expect(page.locator(".detail-title")).toContainText("Learning to read");
  await page.goto("/workbench?paper=a-1");
  await expect(page.locator(".detail-title")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator(".detail img")).toHaveCount(0);
  await page.goto("/workbench?paper=b-0");
  await expect(page.getByText("这篇论文不存在或已无法访问。")).toBeVisible();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/papers/all", async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto("/workbench");
  await expect(
    page.getByRole("heading", { name: "正在加载文献" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("loading.png"),
    fullPage: true,
  });
  release();
  await expect(page.locator(".paper-row")).toHaveCount(50);
  await page.locator(".paper-row").first().click();
  await expect(page.locator(".detail-title")).toContainText("研究文献 1000");
  await page.locator(".paper-row").first().click();
  await expect(page.locator(".detail-title")).toContainText("研究文献 1000");
  await page.locator(".paper-row").nth(1).click();
  await expect(page.locator(".detail-title")).toContainText("研究文献 999");
  await page.goBack();
  await expect(page.locator(".detail-title")).toContainText("研究文献 1000");
  await page.goto("/workbench?paper=a-2");
  await expect(
    page.getByText("暂无摘要，可以返回旧版补充论文信息。"),
  ).toBeVisible();
});

test("rapid selection and stale response never overwrite newest detail", async ({
  page,
}) => {
  await login(page);
  await page.goto("/workbench");
  await expect(page.locator(".paper-row")).toHaveCount(50);
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => (release = r));
  await page.route("**/api/paper/a-999", async (route) => {
    await gate;
    await route.fulfill({ json: { id: "a-999", title: "STALE DETAIL" } });
  });
  await page.locator(".paper-row").nth(0).click();
  await page.locator(".paper-row").nth(1).click();
  await expect(page.locator(".detail-title")).toContainText("研究文献 999");
  release();
  await expect(page.locator(".detail-title")).not.toContainText("STALE DETAIL");
});

test("logout failure clears all tabs and permits retry", async ({
  page,
  context,
}) => {
  await login(page);
  await page.goto("/workbench?paper=a-0");
  await expect(page.locator(".detail-title")).toBeVisible();
  const other = await context.newPage();
  await other.goto("/workbench?paper=a-0");
  await expect(other.locator(".detail-title")).toBeVisible();
  await page.route("**/api/auth/session", (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill({ status: 503, json: { error: "unavailable" } })
      : route.continue(),
  );
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByText(/退出请求未成功/)).toBeVisible();
  await expect(page.locator(".paper-row")).toHaveCount(0);
  await expect(
    other.getByRole("heading", { name: "会话已清除" }),
  ).toBeVisible();
  await expect(other.locator(".detail-title")).toHaveCount(0);
  await page.unroute("**/api/auth/session");
  await page.getByRole("button", { name: "重试退出" }).click();
  await expect(page).toHaveURL("http://127.0.0.2:7191/");
  expect((await page.request.get("/api/auth/session")).status()).toBe(200);
  expect(await (await page.request.get("/api/auth/session")).json()).toEqual({
    authenticated: false,
  });
});

test("expired session and a different user on focus clear previous content", async ({
  page,
}) => {
  await login(page);
  await page.goto("/workbench?paper=a-0");
  await expect(page.locator(".detail-title")).toBeVisible();
  await login(page, "reader_two");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.locator(".username")).toHaveText("reader_two");
  await expect(page.locator(".paper-row")).toHaveCount(1);
  await expect(page.locator(".detail-title")).toHaveCount(0);
  await expect(page.getByText("这篇论文不存在或已无法访问。")).toBeVisible();
  await page.context().clearCookies();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "会话已清除" })).toBeVisible();
  await expect(page.locator(".paper-row")).toHaveCount(0);
});

test("empty, failed and loading states; mobile and theme screenshots", async ({
  page,
}, info) => {
  await login(page);
  for (const scheme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      const external: string[] = [],
        violations: string[] = [];
      const listener = (req) => {
        if (!req.url().startsWith("http://127.0.0.2:7191"))
          external.push(req.url());
      };
      page.on("request", listener);
      await page.addInitScript(() => {
        (window as any).cspViolations = [];
        document.addEventListener(
          "securitypolicyviolation",
          (e: SecurityPolicyViolationEvent) =>
            (window as any).cspViolations.push(e.violatedDirective),
        );
      });
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/workbench?paper=a-0");
      await expect(page.locator(".detail-title")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(await page.evaluate(() => (window as any).cspViolations)).toEqual(
        [],
      );
      expect(external).toEqual([]);
      page.off("request", listener);
      await page.screenshot({
        path: info.outputPath(`${scheme}-${width}-detail.png`),
        fullPage: true,
      });
      if (width === 390) {
        await page.getByRole("button", { name: "返回列表" }).click();
        await expect(page.locator(".library")).toBeVisible();
      }
    }
  }
  await page.route("**/api/papers/all", (route) => route.fulfill({ json: [] }));
  await page.goto("/workbench");
  await expect(page.getByText("文献库还是空的")).toBeVisible();
  await page.screenshot({ path: info.outputPath("empty.png"), fullPage: true });
  await page.unroute("**/api/papers/all");
  await page.route("**/api/papers/all", (route) =>
    route.fulfill({
      status: 500,
      body: "<html>server failure</html>",
      contentType: "text/html",
    }),
  );
  await page.goto("/workbench");
  await expect(page.getByText("文献加载失败")).toBeVisible();
  await page.screenshot({ path: info.outputPath("error.png"), fullPage: true });
  await page.unroute("**/api/papers/all");
  await page.getByRole("button", { name: "重新加载" }).click();
  await expect(page.locator(".paper-row")).toHaveCount(50);
  await page.keyboard.press("Tab");
  const outline = await page.evaluate(
    () => getComputedStyle(document.activeElement!).outlineStyle,
  );
  expect(outline).not.toBe("none");
});
