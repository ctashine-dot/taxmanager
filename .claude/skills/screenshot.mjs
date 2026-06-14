#!/usr/bin/env node
/**
 * taxmanager screenshot helper
 * Usage: node screenshot.mjs <tab> <output-path> [extra-js-file]
 * Tabs: dashboard, clients, julgae, fees, closure
 */

// Playwright is installed globally at /opt/node22/lib/node_modules/playwright
// Run with: NODE_PATH=/opt/node22/lib/node_modules node screenshot.mjs ...

import { createRequire } from 'module';
import { readFileSync } from 'fs';

const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const TAB_MAP = {
  dashboard: null,
  clients: 'clients',
  julgae: 'julgae',
  fees: 'fees',
  closure: 'closure',
};

const [,, tab = 'dashboard', outPath = '/tmp/taxmanager.png', extraJsFile] = process.argv;

if (!(tab in TAB_MAP)) {
  console.error(`Unknown tab: ${tab}. Valid: ${Object.keys(TAB_MAP).join(', ')}`);
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  headless: true,
});

const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Suppress Firebase/network errors in console
page.on('pageerror', () => {});
page.on('console', () => {});

await page.goto('http://localhost:8787/', { waitUntil: 'domcontentloaded', timeout: 15000 });
await page.waitForTimeout(2000);

// Inject a mock authenticated user into G and trigger re-render
await page.evaluate(() => {
  const mockUser = { uid: 'harness-uid', email: 'harness@test.local', displayName: '테스터' };
  if (window.G) {
    window.G.user = mockUser;
    // Try known render functions in this app
    if (typeof window.renderApp === 'function') window.renderApp();
    else if (typeof window.render === 'function') window.render();
    else if (typeof window.showMain === 'function') window.showMain();
    else {
      // Look for a main content div and unhide it
      const main = document.getElementById('mainSection') || document.getElementById('app') || document.querySelector('.main');
      if (main) main.style.display = '';
      const login = document.getElementById('loginSection');
      if (login) login.style.display = 'none';
    }
  }
});
await page.waitForTimeout(1000);

// Switch to the requested tab
if (TAB_MAP[tab]) {
  await page.evaluate((tabName) => {
    const tabLabels = {
      clients:  ['거래처목록', '거래처'],
      julgae:   ['신고 및 결재', '신고및결재', '신고'],
      fees:     ['수수료'],
      closure:  ['해지·폐업', '해지폐업', '해지', '폐업'],
    };
    const labels = tabLabels[tabName] || [tabName];
    const btns = Array.from(document.querySelectorAll('button, [role="tab"]'));
    for (const btn of btns) {
      const txt = (btn.textContent || '').replace(/\s+/g, ' ').trim();
      if (labels.some(l => txt.includes(l))) {
        btn.click();
        return;
      }
    }
  }, TAB_MAP[tab]);
  await page.waitForTimeout(800);
}

// Run optional extra JS from file
if (extraJsFile) {
  try {
    const js = readFileSync(extraJsFile, 'utf8');
    await page.evaluate(js);
    await page.waitForTimeout(600);
  } catch (e) {
    console.warn('extraJs error:', e.message);
  }
}

await page.screenshot({ path: outPath, fullPage: true });
console.log(`Screenshot saved: ${outPath}`);
await browser.close();
