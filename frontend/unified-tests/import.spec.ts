import { test, expect } from "@playwright/test";
test("Zotero destination uses its real form contract and task progress consumes real Flask SSE", async ({
  page,
}) => {
  const login = await page.request.post("/api/auth/login", {
    data: { username: "reader_pdf", password: "workbench-test-pass" },
  });
  const { csrf_token } = await login.json();
  await page.request.put("/api/workspace/state", {
    headers: { "X-CSRF-Token": csrf_token },
    data: {
      tabs: [],
      taskRefs: [
        {
          id: "synthetic-import-completed",
          kind: "import",
          label: "合成 RDF 导入",
        },
      ],
    },
  });
  await page.goto("/?view=tasks");
  await page.getByRole("button", { name: /合成 RDF 导入/ }).click();
  await expect(page.getByRole("dialog")).toContainText("已导入 3 篇");
  await expect(page.getByRole("dialog").locator("progress")).toHaveAttribute(
    "value",
    "100",
  );
  await page.getByRole("dialog").getByLabel("关闭", { exact: true }).click();
  await page
    .getByRole("button", { name: "导入文献", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Zotero RDF", exact: true }).click();
  await page
    .getByLabel("导入文件")
    .setInputFiles({
      name: "synthetic.rdf",
      mimeType: "application/rdf+xml",
      buffer: Buffer.from("<rdf/>"),
    });
  let body = "";
  await page.route("**/api/import/zotero", (route) => {
    body = route.request().postData() || "";
    return route.fulfill({
      status: 202,
      json: { success: true, task_id: "synthetic-import-completed" },
    });
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "开始导入", exact: true })
    .click();
  await expect.poll(() => body).toContain('name="target_category_id"');
  expect(body).toContain("\r\nroot\r\n");
  expect(body).not.toContain('name="category_id"');
});
