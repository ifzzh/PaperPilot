import { test, expect } from "@playwright/test";

test("three paper tabs restore separate document variants and clear across tabs on logout", async ({
  page,
  context,
}) => {
  const login = await page.request.post("/api/auth/login", {
    data: { username: "reader_one", password: "workbench-test-pass" },
  });
  const { csrf_token } = await login.json();
  await page.request.put("/api/workspace/state", {
    headers: { "X-CSRF-Token": csrf_token },
    data: { tabs: ["a-0", "a-4", "a-5"], activePaper: "a-0", theme: "light" },
  });
  const titles = await Promise.all(
    ["a-0", "a-4", "a-5"].map(
      async (id) =>
        (await (await page.request.get("/api/paper/" + id)).json()).title,
    ),
  );
  await page.goto("/?view=reader&paper=a-0");
  await expect(page.locator(".pdf-panel .textLayer").first()).toContainText(
    "Synthetic reader validation",
  );
  await page.getByLabel("文档版本").selectOption("translated");
  await expect(page.locator(".page-count")).toHaveText("/ 2");
  for (const title of [titles[1], titles[2], titles[0]]) {
    await page.getByRole("tab", { name: title, exact: true }).click();
    await expect(page.locator(".page-count")).toHaveText("/ 2");
    await expect(page.locator(".pdf-panel .textLayer").first()).toContainText(
      "Synthetic reader validation",
    );
  }
  await expect(page.getByLabel("文档版本")).toHaveValue("translated");
  const other = await context.newPage();
  await other.goto("/?view=reader&paper=a-4");
  await expect(other.locator(".pdf-panel .textLayer").first()).toContainText(
    "Synthetic reader validation",
  );
  await page.getByLabel("退出登录", { exact: true }).click();
  for (const tab of [page, other]) {
    await expect(
      tab.getByRole("button", { name: "登录", exact: true }),
    ).toBeVisible();
    await expect(tab.locator("canvas")).toHaveCount(0);
    await expect(tab.locator(".paper-tab")).toHaveCount(0);
  }
  expect((await page.request.get("/api/paper/a-0/file")).status()).toBe(401);
});

test("failed logout clears local content and focus does not silently restore it", async ({
  page,
}) => {
  await page.request.post("/api/auth/login", {
    data: { username: "reader_two", password: "workbench-test-pass" },
  });
  await page.goto("/?view=reader&paper=b-0");
  await expect(page.locator(".pdf-panel .textLayer").first()).toContainText(
    "Synthetic reader validation",
  );
  await page.route("**/api/auth/session", (route) =>
    route.request().method() === "DELETE" ? route.abort() : route.continue(),
  );
  await page.getByLabel("退出登录", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "重试退出", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => dispatchEvent(new Event("focus")));
  await expect(page.locator("canvas")).toHaveCount(0);
  expect(
    (await (await page.request.get("/api/auth/session")).json()).authenticated,
  ).toBe(true);
  await page.unroute("**/api/auth/session");
  await page.getByRole("button", { name: "重试退出", exact: true }).click();
  await expect(page.getByText("已退出登录。", { exact: true })).toBeVisible();
});
