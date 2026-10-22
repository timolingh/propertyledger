// Browser acceptance against exported Django fixture pages. No npm dependencies.
// Usage: node scripts/check-workflow-ui.mjs /absolute/path/to/preview-directory
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const output = path.resolve(process.argv[2] || 'docs/qa/wp1');
await mkdir(output, {recursive: true});
const profile = await mkdtemp(path.join(tmpdir(), 'propertyledger-ui-'));
const chrome = spawn(process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-pipe', `--user-data-dir=${profile}`,
], {stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe']});
let nextId = 0, buffer = '';
const pending = new Map(), events = new Map();
chrome.stdio[4].on('data', chunk => {
  buffer += chunk.toString();
  let end;
  while ((end = buffer.indexOf('\0')) >= 0) {
    const raw = buffer.slice(0, end); buffer = buffer.slice(end + 1);
    if (!raw) continue;
    const message = JSON.parse(raw);
    if (message.id && pending.has(message.id)) {
      const {resolve, reject, timer} = pending.get(message.id);
      pending.delete(message.id); clearTimeout(timer);
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
    } else if (events.has(message.method)) {
      const resolve = events.get(message.method); events.delete(message.method); resolve(message.params);
    }
  }
});
chrome.on('error', error => { for (const {reject} of pending.values()) reject(error); });
function send(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {pending.delete(id); reject(new Error(`Timed out: ${method}`));}, 15000);
    pending.set(id, {resolve, reject, timer});
    chrome.stdio[3].write(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}) + '\0');
  });
}
try {
  const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
  const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
  const command = (method, params) => send(method, params, sessionId);
  const evaluate = async expression => {
    const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await command('Page.enable');
  const load = async name => {
    // Load markup and assets as one document, avoiding file-origin storage quirks.
    const html = await readFile(path.join(output, name), 'utf8');
    const css = await readFile(path.join(output, 'workflows.css'), 'utf8');
    const js = await readFile(path.join(output, 'navigation.js'), 'utf8');
    const source = html.replace(/<link rel="stylesheet"[^>]*>/, `<style>${css}</style>`).replace(/<script src="[^"]*" defer><\/script>/, '');
    const loaded = new Promise(resolve => events.set('Page.loadEventFired', resolve));
    await command('Page.navigate', {url: pathToFileURL(path.join(output, name)).href});
    await loaded;
    await evaluate(`document.open(); document.write(${JSON.stringify(source)}); document.close();`);
    await evaluate(js);
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  };
  const screenshot = async name => {
    const {cssContentSize} = await command('Page.getLayoutMetrics');
    const result = await command('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true, clip: {x: 0, y: 0, width: cssContentSize.width, height: cssContentSize.height, scale: 1}});
    await writeFile(path.join(output, name), Buffer.from(result.data, 'base64'));
  };
  await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  await load('home.html');
  assert.equal(await evaluate('document.querySelectorAll(".workflow-card").length'), 3);
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'desktop overflow');
  await screenshot('desktop.png');
  await evaluate('document.getElementById("sidebar-collapse").click()');
  assert.equal(await evaluate('document.documentElement.classList.contains("nav-collapsed")'), true);
  assert.equal(await evaluate('document.getElementById("sidebar-collapse").getAttribute("aria-expanded")'), 'false');
  await load('home.html');
  assert.equal(await evaluate('document.documentElement.classList.contains("nav-collapsed")'), true, 'remember desktop collapse');
  await evaluate('document.getElementById("sidebar-collapse").click()');
  await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await evaluate('new Promise(resolve => setTimeout(resolve, 50))');
  assert.equal(await evaluate('document.getElementById("app-sidebar").inert'), true);
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'mobile overflow');
  await screenshot('mobile.png');
  await evaluate('document.getElementById("sidebar-open").click()');
  assert.equal(await evaluate('document.activeElement.id'), 'sidebar-close');
  assert.equal(await evaluate('document.getElementById("page-shell").inert'), true);
  assert.equal(await evaluate('document.getElementById("app-sidebar").getAttribute("aria-modal")'), 'true');
  await screenshot('mobile-menu.png');
  await evaluate('document.querySelector("#primary-navigation a:last-of-type").focus()');
  // Boundary focus trap: last visible link -> first focusable item, and reverse.
  await evaluate('window.lastNavLink = [...document.querySelectorAll("#app-sidebar a[href], #app-sidebar button")].filter(el => el.getClientRects().length).at(-1); lastNavLink.focus()');
  await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
  assert.equal(await evaluate('document.activeElement.classList.contains("brand")'), true);
  await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, modifiers: 8});
  assert.equal(await evaluate('document.activeElement === lastNavLink'), true);
  await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
  assert.equal(await evaluate('document.activeElement.id'), 'sidebar-open');
  assert.equal(await evaluate('document.getElementById("page-shell").inert'), false);
  await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  await load('records.html');
  assert.equal(await evaluate('document.querySelector("nav a[aria-current=page]").getAttribute("aria-label")'), 'Properties');
  assert.equal(await evaluate('document.querySelector("table") !== null'), true);
  await screenshot('records.png');
  await load('viewer.html');
  assert.equal(await evaluate('[...document.querySelectorAll(".workflow-card a")].some(a => a.textContent.includes("Create") || a.textContent.includes("Record"))'), false);
  await screenshot('viewer.png');
  await load('outage.html');
  assert.equal(await evaluate('document.body.textContent.includes("LedgerOS unavailable")'), true);
  await screenshot('outage.png');
  console.log('PASS: desktop/mobile layout, collapse, mobile drawer, focus trap, Escape/focus return, records active navigation, viewer actions, outage state.');
} finally {
  try { await send('Browser.close'); } catch (_) { chrome.kill(); }
}
