const {chromium} = require('playwright');
/* 첫 화면 「최근 나눈 이야기」 색 (v1.17 · 팀장 요청) + 삽화 그림체 3종 확인 — 예시 모드
     node prototype/tests/home-recent-colors.js [사진 폴더]
   · 왼쪽 아이콘 상자: 평소에도 화면 바탕과 다른 옅은 노랑 바탕 · 갈색 아이콘
   · 마우스를 올린 줄: 화면 바탕(회베이지)과 다른 옅은 노랑, 아이콘 상자와도 다른 색
   · 「문체 선택」 화면에 삽화 그림체 수채화 · 애니풍 · 유화, 고른 값이 서버로 (illust_style)
   실패하면 끝 코드 1. */
const path = require('path'); const fs = require('fs');
const [,, out = ''] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
if (out) fs.mkdirSync(out, {recursive: true});
const rgb = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number);
const dist = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
(async () => {
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const p = await (await b.newContext({viewport: {width: 1366, height: 900}})).newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  const W = (ms) => p.waitForTimeout(ms);
  await p.goto(`file://${file}?demo=1`); await W(1300);
  await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500);
  await p.click('[data-login-google]'); await W(1600);
  await p.evaluate(() => { location.hash = 'home'; }); await W(1200);
  await p.mouse.move(2, 2);
  const row = p.locator('.recent-row').first(); await row.scrollIntoViewIfNeeded();
  const read = () => row.evaluate((r) => { const th = r.querySelector('.memory-thumbnail'); return {row: getComputedStyle(r).backgroundColor, page: getComputedStyle(document.body).backgroundColor, icon: getComputedStyle(th).backgroundColor, stroke: getComputedStyle(th).color}; });
  const a = await read();
  check(dist(rgb(a.icon), rgb(a.page)) > 20, `평소 아이콘 상자 바탕이 화면 바탕과 다르다 (${a.icon} / ${a.page})`);
  check(dist(rgb(a.stroke), [255, 255, 255]) > 150, `아이콘 선이 진하다 (${a.stroke})`);
  if (out) await p.locator('.recent-panel').first().screenshot({path: path.join(out, 'home_normal.png')});
  await row.hover(); await W(400);
  const h = await read();
  check(dist(rgb(h.row), rgb(h.page)) > 12, `마우스 올린 줄 바탕이 화면 바탕과 다르다 (${h.row} / ${h.page})`);
  check(dist(rgb(h.row), rgb(h.icon)) > 12, `마우스 올린 줄 바탕과 아이콘 상자가 같은 색이 아니다 (${h.row} / ${h.icon})`);
  check(rgb(h.row)[0] >= rgb(h.row)[2] + 15, `마우스 올린 줄은 따뜻한 노랑 계열 (${h.row})`);
  if (out) await p.locator('.recent-panel').first().screenshot({path: path.join(out, 'home_hover.png')});
  // 삽화 그림체
  await p.evaluate(() => { location.hash = 'records'; }); await W(1000);
  await p.click('#choose-style'); await W(600); await p.click('#choose-style'); await W(800);
  const names = await p.locator('[data-illust-style]').evaluateAll((xs) => xs.map((x) => `${x.dataset.illustStyle}:${x.querySelector('strong').textContent}`));
  check(JSON.stringify(names) === JSON.stringify(['watercolor:수채화', 'anime:애니풍', 'oil_painting:유화']), `그림체 3종 — ${names.join(' · ')}`);
  await p.click('[data-illust-style="anime"]'); await W(200);
  check(await p.locator('[data-illust-style="anime"]').getAttribute('aria-pressed') === 'true', '애니풍을 고를 수 있다');
  await p.click('[data-style="essay"]'); await p.click('#generate-draft');
  for (let i = 0; i < 40 && await p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen) !== 'draft'; i++) await W(500);
  const sent = await p.evaluate(() => { const db = JSON.parse(localStorage.getItem('memoir.demo.db')); const js = Object.values(db.jobs || {}); return js.length ? js[js.length - 1].illust_style : null; });
  check(sent === 'anime', `만들기 요청에 illust_style = ${sent}`);
  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(fail.length ? `실패 ${fail.length}` : '모두 통과');
  process.exit(fail.length ? 1 : 0);
})();
