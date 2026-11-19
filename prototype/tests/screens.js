const {chromium} = require('playwright');
/* 23개 화면 돌아보기 — 예시 모드(?demo=1)로 처음가기부터 인터뷰 마치기까지 누르며, 화면마다 사진을 찍고 오류를 모은다.
     node prototype/tests/screens.js [pc|m] [사진 폴더] [이름표]
   · 먼저 python prototype/build.py 로 prototype/index.html 을 만든다. 서버 · 유료 API 를 부르지 않는다.
   · 사진 폴더를 주면 <이름표>_<pc|m>_<화면>.jpg 로 찍는다 (고치기 전 · 뒤를 찍어 비교). 안 주면 찍지 않는다.
   · 자바스크립트 오류가 하나라도 있거나 화면 단계가 실패하면 끝 코드 1.
   · 주소 뒤 값을 더하려면 Q 환경 변수 (예: Q='&tone=buttons'). 다른 파일을 보려면 FILE 환경 변수.
   필요: npm 의 playwright (크로미움 포함). */
const path = require('path'); const fs = require('fs');
const [,, which = 'pc', out = '', tag = 'now'] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
if (out) fs.mkdirSync(out, {recursive: true});
(async () => {
  const b = await chromium.launch({args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--allow-file-access-from-files']});
  const ctx = await b.newContext(which === 'm' ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}});
  await ctx.grantPermissions(['microphone']);
  const p = await ctx.newPage(); const log = []; p.on('pageerror', (e) => log.push('ERR ' + e.message)); p.on('dialog', (d) => d.accept());
  const vis = () => p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen);
  const W = (ms) => p.waitForTimeout(ms);
  const hideToast = () => p.evaluate(() => { const t = document.getElementById('toast'); if (t) t.hidden = true; });
  const shot = async (n, full = true) => { await hideToast();
    await p.evaluate((f) => { let st = document.getElementById('cmp-hide'); if (!st) { st = document.createElement('style'); st.id = 'cmp-hide'; document.head.append(st); } st.textContent = '.demo-badge{display:none!important}' + (f ? '.mobile-nav,.draft-dock,.srv-gen-pill{display:none!important}' : ''); }, full);
    if (full) { await p.evaluate(() => scrollTo(0, 0)); await W(300); }
    if (out) await p.screenshot({path: path.join(out, `${tag}_${which}_${n}.jpg`), type: 'jpeg', quality: 82, fullPage: full}); log.push('ok ' + n); };
  const step = async (n, fn) => { try { await fn(); } catch (e) { log.push(`FAIL ${n} ${e.message.split('\n')[0]}`); } };
  const go = async (h) => { await p.evaluate((x) => { location.hash = x; }, h); await W(900); };
  await p.goto(`file://${file}?demo=1${process.env.Q || ""}`); await W(1300);
  await step('01_첫화면_로그인전', () => shot('01_첫화면_로그인전'));
  await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500);
  await step('02_로그인창', () => shot('02_로그인창', false));
  await p.click('[data-login-google]'); await W(1600);
  await step('03_처음가기', async () => { await go('home'); await shot('03_처음가기'); });
  await step('04_이용안내', async () => { await p.evaluate(() => document.querySelector('[data-help]').click()); await W(500); await shot('04_이용안내', false); await p.evaluate(() => document.getElementById('help-dialog').close()); });
  await step('05_시작고르기', async () => { await go('start'); await shot('05_시작고르기'); });
  await step('06_내이야기_시작', async () => { await p.click('[data-start="self"]'); await W(500); await shot('06_내이야기_시작'); });
  await step('07_초대주소_만들기', async () => { await go('start'); await p.click('[data-start="invite"]'); await W(500); await shot('07_초대주소_만들기'); });
  await step('08_엽서보드', async () => { await go('records'); await shot('08_엽서보드'); });
  await step('09_엽서펼치기', async () => { await p.click('#record-list .pc-slot:nth-child(1) .postcard-card'); await W(1500); await shot('09_엽서펼치기', false); await p.click('[data-pc-close]'); await W(1300); });
  await step('10_주인공고르기', async () => { await p.evaluate(() => [...document.querySelectorAll('[data-role="pick-elder"]')].find((x) => x.offsetParent).click()); await W(500); await shot('10_주인공고르기', false);
    await p.click('.elder-pick-dialog [data-role="manage-elders"]'); await W(600); await shot('10b_이름고치기', false); await p.keyboard.press('Escape'); await W(400); });
  await step('11_엽서고르기', async () => { await go('records'); await p.click('#choose-style'); await W(600); await shot('11_엽서고르기'); });
  await step('12_문체고르기', async () => { await p.click('#choose-style'); await W(600); await shot('12_문체고르기'); });
  await step('13_만드는중', async () => { await p.click('[data-style="essay"]'); await p.click('#generate-draft'); await W(700); await shot('13_만드는중', false); });
  await step('14_초안', async () => { for (let i = 0; i < 30 && (await vis()) !== 'draft'; i++) await W(500); await W(1500); await shot('14_초안'); });
  await step('15_초안_글수정', async () => { await p.click('#edit-draft'); await W(500); await shot('15_초안_글수정'); await p.click('#edit-draft').catch(() => {}); await W(300); });
  await step('16_책장', async () => { await go('draft'); await p.click('#save-volume'); await W(5500); await shot('16_책장'); });
  await step('17_책읽기', async () => { await p.click('[data-library-book]'); await W(4500); await shot('17_책읽기', false); });
  await step('18_보기설정', async () => { await p.click('#ebook-open-settings'); await W(600); await shot('18_보기설정', false); await p.keyboard.press('Escape'); await W(400); await p.click('#ebook-back, [data-ebook-close], .ebook-back').catch(() => {}); await W(800); });
  await step('19_인터뷰_말로', async () => { await go('start'); await p.click('[data-start="self"]'); await W(500); await p.click('[data-screen="start-self"] .sc-make'); await W(2400); await shot('19_인터뷰_말로'); });
  await step('20_인터뷰_글로', async () => { await p.click('#toggle-answer'); await W(1500); await shot('20_인터뷰_글로'); });
  await step('21_인터뷰_글보낸뒤', async () => { await p.fill('#answer-text', '골목 끝 가게에서 사탕을 사 먹던 기억이 나요. 할머니가 쥐여 주신 동전을 꼭 쥐고 달려갔지요.');
    await p.click('#answer-panel [type="submit"]'); for (let i = 0; i < 30; i++) { await W(500); if (!(await p.evaluate(() => document.getElementById('answer-text').value))) break; } await W(600);
    await p.evaluate(() => document.getElementById('answer-panel').scrollIntoView({block: 'center'})); await W(300); await shot('21_인터뷰_글보낸뒤', false); });
  await step('22_마치기확인', async () => { await p.click('#finish-interview'); await W(700); await shot('22_마치기확인', false); });
  const bad = log.filter((x) => !x.startsWith('ok'));
  console.log(which, bad.join(' | ') || '모두 통과', `${log.length - bad.length}/23 화면`);
  await b.close();
  process.exit(bad.length ? 1 : 0);
})();
