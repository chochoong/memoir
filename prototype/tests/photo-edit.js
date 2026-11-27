const {chromium} = require('playwright');
/* 자서전 「사진 편집」 시험 (v1.16 · v1.17 서버 계약 9-C1 · v1.18 장 탭 · v1.24 PC 왼쪽 목차 / 휴대폰 알약 탭) — 업무지시서 6. 완료 기준(프론트 검수 체크리스트)을 그대로 따라간다. 예시 모드(?demo=1)
     node prototype/tests/photo-edit.js [pc|m] [사진 폴더]
   예시 서버가 서버 계약 9-C1(backend 86cd502 · POST · PATCH · DELETE /api/memoirs/saved/{id}/photos)을 흉내 낸다. 실제 서버 · 유료 API 는 부르지 않는다.
   실패 흉내: localStorage 'demo.failPhotoEdit' = POST | PATCH | DELETE → 그 요청 한 번이 503.
             'POST-after-save' → 저장은 되고 응답만 503 (다시 보내도 request_id 로 한 장만). 실패하면 끝 코드 1. */
const path = require('path'); const fs = require('fs'); const zlib = require('zlib');
const [,, which = 'pc', out = ''] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
if (out) fs.mkdirSync(out, {recursive: true});
function png(w, h, rgb) {
  const crc = (b) => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } let x = -1; for (const v of b) x = t[(x ^ v) & 255] ^ (x >>> 8); return (x ^ -1) >>> 0; };
  const chunk = (ty, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(ty), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.concat(Array(w).fill(Buffer.from(rgb)))]);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(Buffer.concat(Array(h).fill(row)))), chunk('IEND', Buffer.alloc(0))]);
}
const PICS = [{name: '1_빨강.png', mimeType: 'image/png', buffer: png(80, 60, [200, 60, 50])}, {name: '2_파랑.png', mimeType: 'image/png', buffer: png(60, 80, [50, 90, 200])}];

