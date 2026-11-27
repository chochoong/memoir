const {chromium} = require('playwright');
/* 「책에 넣지 못한 사진」 안내 시험 (v1.14 · v1.16 에서 단추가 「사진 편집」을 열도록 바뀜) — 예시 모드(?demo=1&unplaced=1)
     node prototype/tests/unplaced-photos.js [pc|m] [사진 폴더]
   · 예시 서버가 사진 붙은 첫 회차의 사진을 「책 글에 쓰이지 않음」으로, 올리다 끊긴 사진 하나를 더 돌려준다.
   · 확인: 책을 펼치면 알림 · 독서 메뉴 「사진 편집」(넣을 수 있는 사진 1 숫자), 누르면 편집 창 → 「넣지 못한 까닭 보기」에 2장(사진 1 · 빈 칸 1)과 쉬운 까닭 → 「넣을 자리 고르기」로 책에 넣기.
   · 같은 책을 unplaced 없이 열면 숫자가 없다. 실패하면 끝 코드 1. */
const path = require('path'); const fs = require('fs');
const [,, which = 'pc', out = ''] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
if (out) fs.mkdirSync(out, {recursive: true});
(async () => {
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const ctx = await b.newContext(which === 'm' ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}});
  const p = await ctx.newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message)); p.on('dialog', (d) => d.accept());
  const W = (ms) => p.waitForTimeout(ms);
  const shot = async (n) => { if (out) await p.screenshot({path: path.join(out, `${which}_${n}.jpg`), type: 'jpeg', quality: 85}); };
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  const go = async (h) => { await p.evaluate((x) => { location.hash = x; }, h); await W(900); };

  await p.goto(`file://${file}?demo=1&unplaced=1`); await W(1300);
  await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500);
  await p.click('[data-login-google]'); await W(1600);
  await go('records'); await p.click('#choose-style'); await W(600); await p.click('#choose-style'); await W(600);
  await p.click('[data-style="essay"]'); await p.click('#generate-draft');
  for (let i = 0; i < 40 && (await p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen)) !== 'draft'; i++) await W(500);
  await go('draft'); await p.click('#save-volume'); await W(5500);
  await p.click('[data-library-book]'); await W(4500);

  const btn = p.locator('#ebook-unplaced');
  check(await btn.isVisible(), '독서 메뉴에 「사진 편집」 단추가 보인다');
  check((await p.locator('#ebook-unplaced .bu-count').textContent()) === '1', '단추 숫자 = 넣을 수 있는 사진 1');
  await W(1000);
  check(/넣지 못한 사진이 2장/.test(await p.locator('#toast').textContent()), '처음 펼칠 때 알림');
  await shot('1_읽기화면');
  await p.evaluate(() => document.getElementById('toast').hidden = true);
  await btn.click(); await W(1200);
  check(await p.locator('#photo-edit[open]').isVisible(), '누르면 사진 편집 창이 열린다');
  await p.click('#photo-edit [data-pe="why"]'); await W(1200);
  check(await p.locator('#unplaced-dialog[open]').isVisible(), '「넣지 못한 까닭 보기」로 까닭 창이 열린다');
  check((await p.locator('#unplaced-dialog .bu-item').count()) === 2, '창에 2장');
  check(await p.locator('#unplaced-dialog .bu-item').first().locator('img[src^="blob:"]').count() === 1, '첫 사진은 실제 사진이 보인다');
  check(await p.locator('#unplaced-dialog .bu-item').nth(1).locator('.bu-thumb.is-empty').count() === 1, '끊긴 사진은 빈 칸');
  const txt = await p.locator('#unplaced-dialog').innerText();
  check(txt.includes('이 이야기가 책 글에 쓰이지 않았어요') && txt.includes('사진이 끝까지 올라가지 않았어요'), '쉬운 까닭 문구');
  check(!/session_not_cited|photo_not_stored|회차/.test(txt), '개발용 말(코드 · 회차)이 보이지 않는다');
  check((await p.locator('#unplaced-dialog [data-bu-save]').count()) === 1, '받을 수 있는 사진에만 「사진 저장」');
  await shot('2_창');
  await p.keyboard.press('Escape'); await W(400);
  // 넣지 못한 사진 → 「넣을 자리 고르기」 → 1장 1번째 문단 아래 (POST photo_id)
  await p.locator('#photo-edit [data-pe-place]').first().click(); await W(300);
  await p.locator('#photo-edit [data-pe-put="1:0"]').click();
  for (let i = 0; i < 40 && await p.evaluate(() => document.getElementById('photo-edit').classList.contains('is-busy')); i++) await W(250);
  await W(400);
  check(!(await p.locator('#photo-edit [data-pe-place]').count()), '넣은 사진은 「책에 넣지 못한 사진」에서 빠진다');
  check(await p.locator('#photo-edit .pe-para:has([data-pe-add="1:0"]) .pe-fig').count() >= 1, '1장 1번째 문단 아래에 들어갔다');
  check((await p.locator('#ebook-unplaced .bu-count').textContent()) === '', '독서 메뉴 숫자가 사라진다');
  await shot('3_넣은뒤');
  await p.locator('#photo-edit [data-pe="close"]:visible').first().click(); await W(400);

  // unplaced 없이 다시 열면 단추가 숨는다 (같은 예시 자료)
  await p.goto(`file://${file}?demo=1`); await W(1500);
  await go('library'); await W(1200); await p.click('[data-library-book]'); await W(4000);
  check(!(await p.locator('#ebook-unplaced .bu-count').textContent()), '넣지 못한 사진이 없으면 숫자가 없다');
  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(which, fail.length ? `실패 ${fail.length}` : '모두 통과');
  process.exit(fail.length ? 1 : 0);
})();
