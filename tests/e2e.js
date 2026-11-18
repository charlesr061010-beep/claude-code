/* End-to-end check of the game in a real browser.

   npx playwright install chromium   # once, if Playwright isn't set up
   python3 -m http.server 8765 &     # from the repo root
   node tests/e2e.js [http://localhost:8765/] [screenshot-dir]

   Plays a full daily game (good answers, a wrong one, a timeout), checks the
   daily schedule never repeats a prompt for 120 days, exercises Unlimited
   with a team focus and the archive, and fails on any page error. */
const { chromium } = require('playwright');

const BASE = process.argv[2] || 'http://localhost:8765/';
const SHOTS = process.argv[3] || null;
const fails = [];
const ok = (cond, msg) => { if (!cond) fails.push(msg); };

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(BASE + 'index.html');
  await page.waitForSelector('#dlg-help[open]', { timeout: 30000 });
  ok(true, 'help opens on first visit');
  await page.click('#dlg-help button[value="close"]');

  // --- daily schedule ---------------------------------------------------------
  const sched = await page.evaluate(() => {
    const out = [];
    for (let n = 1; n <= 120; n++) out.push(window.MoonshotDebug.dailyIds(n));
    return out;
  });
  const flat = sched.flat();
  ok(sched.every((d) => d.length === 7 && new Set(d).size === 7), 'each daily has 7 distinct prompts');
  ok(new Set(flat).size === flat.length, `no prompt repeats in 120 dailies (${flat.length - new Set(flat).size} repeats)`);
  const again = await page.evaluate(() => window.MoonshotDebug.dailyIds(37));
  ok(JSON.stringify(again) === JSON.stringify(sched[36]), 'schedule is deterministic');

  // --- search -----------------------------------------------------------------
  const s1 = await page.evaluate(() => window.MoonshotDebug.search('ken griffey jr').map((i) => window.MOONSHOT_DATA.players[i][0]));
  ok(s1.length === 1 && s1[0] === 'Ken Griffey Jr.', 'a Jr. query picks the Jr.: ' + s1);
  const s1b = await page.evaluate(() => window.MoonshotDebug.search('ken griffey').length);
  ok(s1b === 2, 'a bare name finds both Griffeys');
  const s1c = await page.evaluate(() => window.MoonshotDebug.search('bobby bonds jr').length);
  ok(s1c >= 1, 'an unknown suffix falls back to the bare name');
  const s2 = await page.evaluate(() => window.MoonshotDebug.search('ronald acuna').length);
  ok(s2 >= 1, 'accent-insensitive search');
  const s3 = await page.evaluate(() => window.MoonshotDebug.search("o'neill").length);
  ok(s3 >= 2, 'apostrophes ignored in search');

  // --- play a full daily ------------------------------------------------------
  await page.click('#btn-start');
  const plan = ['top', 'deep', 'mid', 'wrong', 'deep', 'timeout', 'mid'];
  for (let i = 0; i < 7; i++) {
    await page.waitForSelector('#guess');
    if (plan[i] === 'timeout') {
      await page.evaluate(() => {
        const g = JSON.parse(localStorage.getItem('moonshot.daily'));
        g.deadline = Date.now() - 10;
        localStorage.setItem('moonshot.daily', JSON.stringify(g));
      });
      await page.reload();
      await page.waitForSelector('#btn-next');
      ok((await page.textContent('.verdict')).includes('Pitch clock'), 'timeout survives reload');
      await page.click('#btn-next');
      continue;
    }
    const pick = await page.evaluate((how) => {
      const D = window.MOONSHOT_DATA;
      const g = JSON.parse(localStorage.getItem('moonshot.daily'));
      const p = { a: window.MoonshotDebug.answers(g.ids[g.cur]) };
      const used = new Set(g.inn.map((x) => x.p));
      // Skip names shared by many players so the pick shows in the 8-row dropdown.
      const count = {};
      D.players.forEach((q) => { count[q[0]] = (count[q[0]] || 0) + 1; });
      const clear = (i) => !used.has(i) && count[D.players[i][0]] <= 6;
      if (how === 'wrong') {
        const valid = new Set(p.a.map((x) => x >> 3));
        for (let i = 0; i < D.players.length; i++) if (!valid.has(i) && clear(i)) return { i, name: D.players[i][0], y: D.players[i][1], valid: false };
      }
      const order = p.a.map((x) => x >> 3).filter(clear);
      const i = how === 'top' ? order[0] : how === 'mid' ? order[Math.floor(order.length / 3)] : order[order.length - 1];
      return { i, name: D.players[i][0], y: D.players[i][1], valid: true };
    }, plan[i]);
    await page.fill('#guess', pick.name);
    await page.waitForSelector('#results li[data-pid]');
    await page.click(`#results li[data-pid="${pick.i}"]`);
    await page.waitForSelector('#btn-next');
    const verdict = await page.textContent('.verdict');
    if (pick.valid) ok(!verdict.includes('Strikeout'), `inning ${i + 1}: valid pick ${pick.name} scored`);
    else ok(verdict.includes('Strikeout'), `inning ${i + 1}: invalid pick ${pick.name} struck out`);
    if (SHOTS && i === 2) await page.screenshot({ path: `${SHOTS}/e2e-result.png`, fullPage: true });
    await page.click('#btn-next');
  }
  await page.waitForSelector('.final-dist');
  const total = Number(await page.$eval('.final-dist', (e) => parseInt(e.textContent, 10)));
  const board = Number(await page.$eval('.plate.tot', (e) => e.textContent));
  ok(total === board, 'scoreboard total matches final distance');
  ok((await page.$$('.box-row')).length === 7, 'box score has 7 rows');
  ok(!!(await page.$('svg.park')), 'ballpark chart renders');
  const share = await page.textContent('#share-text');
  ok(/Moonshot Daily #\d+ · \d+ ft/.test(share), 'share text headline');
  await page.click('details.all summary');
  await page.fill('details.all .filter', 'a');
  ok((await page.$$('details.all .all-list li')).length > 0, 'answer list filters');
  if (SHOTS) {
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `${SHOTS}/e2e-final.png`, fullPage: true });
  }
  const stats = await page.evaluate(() => JSON.parse(localStorage.getItem('moonshot.stats')));
  ok(stats && stats.played === 1 && stats.total === total, 'daily stats recorded once');
  await page.reload();
  await page.waitForSelector('.final-dist');
  const stats2 = await page.evaluate(() => JSON.parse(localStorage.getItem('moonshot.stats')));
  ok(stats2.played === 1, 'reloading a finished daily does not double-count');

  // --- unlimited with a team focus -------------------------------------------------
  await page.click('#mode-unlimited');
  await page.waitForSelector('#team-focus');
  await page.selectOption('#team-focus', 'SEA');
  await page.waitForSelector('#btn-start');
  const ids = await page.evaluate(() => JSON.parse(localStorage.getItem('moonshot.unlimited')).ids);
  const allSea = await page.evaluate((ids) => {
    const D = window.MOONSHOT_DATA;
    return ids.every((id) => (D.prompts.find((p) => p.id === id).tm || []).includes('SEA'));
  }, ids);
  ok(allSea, 'team focus deals only Mariners prompts');
  ok(new Set(ids).size === 7, 'team game has 7 distinct prompts');
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e-unlimited.png`, fullPage: true });

  // --- category focus + hard mode -----------------------------------------------
  await page.selectOption('#team-focus', '');
  await page.waitForSelector('#cat-focus');
  await page.selectOption('#cat-focus', 'fun');
  await page.waitForSelector('#btn-start');
  const funOk = await page.evaluate(() => {
    const D = window.MOONSHOT_DATA;
    const g = JSON.parse(localStorage.getItem('moonshot.unlimited'));
    const cats = ['names', 'body', 'hand', 'misc', 'debut'];
    return g.ids.every((id) => cats.includes(D.prompts.find((p) => p.id === id).c));
  });
  ok(funOk, 'category focus deals only name-game prompts');
  await page.check('#hard-mode');
  await page.click('#btn-start');
  await page.waitForSelector('#hard-form');
  ok(!(await page.$('#results')), 'hard mode hides suggestions');
  await page.fill('#guess', 'Mickey Mantel');
  await page.press('#guess', 'Enter');
  await page.waitForFunction(() => document.querySelector('#hard-msg').textContent.length > 0);
  ok(!!(await page.$('#hard-form')), 'a misspelling is not a strikeout');
  const valid = await page.evaluate(() => {
    const g = JSON.parse(localStorage.getItem('moonshot.unlimited'));
    const a = window.MoonshotDebug.answers(g.ids[g.cur]);
    return window.MOONSHOT_DATA.players[a[0] >> 3][0];
  });
  await page.fill('#guess', valid.toLowerCase());
  await page.press('#guess', 'Enter');
  await page.waitForSelector('#btn-next');
  ok(!(await page.textContent('.verdict')).includes('Strikeout'), `hard mode accepts a typed name (${valid})`);
  const jr = await page.evaluate(() => window.MoonshotDebug.resolveName('Ken Griffey Jr.', 0));
  ok(jr.pid !== undefined, 'hard mode resolves a Jr. name');

  // --- archive ---------------------------------------------------------------
  await page.click('#btn-archive');
  await page.waitForSelector('#dlg-archive[open] .arch');
  ok((await page.$$('#dlg-archive .arch')).length >= 1, 'archive lists games');
  await page.click('#dlg-archive button[value="close"]');

  // --- phone, dark -------------------------------------------------------------
  const m = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
  const mp = await m.newPage();
  mp.on('pageerror', (e) => errors.push('mobile: ' + e.message));
  await mp.goto(BASE + 'index.html');
  await mp.waitForSelector('#btn-start');
  ok(await mp.evaluate(() => document.documentElement.scrollWidth <= 390), 'no horizontal scroll at 390px');
  if (SHOTS) await mp.screenshot({ path: `${SHOTS}/e2e-mobile.png`, fullPage: true });

  ok(errors.length === 0, 'no page errors: ' + errors.join(' | '));
  await browser.close();
  if (fails.length) {
    console.log(`FAILED ${fails.length}:`);
    fails.forEach((f) => console.log('  - ' + f));
    process.exit(1);
  }
  console.log('e2e: all checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
