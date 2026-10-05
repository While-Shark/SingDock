'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const baseURL = 'http://127.0.0.1:18101';
const screenshots = process.env.SCREENSHOT_DIR || 'browser-results';
const credentials = {username:'admin', password:'synthetic-browser-password'};

async function main() {
  await fs.mkdir(screenshots, {recursive:true});
  const browser = await chromium.launch();
  try {
    for (const [name, viewport] of [['desktop', {width:1280, height:900}], ['mobile', {width:390, height:844}]]) {
      const context = await browser.newContext({viewport, httpCredentials:credentials});
      await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin:baseURL});
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(baseURL);
      await page.locator('#nodes tr').nth(9).waitFor();
      await page.waitForFunction(() => document.getElementById('notice').textContent.includes('配置已加载'));
      assert.equal(await page.locator('#nodes tr').count(), 10);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Page overflows viewport');
      await page.screenshot({path:path.join(screenshots, `${name}.png`), fullPage:true});
      // Select two nodes and fill a continuous range.
      const first = page.locator('#nodes tr').nth(0);
      const second = page.locator('#nodes tr').nth(1);
      await first.locator('[type=checkbox]').check();
      await second.locator('[type=checkbox]').check();
      const start = name === 'desktop' ? 32000 : 33000;
      await page.locator('#batch-ports').fill(String(start));
      await page.locator('#assign').click();
      assert.equal(await first.locator('[type=number]').inputValue(), String(start));
      assert.equal(await second.locator('[type=number]').inputValue(), String(start + 1));
      await page.locator('#preview').click();
      await page.locator('#confirmation[open]').waitFor();
      assert.equal(await page.locator('#changes .change').count(), 2);
      await page.screenshot({path:path.join(screenshots, `${name}-preview.png`), fullPage:true});
      await page.locator('#cancel').click();
      const before = await context.request.get(baseURL + '/api/nodes');
      const beforeState = await before.json();
      assert.notEqual(beforeState.nodes[0].port, start, 'Preview/cancel changed configuration');
      await page.locator('#preview').click();
      await page.locator('#confirmation[open]').waitFor();
      await page.locator('#apply').click();
      await page.waitForFunction(() => document.getElementById('notice').textContent.includes('端口已应用'));
      const after = await context.request.get(baseURL + '/api/nodes');
      assert.equal((await after.json()).nodes[0].port, start);
      // Refresh rebuilds selection. Check a custom list and invalid list length.
      await first.locator('[type=checkbox]').check();
      await second.locator('[type=checkbox]').check();
      await page.locator('#mode').selectOption('list');
      await page.locator('#batch-ports').fill('34000');
      await page.locator('#assign').click();
      await page.waitForFunction(() => document.getElementById('notice').textContent.includes('列表数量'));
      await page.locator('#batch-ports').fill('34000, 34010');
      await page.locator('#assign').click();
      assert.equal(await first.locator('[type=number]').inputValue(), '34000');
      assert.equal(await second.locator('[type=number]').inputValue(), '34010');
      // Simulate a competing write after preview; its error must stay visible in the dialog.
      await page.locator('#preview').click();
      await page.locator('#confirmation[open]').waitFor();
      const current = await context.request.get(baseURL + '/api/nodes');
      const state = await current.json();
      const competing = await context.request.post(baseURL + '/api/apply', {
        headers:{'X-SingDock-Request':'1', 'Content-Type':'application/json'},
        data:{ports:{'ss': name === 'desktop' ? 35000 : 35001}, revision:state.revision}
      });
      assert(competing.ok());
      await page.locator('#apply').click();
      await page.waitForFunction(() => document.getElementById('confirmation-notice').textContent.includes('配置已变化'));
      assert(await page.locator('#confirmation-notice').isVisible());
      await page.locator('#cancel').click();
      await page.locator('#refresh').click();
      await page.waitForFunction(() => document.getElementById('notice').textContent.includes('配置已加载'));
      await page.locator('#links').click();
      await page.locator('#share[open]').waitFor();
      assert((await page.locator('#share-text').inputValue()).includes('example.invalid'));
      await page.locator('#copy').click();
      await page.waitForFunction(() => document.getElementById('share-notice').textContent.includes('已复制'));
      await page.keyboard.press('Escape');
      await page.locator('#share[open]').waitFor({state:'hidden'});
      // Native dialog close events are queued after the open attribute changes.
      // Wait for the cleanup side effect rather than racing its event handler.
      await page.waitForFunction(() => document.getElementById('share-text').value === '');
      assert.equal(await page.locator('#share-text').inputValue(), '');
      assert.deepEqual(errors, [], 'Unexpected browser JS errors');
      console.log(`PASS: ${name} layout, batches, preview/cancel/apply, stale preview, links and clipboard`);
      await context.close();
    }
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
