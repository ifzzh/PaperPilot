import {test,expect} from '@playwright/test';
test('PDF loads and renders in installed Edge with matching compatibility worker',async({page})=>{
 await page.request.post('/api/auth/login',{data:{username:'reader_one',password:'workbench-test-pass'}});
 for(const document of ['original','translated']){
  await page.goto('/workbench?paper=a-0&view=reader&document='+document);
  await expect(page.locator('.pdf-page canvas').first()).toBeVisible({timeout:20000});
  await expect(page.locator('.pdf-status')).toBeEmpty({timeout:20000});
  expect(await page.locator('.textLayer').first().textContent()).toBeTruthy();
 }
});
