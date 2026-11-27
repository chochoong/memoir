const {chromium} = require('playwright');
/* 예시 자서전 미리 넣기 시험 (v1.25) — 예시 모드
     node prototype/tests/sample-book.js [pc|m]
   · ?demo=1&sample=1 로 열면 로그인돼 있고 책장에 예시 자서전 한 권 — 펼치면 사진 · AI 그림, 「사진 편집」이 열린다
   · 다시 열어도 한 권 그대로(겹쳐 넣지 않음) · 책을 지운 뒤 다시 열면 다시 들어감
   · sample 없이 열면 넣지 않는다(지금까지와 같음). 실패하면 끝 코드 1. */
const path = require('path');
const [,, which = 'pc'] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
(async () => {
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const ctx = await b.newContext(which === 'm' ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}});
  const p = await ctx.newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  const W = (ms) => p.waitForTimeout(ms);
  const books = () => p.evaluate(() => document.querySelectorAll('[data-library-book]').length);
  const screen = () => p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen);
  // sample 없이: 넣지 않는다
  await p.goto(`file://${file}?demo=1#library`); await W(2500);
  const plainDb = await p.evaluate(() => JSON.parse(localStorage.getItem('memoir.demo.db')));
  check(plainDb && !plainDb.logged && !(plainDb.memoirs || []).length, 'sample 없이 열면 로그인 · 자서전 없이 처음 그대로');
  // sample=1
  await p.goto(`file://${file}?demo=1&sample=1#library`); await W(3000);
  check(await screen() === 'library' && await books() === 1, `sample=1 로 열면 로그인된 채 책장에 예시 자서전 1권 (${await books()}권)`);
  await p.reload(); await W(3000);
  check(await books() === 1, '다시 열어도 1권 그대로 (겹쳐 넣지 않음)');
  await p.click('[data-library-book]'); await W(4500);
  const read = await p.evaluate(() => ({screen: document.querySelector('[data-screen]:not([hidden])')?.dataset.screen, figs: document.querySelectorAll('.book-figure, figure img, .ebook-figure').length, title: state.title})); // eslint-disable-line no-undef
  check(!!read.title && await p.locator('#ebook-unplaced').isVisible(), `책이 펼쳐진다 — 「${read.title}」`);
  const id = await p.evaluate(() => state.savedMemoirId || (window.MemoirLibrary.bookIds()[0])); // eslint-disable-line no-undef
  const ill = await p.evaluate(async (id) => { const v = await window.Srv.call(`/memoirs/saved/${id}/illustrations`); return v.chapters.map((c) => c.figures.map((f) => f.origin)).flat(); }, id);
  check(ill.includes('auto') && ill.includes('ai'), `예시 자서전에 엽서 사진과 AI 그림 (${ill.join(', ')})`);
  await p.evaluate(() => { const t = document.getElementById('toast'); if (t) t.hidden = true; });
  await p.locator('#ebook-unplaced').click(); await W(1200);
  check(await p.locator('#photo-edit[open]').isVisible() && await p.locator('#photo-edit .pe-tab').count() >= 3, '「사진 편집」이 열리고 장 목록이 보인다');
  await p.locator('#photo-edit [data-pe="close"]:visible').first().click(); await W(400);
  // 책을 지운 뒤 다시 열면 다시 들어간다
  await p.evaluate(async (id) => { await window.Srv.call(`/memoirs/saved/${id}`, {method: 'DELETE'}); }, id);
  await p.goto(`file://${file}?demo=1&sample=1#library`); await p.reload(); await W(3000);   // # 만 다르면 다시 읽지 않으므로 새로고침
  check(await books() === 1, '예시 책을 지우고 다시 열면 다시 1권');
  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(fail.length ? `${which} 실패 ${fail.length}` : `${which} 모두 통과`);
  process.exit(fail.length ? 1 : 0);
})();
