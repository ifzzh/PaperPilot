import { test, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("desktop and mobile unified visual acceptance with bounded PDF rendering", async ({
  page,
}) => {
  test.setTimeout(90000);
  const root = resolve("../.devnotes/p1-evidence/unified");
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const errors: string[] = [],
    violations: string[] = [],
    external: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (
      !r.url().startsWith("http://127.0.0.2:7191") &&
      !r.url().startsWith("blob:") &&
      !r.url().startsWith("data:")
    )
      external.push(r.url());
  });
  await page.exposeFunction("recordViolation", (v: string) =>
    violations.push(v),
  );
  await page.addInitScript(() =>
    addEventListener("securitypolicyviolation", (e) =>
      (window as any).recordViolation(e.effectiveDirective),
    ),
  );
  await page.request.post("/api/auth/login", {
    data: { username: "reader_one", password: "workbench-test-pass" },
  });
  const measurements: any[] = [];
  for (const width of [1920, 1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1080 });
    for (const theme of ["light", "dark"]) {
      await page.goto("/?paper=a-0");
      await expect(page.locator(".paper-row")).toHaveCount(50);
      while ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.getByLabel("切换浅深主题").click();
      await page.screenshot({
        path: resolve(root, `library-${width}-${theme}.png`),
      });
      const start = Date.now();
      await page.goto("/?view=reader&paper=a-0");
      await expect(page.locator(".pdf-panel .textLayer").first()).toContainText(
        "Synthetic reader validation",
      );
      await expect(page.locator(".page-count")).toHaveText("/ 100");
      const metrics = await page.locator(".pdf-panel").evaluate((el) => ({
        height: el.clientHeight,
        canvasCount: el.querySelectorAll("canvas").length,
        text: el.querySelector(".textLayer")?.textContent?.slice(0, 80),
      }));
      measurements.push({
        width,
        theme,
        firstRenderMs: Date.now() - start,
        ...metrics,
      });
      expect(metrics.height).toBeGreaterThan(width === 390 ? 400 : 600);
      expect(metrics.canvasCount).toBeLessThan(12);
      await page.screenshot({
        path: resolve(root, `reader-${width}-${theme}.png`),
      });
      if (width === 390) {
        await page
          .getByRole("button", { name: "论文问答", exact: true })
          .click();
        await expect(page.getByLabel("你的问题")).toBeVisible();
        await page.screenshot({
          path: resolve(root, `chat-${width}-${theme}.png`),
        });
        await page
          .getByRole("button", { name: "返回阅读", exact: true })
          .click();
      }
    }
  }
  writeFileSync(
    resolve(root, "synthetic-metrics.json"),
    JSON.stringify({ measurements, errors, violations, external }, null, 2),
    { mode: 0o600 },
  );
  expect(errors).toEqual([]);
  expect(violations).toEqual([]);
  expect(external).toEqual([]);
});
