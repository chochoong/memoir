/* 책 읽기 화면 「공유」가 펼친 그 책을 보내는지 — 11-19 제보 「공유하면 글 하나가 사라짐」 되풀이 막기
     node prototype/tests/share-open-book.js
   예시 모드에서 같은 엽서로 책 두 권(제목이 같다)을 만든 뒤
     ① 두 번째 책을 초안 「책으로 미리 읽기」로 볼 때는 공유 버튼이 숨는지
     ② 두 번째 책을 책장에서 펼쳐 공유하면 두 번째 책의 번호가 서버로 가는지 (예전에는 제목이 같은 첫 책이 갔다)
   틀리면 끝 코드 1. 먼저 python prototype/build.py. 필요: npm 의 playwright. */
const path = require('path');
const {chromium} = require('playwright');
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
(async () => {
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const p = await (await b.newContext({viewport: {width: 1366, height: 900}})).newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(e.message)); p.on('dialog', (d) => d.accept());
  const W = (ms) => p.waitForTimeout(ms);
  const go = async (h) => { await p.evaluate((x) => { location.hash = x; }, h); await W(900); };
  const vis = () => p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen);
  const make = async () => {
    await go('records'); await p.click('#choose-style'); await W(600); await p.click('#choose-style'); await W(600);
    await p.click('[data-style="essay"]'); await p.click('#generate-draft'); await W(700);
    for (let i = 0; i < 30 && (await vis()) !== 'draft'; i++) await W(500);
    await W(1200);
  };
  // 공유 창을 열고 「공유 링크 만들기」까지 눌러, 서버로 간 책 번호를 돌려준다
  const share = () => p.evaluate(async () => {
    let sent = null; const f = window.fetch;
    window.fetch = async (u, i) => { if (String(u).includes('/shares') && i && i.method === 'POST') sent = JSON.parse(i.body).book_id; return f(u, i); };
    const btn = document.getElementById('ebook-share-book');
    if (!btn || btn.hidden) { window.fetch = f; return {hidden: true, sent: null}; }
    btn.click(); await new Promise((r) => setTimeout(r, 1500));
    document.querySelector('.share-create')?.click(); await new Promise((r) => setTimeout(r, 1500));
    window.fetch = f; return {hidden: false, sent};
  });

  await p.goto(`file://${file}?demo=1`); await W(1300);
  await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500);
  await p.click('[data-login-google]'); await W(1600);
  await make(); await go('draft'); await p.click('#save-volume'); await W(5500); // 책 1 — 책장에 꽂음
  await make();                                                                  // 책 2 — 같은 제목, 아직 초안
  const second = await p.evaluate(() => window.MemoirLibrary.bookIds().slice(-1)[0]);
  const titles = await p.evaluate(() => window.MemoirLibrary.bookIds().map((id) => window.MemoirLibrary.getBook(id).title));
  await p.click('[data-screen="draft"] [data-go="reader"]'); await W(2500);
  const preview = await share();
  await p.evaluate(() => document.getElementById('ebook-exit')?.click()); await W(800);
  await go('library'); await W(800);
  await p.evaluate((id) => window.MemoirLibrary.openBook(id), second); await W(2500);
  const shelf = await share();
  await b.close();

  const fails = [];
  if (new Set(titles).size !== 1) fails.push(`시험 준비 실패 — 두 책의 제목이 달라요 (${titles.join(' / ')})`);
  if (!preview.hidden) fails.push(`① 초안 미리 읽기에 공유 버튼이 보여요 (보낸 책: ${preview.sent})`);
  if (shelf.sent !== second) fails.push(`② 두 번째 책(${second})을 펼쳤는데 ${shelf.sent} 이(가) 공유됐어요`);
  if (errs.length) fails.push('자바스크립트 오류: ' + errs.join(' | '));
  console.log(fails.length ? fails.join('\n') : '모두 통과 — 펼친 책을 공유해요');
  process.exit(fails.length ? 1 : 0);
})();