(async () => {
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const ctx = await b.newContext(which === 'm' ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}});
  const p = await ctx.newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message)); p.on('dialog', (d) => d.accept());
  const W = (ms) => p.waitForTimeout(ms);
  let n = 0; const shot = async (t, el) => { if (!out) return; const o = {path: path.join(out, `${which}_${String(++n).padStart(2, '0')}_${t}.jpg`), type: 'jpeg', quality: 85}; if (el) await p.locator(el).screenshot(o); else await p.screenshot(o); };
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  const go = async (h) => { await p.evaluate((x) => { location.hash = x; }, h); await W(900); };
  const screen = () => p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen);
  const login = async () => { await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500); await p.click('[data-login-google]'); await W(1600); };
  // 서버(예시) 상태 그대로: [{id, ch, para, order, origin, url}]
  const serverFigs = (id) => p.evaluate(async (id) => { const v = await window.Srv.call(`/memoirs/saved/${id}/illustrations`);
    return v.chapters.flatMap((c) => c.figures.map((f) => ({id: f.placement_id, ch: c.no, para: f.after_paragraph, order: f.display_order, origin: f.origin, url: f.url.split('?')[0]}))); }, id);
  const tab = async (ch) => { await p.locator(`.pe-tab[data-pe-tab="${ch}"]`).click(); await W(250); };   // 장 탭 (v1.18)
  const idle = async () => { for (let i = 0; i < 40 && await p.evaluate(() => document.getElementById('photo-edit').classList.contains('is-busy')); i++) await W(250); await W(300); };
  // 장 탭 줄은 장이 많으면 옆으로 밀어 보는 칸이라 빼고, 그 밖의 단추 · 사진이 화면 안에 있고 편집 화면이 옆으로 밀리지 않는지
  const noOverflow = () => p.evaluate(() => { const d = document.getElementById('photo-edit'); const body = d.querySelector('.pe-body');
    return body.scrollWidth <= body.clientWidth + 1 && [...d.querySelectorAll('button, .pe-fig, img')].filter((el) => !el.closest('.pe-tabs')).every((el) => { const r = el.getBoundingClientRect(); return !r.width || (r.right <= innerWidth + 1 && r.left >= -1); }); });

  // ── 준비: 엽서로 자서전 만들기 → 책장에 보관 → 펼치기 ──
  await p.goto(`file://${file}?demo=1`); await W(1300); await login();
  await go('records'); await p.click('#choose-style'); await W(600); await p.click('#choose-style'); await W(600);
  await p.click('[data-style="essay"]'); await p.click('#generate-draft');
  for (let i = 0; i < 40 && (await screen()) !== 'draft'; i++) await W(500);
  await W(1500);
  const id = await p.evaluate(() => state.savedMemoirId); // eslint-disable-line no-undef
  const draftBtn = p.locator('#edit-photos');
  if (which === 'm') await draftBtn.scrollIntoViewIfNeeded();
  check(await draftBtn.isVisible() && await draftBtn.isEnabled(), '[진입] 초안 화면에 「사진 편집」');
  await go('draft'); await p.click('#save-volume'); await W(5500);
  await p.click('[data-library-book]'); await W(4500);
  const readerBtn = p.locator('#ebook-unplaced');
  check(await readerBtn.isVisible() && /사진/.test(await readerBtn.innerText()), '[진입] 완성된 자서전(읽기 화면) 독서 메뉴에 「사진 편집」');
  const start = await serverFigs(id);
  const auto = start.find((f) => f.origin === 'auto');
  const chs = await p.evaluate(() => [...new Set(state.document.sections.map((s) => s.chapterNo))]); // eslint-disable-line no-undef
  check(!!auto && chs.length >= 2, `준비: 엽서 대표 사진(자동 배치) 1장 · 장 ${chs.length}개`);
  await readerBtn.click(); await W(1200);
  check(await p.locator('#photo-edit[open]').isVisible(), '[편집 진입] 편집 모드가 열린다');
  // 장 탭: 책의 장마다 하나 · 처음엔 1장 · 고른 장의 문단만 · 탭마다 「+ 사진 추가」가 그 장 문단 수만큼
  const tabInfo = await p.locator('.pe-tab').evaluateAll((xs) => xs.map((x) => ({no: Number(x.dataset.peTab), on: x.getAttribute('aria-selected') === 'true', text: x.innerText.replace(/\s+/g, ' ')})));
  const docCh = await p.evaluate(() => { const m = new Map(); state.document.sections.forEach((s) => { if (Number.isInteger(s.chapterNo)) m.set(s.chapterNo, (m.get(s.chapterNo) || 0) + 1); }); return [...m.entries()]; }); // eslint-disable-line no-undef
  check(JSON.stringify(tabInfo.map((t) => t.no)) === JSON.stringify(docCh.map(([no]) => no)), `[장 탭] 책의 장마다 탭 하나 (${tabInfo.map((t) => t.text).join(' / ')})`);
  check(tabInfo[0].on && tabInfo.filter((t) => t.on).length === 1, '[장 탭] 처음엔 1장 탭이 골라져 있다');
  // 화면 (v1.24): PC = 왼쪽 세로 목차 · 목차 맨 아래 「편집 마치기」 / 휴대폰 = 위 알약 탭 · 설명은 함께 스크롤 · 「편집 마치기」는 장 맨 끝. 이전 · 다음 장 단추 없음
  const L = await p.evaluate(() => {
    const d = document.getElementById('photo-edit'), q = (x) => d.querySelector(x), R = (e) => e.getBoundingClientRect(), cs = (e) => getComputedStyle(e);
    const shown = (e) => !!e && R(e).width > 0 && R(e).height > 0;
    const tabs = [...d.querySelectorAll('.pe-tab')], on = q('.pe-tab.is-on'), off = q('.pe-tab:not(.is-on)');
    const doneVis = [...d.querySelectorAll('.pe-done')].filter(shown);
    const side = q('.pe-tabbar'), body = q('.pe-body'), head = q('.pe-head'), intro = q('.pe-intro');
    return {
      vertical: tabs.length > 1 && R(tabs[1]).top >= R(tabs[0]).bottom - 1 && Math.abs(R(tabs[1]).left - R(tabs[0]).left) < 2,
      sideLeft: R(side).right <= R(body).left + 1,
      row: tabs.length > 1 && Math.abs(R(tabs[1]).top - R(tabs[0]).top) < 2,
      equal: tabs.length > 1 && Math.abs(R(tabs[0]).width - R(tabs[tabs.length - 1]).width) < 2,
      onBg: cs(on).backgroundColor, offBg: cs(off).backgroundColor, track: cs(q('.pe-tabs')).backgroundColor, onBar: cs(on).boxShadow,
      doneN: doneVis.length, doneInSide: doneVis.length === 1 && side.contains(doneVis[0]) && R(side).bottom - R(doneVis[0]).bottom < 40,
      doneInEnd: doneVis.length === 1 && !!doneVis[0].closest('.pe-end'),
      done: (() => { const x = cs(d.querySelector('.pe-done')); return {img: x.backgroundImage, bg: x.backgroundColor}; })(),
      headShown: shown(head), introShown: shown(intro), introInBody: !!intro && body.contains(intro),
      nav: d.querySelectorAll('.pe-chnav, .pe-body [data-pe-tab]').length,
      titles: [...d.querySelectorAll('.pe-tab-title')].some(shown),
      fit: q('.pe-tabs').scrollWidth <= q('.pe-tabs').clientWidth + 1,
      names: tabs.every((t) => /장 \S/.test(t.getAttribute('aria-label') || '')) };
  });
  check(L.done.img === 'none' && L.done.bg === 'rgb(245, 180, 32)', `[편집 마치기] 그라데이션 없이 평평한 노랑 #F5B420 (${L.done.img} · ${L.done.bg})`);
  check(L.nav === 0, '[화면] 이전 · 다음 장 단추가 없다');
  check(L.names, '[장 탭] 화면 읽기 프로그램에는 장 제목까지 읽힌다 (aria-label)');
  if (which === 'm') {
    check(L.row && L.equal && L.fit && !L.titles, '[휴대폰 · 알약 탭] 장이 한 줄에 같은 폭으로 · 제목은 빼고 옆으로 밀지 않아도 다 보임');
    check(L.onBg !== L.track && L.offBg !== L.onBg, `[휴대폰 · 알약 탭] 고른 장만 흰 알약 (${L.onBg} / 틀 ${L.track})`);
    check(!L.headShown && L.introShown && L.introInBody, '[휴대폰] 설명은 내용 맨 위에서 함께 스크롤된다');
    const end = await p.evaluate(() => { const b = document.querySelector('#photo-edit .pe-body'); const top0 = document.querySelector('#photo-edit .pe-intro').getBoundingClientRect().top; b.scrollTop = 300; const top1 = document.querySelector('#photo-edit .pe-intro').getBoundingClientRect().top; const tb = document.querySelector('#photo-edit .pe-tabbar').getBoundingClientRect().top; b.scrollTop = b.scrollHeight;
      const e = document.querySelector('#photo-edit .pe-end .pe-done').getBoundingClientRect(), br = b.getBoundingClientRect(); const r = {moved: top1 < top0 - 100, tabsTop: Math.round(tb), endVis: e.top >= br.top && e.bottom <= br.bottom + 1}; b.scrollTop = 0; return r; });
    check(end.moved && end.tabsTop <= 1, `[휴대폰] 내리면 설명은 올라가고 탭 줄은 맨 위에 그대로 (탭 위치 ${end.tabsTop}px)`);
    check(L.doneN === 1 && L.doneInEnd && end.endVis, '[휴대폰] 「편집 마치기」는 장 맨 끝에 (내려야 보임)');
  } else {
    check(L.vertical && L.sideLeft && L.titles, '[PC · 왼쪽 목차] 장이 왼쪽에 세로로 · 장 제목이 보인다');
    check(/245, 180, 32/.test(L.onBar), '[PC · 왼쪽 목차] 고른 장은 왼쪽 노란 막대');
    check(L.doneN === 1 && L.doneInSide, '[PC] 「편집 마치기」는 왼쪽 목차 맨 아래 하나');
    const g = await p.evaluate(() => { const h = document.querySelector('#photo-edit .pe-head').getBoundingClientRect(), t = document.querySelector('#photo-edit .pe-tabbar').getBoundingClientRect(); const b = document.querySelector('#photo-edit .pe-body'); b.scrollTop = 400; const t2 = document.querySelector('#photo-edit .pe-tabbar').getBoundingClientRect(); b.scrollTop = 0; return [Math.round(t.top - h.bottom), Math.round(t2.top - h.bottom)]; });
    check(g[0] === 0 && g[1] === 0, `[PC] 머리와 목차 사이 틈 없음 · 내려도 그대로 (${g.join('px / ')}px)`);
  }
  let slotOk = true, total = 0;
  for (const [no, n] of docCh) {
    await tab(no); total += n;
    const vis = await p.locator('[data-pe-add]').evaluateAll((xs) => xs.map((x) => Number(x.dataset.peAdd.split(':')[0])));
    if (vis.length !== n || vis.some((v) => v !== no)) slotOk = false;
  }
  check(slotOk, `[장 탭 · 추가 위치] 탭마다 그 장의 문단마다 「+ 사진 추가」 (모두 ${total}문단) · 읽기 화면과 같은 문단 기준`);
  await p.locator('.pe-tab').first().focus(); await p.keyboard.press('ArrowRight'); await W(250);
  check(await p.locator('.pe-tab').nth(1).getAttribute('aria-selected') === 'true', '[장 탭] 키보드 화살표로 다음 장');
  await tab(docCh[0][0]);
  // AI 그림이 있는 장으로
  const aiCh = start.find((f) => f.origin === 'ai');
  if (aiCh) await tab(aiCh.ch);
  check(!/교체/.test(await p.locator('#photo-edit').innerText()), '[체크 6] 「교체」 메뉴가 없다 (추가 · 이동 · 삭제만)');
  // 서버 결정: AI 삽화는 옮기거나 빼지 않는다 (origin ai · placement_id null)
  const aiFig = start.find((f) => f.origin === 'ai');
  check(!!aiFig && aiFig.id === null, '서버 계약: AI 삽화는 origin ai · placement_id null');
  check(await p.locator('.pe-fig.is-ai [data-pe-move], .pe-fig.is-ai [data-pe-del]').count() === 0 && await p.locator('.pe-fig.is-ai .pe-fixed').count() >= 1, 'AI 그림에는 이동 · 삭제 단추 대신 안내');
  check(await noOverflow(), '[체크 7] 편집 화면 단추 · 사진이 화면 밖으로 넘치지 않는다');
  await shot('편집모드');

  // ── 체크 1: 특정 문단 뒤 사진 2장 → 고른 순서대로 ──
  const tgt = {ch: chs[chs.length - 1], para: 0};
  await tab(tgt.ch);
  await p.locator(`[data-pe-add="${tgt.ch}:${tgt.para}"]`).scrollIntoViewIfNeeded();
  const [chooser] = await Promise.all([p.waitForEvent('filechooser'), p.locator(`[data-pe-add="${tgt.ch}:${tgt.para}"]`).click()]);
  await chooser.setFiles(PICS); await W(600);
  check(await p.locator('#photo-edit-sheet[open]').isVisible(), '미리보기 창이 열린다');
  check(/「\d+장 1번째 문단 아래」에 사진 2장/.test(await p.locator('#pe-sheet-title').innerText()), '미리보기에 「N장 1번째 문단 아래」 같은 쉬운 자리 말');
  await shot('미리보기');
  await p.click('#photo-edit-sheet [data-ps="go"]');
  check(await p.locator('#photo-edit-sheet [data-ps="go"]').isDisabled().catch(() => true), '[중복 방지] 넣는 동안 「넣기」를 다시 누를 수 없다');
  for (let i = 0; i < 40 && !(await p.locator('#photo-edit-sheet [data-ps="close"]:not([disabled])').count() && await p.locator('#photo-edit-sheet .pe-pre li.is-ok').count() === 2); i++) await W(250);
  await shot('넣은뒤');
  await p.click('#photo-edit-sheet [data-ps="close"]'); await idle();
  let now = await serverFigs(id);
  const added = now.filter((f) => f.origin === 'manual' && f.ch === tgt.ch && f.para === tgt.para).sort((a, c) => a.order - c.order);
  check(added.length === 2, '[체크 1] 지정한 문단 뒤에 사진 2장이 저장됐다');
  const addedUrls = added.map((f) => f.url);
  const ui = await p.locator(`.pe-para:has([data-pe-add="${tgt.ch}:${tgt.para}"]) .pe-fig img`).evaluateAll((xs) => xs.map((x) => x.alt));
  check(ui.length >= 2, '[체크 1] 편집 화면의 그 문단에 2장이 보인다');
  // 고른 순서 = 화면 순서 (빨강 80×60 이 먼저, 파랑 60×80 이 다음)
  const sizes = await p.evaluate(async (urls) => Promise.all(urls.map(async (u) => { const bl = await (await fetch(u)).blob(); const bm = await createImageBitmap(bl); return bm.width; })), addedUrls);
  check(sizes[0] === 80 && sizes[1] === 60, `[체크 1] 고른 순서대로 (첫째 가로 ${sizes[0]} · 둘째 가로 ${sizes[1]})`);

  // ── 체크 2: 다른 장의 특정 문단 뒤로 이동 → 중복 없음 ──
  const mv = added[0]; const dest = {ch: chs[0], para: 0};
  const oldCount = await p.locator(`.pe-para:has([data-pe-add="${tgt.ch}:${tgt.para}"]) .pe-fig`).count();
  await p.locator(`[data-pe-move="${mv.id}"]`).click(); await W(300);
  check(await p.locator('.pe-movebar').isVisible(), '이동: 옮길 자리를 고르라는 안내');
  await tab(dest.ch);
  check(await p.locator(`[data-pe-to="${dest.ch}:${dest.para}"]`).isEnabled() && await p.locator(`.pe-tab[data-pe-tab="${tgt.ch}"].is-from`).count() === 1, '[장 탭] 옮기는 중에 다른 장 탭으로 가서 자리를 고를 수 있다 (원래 장 탭 표시)');
  await shot('이동고르기');
  await p.locator(`[data-pe-to="${dest.ch}:${dest.para}"]`).click(); await idle();
  now = await serverFigs(id);
  check(now.filter((f) => f.url === mv.url).length === 1 && now.find((f) => f.url === mv.url).ch === dest.ch, '[체크 2] 다른 장으로 옮긴 사진이 한 번만, 새 자리에');
  await tab(tgt.ch);
  check(await p.locator(`.pe-para:has([data-pe-add="${tgt.ch}:${tgt.para}"]) .pe-fig`).count() === oldCount - 1 && !now.some((f) => f.url === mv.url && f.ch === tgt.ch), '[체크 2] 예전 자리에서는 사라졌다');

  // ── 체크 3: 엽서 대표 사진 삭제 → 자서전에서만 ──
  await tab(auto.ch);
  await p.locator(`[data-pe-del="${auto.id}"]`).scrollIntoViewIfNeeded();
  await p.locator(`[data-pe-del="${auto.id}"]`).click(); await W(400);
  check(/엽서와 사진 원본은 그대로/.test(await p.locator('#photo-edit-sheet').innerText()), '삭제 확인 창 (엽서는 그대로라는 안내)');
  await shot('삭제확인');
  await p.click('#photo-edit-sheet [data-ps="no"]'); await W(300);
  check((await serverFigs(id)).some((f) => f.id === auto.id), '삭제 확인에서 취소하면 그대로');
  await p.locator(`[data-pe-del="${auto.id}"]`).click(); await W(300);
  await p.click('#photo-edit-sheet [data-ps="yes"]'); await idle();
  now = await serverFigs(id);
  check(!now.some((f) => f.id === auto.id), '[체크 3] 엽서 대표 사진이 이 자서전에서 사라졌다');
  const pcPhoto = await p.evaluate((url) => { const db = JSON.parse(localStorage.getItem('memoir.demo.db')); return db.sessions.some((s) => s.photo_id && url.endsWith(s.photo_id) && s.postcard); }, auto.url);
  check(pcPhoto, '[체크 3] 엽서에는 사진이 그대로 남아 있다');

  // ── 체크 5: 실패하면 성공 안내 없이 원래 화면 ──
  const before = JSON.stringify(await serverFigs(id));
  await p.evaluate(() => localStorage.setItem('demo.failPhotoEdit', 'PATCH'));
  const mv2 = added[1];
  await p.evaluate(() => { document.getElementById('toast').hidden = true; });
  await tab(tgt.ch);
  await p.locator(`[data-pe-move="${mv2.id}"]`).click(); await W(200);
  await tab(chs[0]);
  await p.locator(`[data-pe-to="${chs[0]}:0"]`).click(); await idle();
  check(/실패했어요/.test(await p.locator('.pe-banner').innerText()) && await p.locator('.pe-banner [data-pe="retry"]').isVisible(), '[체크 5] 이동 실패: 오류 문구 + 다시 시도');
  check(JSON.stringify(await serverFigs(id)) === before, '[체크 5] 실패하면 서버 상태 그대로');
  check(!(await p.locator('#toast').isVisible()) || !/옮겼어요/.test(await p.locator('#toast').innerText()), '[체크 5] 실패를 성공으로 알리지 않는다');
  await shot('실패');
  await p.click('.pe-banner [data-pe="retry"]'); await idle();
  check((await serverFigs(id)).find((f) => f.id === mv2.id).ch === chs[0], '다시 시도하면 옮겨진다');
  // 여러 장 중 일부 실패
  await p.evaluate(() => localStorage.setItem('demo.failPhotoEdit', 'POST'));
  await tab(tgt.ch);
  const [ch2] = await Promise.all([p.waitForEvent('filechooser'), p.locator(`[data-pe-add="${tgt.ch}:${tgt.para}"]`).click()]);
  await ch2.setFiles(PICS); await W(500); await p.click('#photo-edit-sheet [data-ps="go"]');
  for (let i = 0; i < 80 && !(await p.locator('#photo-edit-sheet [data-ps="retry"]').count()); i++) await W(250);
  check(/2장 가운데 1장을 넣었어요. 1장은 넣지 못했어요/.test(await p.locator('#photo-edit-sheet').innerText()), '[체크 5] 여러 장 중 일부 실패를 분명히 알린다');
  await shot('일부실패');
  await p.click('#photo-edit-sheet [data-ps="retry"]');
  for (let i = 0; i < 80 && (await p.locator('#photo-edit-sheet .pe-pre li.is-up, #photo-edit-sheet .pe-pre li.is-bad').count() || await p.locator('#photo-edit-sheet .pe-pre li.is-ok').count() < 2); i++) await W(250);
  const okN = await p.locator('#photo-edit-sheet .pe-pre li.is-ok').count();
  check(okN === 2, '못 넣은 사진만 다시 넣기' + (okN === 2 ? '' : ` — ${(await p.locator('#photo-edit-sheet').innerText()).replace(/\s+/g, ' ')} / 배너: ${await p.locator('.pe-banner').innerText()}`));
  await p.click('#photo-edit-sheet [data-ps="close"]'); await idle();
  // 다시 넣은 첫 사진(빨강)이 둘째(파랑) 앞에 — 고른 순서 그대로 (display_order)
  const batch = (await serverFigs(id)).filter((f) => f.origin === 'manual' && f.ch === tgt.ch && f.para === tgt.para && !addedUrls.includes(f.url));
  const bw = await p.evaluate(async (urls) => Promise.all(urls.map(async (u) => (await createImageBitmap(await (await fetch(u)).blob())).width)), batch.map((f) => f.url));
  check(batch.length === 2 && bw[0] === 80 && bw[1] === 60, `[체크 5] 실패한 사진을 다시 넣어도 고른 순서 그대로 (가로 ${bw.join(' · ')})`);
  // 응답이 끊긴 경우: 저장은 됐는데 503 → 다시 넣기 → request_id 덕분에 한 장만
  const cntBefore = (await serverFigs(id)).filter((f) => f.origin === 'manual').length;
  await p.evaluate(() => localStorage.setItem('demo.failPhotoEdit', 'POST-after-save'));
  await tab(chs[0]);
  const [ch3] = await Promise.all([p.waitForEvent('filechooser'), p.locator(`[data-pe-add="${chs[0]}:0"]`).click()]);
  await ch3.setFiles([PICS[0]]); await W(500); await p.click('#photo-edit-sheet [data-ps="go"]');
  for (let i = 0; i < 80 && !(await p.locator('#photo-edit-sheet [data-ps="retry"]').count()); i++) await W(250);
  await p.click('#photo-edit-sheet [data-ps="retry"]');
  for (let i = 0; i < 80 && await p.locator('#photo-edit-sheet .pe-pre li.is-ok').count() < 1; i++) await W(250);
  await p.click('#photo-edit-sheet [data-ps="close"]'); await idle();
  check((await serverFigs(id)).filter((f) => f.origin === 'manual').length === cntBefore + 1, '[중복 방지] 응답이 끊겨 다시 보내도 한 장만 들어간다 (request_id)');
  await p.locator('#photo-edit [data-pe="close"]:visible').first().click(); await W(600);

  // ── 체크 4: 새로고침 · 로그아웃 후 다시 로그인해도 그대로 ──
  const saved = JSON.stringify(await serverFigs(id));
  const viewBefore = JSON.stringify(await p.evaluate((id) => window.SrvLibrary.figures(id, (window.MemoirLibrary.getBook(id) || {}).document), id));
  await p.reload(); await W(2500);
  check(JSON.stringify(await serverFigs(id)) === saved, '[체크 4] 새로고침해도 위치 · 순서 · 삭제가 그대로');
  await p.evaluate(() => window.Srv.api.authLogout()); await p.reload(); await W(2000); await login();
  await go('library'); await W(1500); await p.click('[data-library-book]'); await W(4500);
  check(JSON.stringify(await serverFigs(id)) === saved, '[체크 4] 로그아웃 후 다시 로그인해도 그대로');
  const viewAfter = JSON.stringify(await p.evaluate((id) => window.SrvLibrary.figures(id, (window.MemoirLibrary.getBook(id) || {}).document), id));
  check(viewAfter === viewBefore, '[체크 4] 읽기 화면의 그림 자리 · 순서도 그대로');
  // ── 체크 8: PDF 가 쓰는 그림 목록(SrvLibrary.figures)이 서버 순서와 같다 ──
  const pdfOrder = await p.evaluate((id) => { const d = window.MemoirLibrary.getBook(id).document; const at = window.SrvLibrary.figures(id, d);
    return Object.entries(at).sort((a, c) => a[0] - c[0]).flatMap(([i, fs]) => fs.map((f) => [d.sections[i].chapterNo, d.sections[i].paragraphIndex, f.url.split('?')[0]])); }, id);
  // 서버가 정렬해 준 차례 그대로 (장 → 문단 → 같은 문단은 사진 display_order · AI 삽화는 사진 뒤). 화면 · PDF 는 문단 번호 순으로 같은 배열을 쓴다
  const srvOrder = JSON.parse(saved).map((f, k) => [f.ch, f.para, f.url, k]).sort((a, c) => a[0] - c[0] || a[1] - c[1] || a[3] - c[3]).map((x) => x.slice(0, 3));
  check(JSON.stringify(pdfOrder) === JSON.stringify(srvOrder), '[체크 8] PDF · 읽기 화면에 들어가는 그림 순서 = 서버 순서');
  await shot('읽기화면');

  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(which, fail.length ? `실패 ${fail.length}` : '모두 통과');
  process.exit(fail.length ? 1 : 0);
})();
