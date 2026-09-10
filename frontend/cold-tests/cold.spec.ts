import { test, expect } from '@playwright/test';

test('cold direct entry loads persisted assets and isolates populated and empty users', async ({ browser }, info) => {
  for (const [username, count] of [['reader_one', 6], ['reader_two', 1], ['empty_reader', 0]] as const) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const violations: string[] = [];
    const external: string[] = [];
    await page.addInitScript(() => document.addEventListener('securitypolicyviolation', e => {
      (window as any).__csp = ((window as any).__csp || []).concat(e.violatedDirective);
    }));
    page.on('request', r => { if (!r.url().startsWith('http://127.0.0.3:7191/')) external.push(r.url().split('?')[0]); });
    const response = await context.request.post('http://127.0.0.3:7191/api/auth/login', {data: {username, password:'workbench-test-pass'}});
    expect(response.ok()).toBeTruthy();
    const list = page.waitForResponse(r => r.url().endsWith('/api/papers/all'));
    await page.goto('http://127.0.0.3:7191/workbench');
    expect((await (await list).json()).length).toBe(count);
    await expect(page.locator('.paper-row')).toHaveCount(count);
    if (count) {
      await page.goto(`http://127.0.0.3:7191/workbench?paper=${username === 'reader_one' ? 'a-1' : 'b-0'}`);
      await expect(page.locator('.detail-title')).toBeVisible();
    }
    for (const width of [1440, 390]) for (const colorScheme of ['light', 'dark'] as const) {
      await page.setViewportSize({width, height: 900});
      await page.emulateMedia({colorScheme});
      await page.screenshot({path: info.outputPath(`${username}-${width}-${colorScheme}.png`), fullPage:true});
    }
    expect((await context.request.get('http://127.0.0.3:7191/api/paper/' + (username === 'reader_one' ? 'b-0' : 'a-1'))).status()).toBe(404);
    violations.push(...await page.evaluate(() => (window as any).__csp || []));
    expect(violations).toEqual([]); expect(external).toEqual([]);
    await context.close();
  }
});
