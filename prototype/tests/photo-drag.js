const {chromium} = require('playwright');
/* 「사진 편집」 끌어서 옮기기 시험 (v1.21 · v1.22 탭에 놓기 · 되돌리기) — 예시 모드(?demo=1&unplaced=1)
     node prototype/tests/photo-drag.js [pc|m] [사진 폴더]
   pc: 마우스로 사진을 끈다.  m: 휴대폰 크기에서 손가락(터치)으로 「끌기」 손잡이를 끈다.
   · 같은 문단 안 차례 바꾸기 (다른 사진 왼쪽 절반에 놓으면 그 앞)
   · 장 탭에 잠깐 대고 있으면 그 장이 열리고, 그 장 문단에 놓기
   · 넣지 못한 사진을 끌어 문단에 넣기
   · (v1.22) 장 탭 위에서 손을 떼면 그 장 1번째 문단 아래 맨 앞 → 그 장이 열리고 사진 강조 · 「되돌리기」로 원래 자리 · 이미 맨 앞이면 요청 없음
   · 제자리 · Esc 로 그만두기는 서버에 아무것도 보내지 않음
   · AI 그림은 끌 수 없음 · 손가락으로 사진 위(손잡이 밖)를 밀면 끌지 않고 화면이 움직임
   서버 순서는 예시 서버(9-C1 흉내)에서 그대로 읽어 확인한다. 실패하면 끝 코드 1. */
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
const PICS = [{name: '1_빨강.png', mimeType: 'image/png', buffer: png(80, 60, [200, 60, 50])}, {name: '2_파랑.png', mimeType: 'image/png', buffer: png(60, 80, [50, 90, 200])}, {name: '3_초록.png', mimeType: 'image/png', buffer: png(80, 60, [60, 160, 80])}];

(async () => {
  const touch = which === 'm';
  const b = await chromium.launch({args: ['--allow-file-access-from-files']});
  const ctx = await b.newContext(touch ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}});
  const p = await ctx.newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const cdp = await ctx.newCDPSession(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const W = (ms) => p.waitForTimeout(ms);
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  let n = 0; const shot = async (t) => { if (out) await p.screenshot({path: path.join(out, `${which}_drag_${String(++n).padStart(2, '0')}_${t}.jpg`), type: 'jpeg', quality: 85}); };
  const go = async (h) => { await p.evaluate((x) => { location.hash = x; }, h); await W(900); };
  const idle = async () => { for (let i = 0; i < 40 && await p.evaluate(() => document.getElementById('photo-edit').classList.contains('is-busy')); i++) await W(250); await W(400); };
  const serverFigs = (id) => p.evaluate(async (id) => { const v = await window.Srv.call(`/memoirs/saved/${id}/illustrations`);
    return {figs: v.chapters.flatMap((c) => c.figures.map((f) => ({id: f.placement_id, ch: c.no, para: f.after_paragraph, order: f.display_order, origin: f.origin, photo: f.photo_id}))), unplaced: (v.unplaced_photos || []).map((u) => u.photo_id)}; }, id);
  // 서버로 가는 사진 편집 요청(넣기 · 옮기기 · 빼기) 세기
  const countCalls = () => p.evaluate(() => { const a = window.Srv.api; window.__peCalls = 0; ['memoirPhotoAdd', 'memoirPhotoMove', 'memoirPhotoDelete'].forEach((k) => { const f = a[k]; a[k] = function () { window.__peCalls++; return f.apply(this, arguments); }; }); });
  const calls = () => p.evaluate(() => window.__peCalls);

  // ── 손 움직임: 마우스 / 터치 ──
  const center = (r) => ({x: r.x + r.width / 2, y: r.y + r.height / 2});
  const tp = (type, x, y) => cdp.send('Input.dispatchTouchEvent', {type, touchPoints: type === 'touchEnd' ? [] : [{x, y, id: 1}]});
  let cur = {x: 0, y: 0};
  const press = async (x, y) => { cur = {x, y}; if (touch) await tp('touchStart', x, y); else { await p.mouse.move(x, y); await p.mouse.down(); } };
  const moveTo = async (x, y, steps = 8) => { for (let i = 1; i <= steps; i++) { const nx = cur.x + (x - cur.x) * i / steps, ny = cur.y + (y - cur.y) * i / steps; if (touch) await tp('touchMove', nx, ny); else await p.mouse.move(nx, ny); await W(16); } cur = {x, y}; };
  const release = async () => { if (touch) await tp('touchEnd'); else await p.mouse.up(); await W(200); };
  // 끄는 곳(사진: 마우스는 사진 가운데, 손가락은 「끌기」 손잡이)
  const grabPoint = async (sel) => { const el = p.locator(sel).first(); await el.scrollIntoViewIfNeeded(); await W(150);
    const r = await (touch ? el.locator('.pe-grip') : el.locator('.pe-thumb')).boundingBox(); return center(r); };
  // 놓을 곳이 창 밖이면 가장자리에 대고 저절로 밀리기를 기다린다
  async function dragTo(srcSel, target, {hold = 0, release: rel = true, direct = false} = {}) {
    const s = await grabPoint(srcSel); await press(s.x, s.y); await moveTo(s.x + 12, s.y + 14, 3);
    for (let i = 0; i < 60; i++) {
      const t = await p.evaluate(target.f, target.a);
      const body = await p.locator('#photo-edit .pe-body').boundingBox();
      if (!t) { await W(100); continue; }
      if (direct) { await moveTo(t.x, t.y); break; }
      const top = body.y;   // v1.23~: 장 탭 · 목차는 스크롤 칸 밖
      const st = await p.locator('#photo-edit .pe-body').evaluate((e) => [e.scrollTop, e.scrollHeight - e.clientHeight]);
      if ((t.y < top + 80 && st[0] <= 0) || (t.y > body.y + body.height - 80 && st[0] >= st[1] - 1)) { await moveTo(t.x, t.y); break; }   // 더 밀 수 없으면 그 자리에
      if (t.y < top + 80) await moveTo(body.x + body.width / 2, top + 20, 4);
      else if (t.y > body.y + body.height - 80) await moveTo(body.x + body.width / 2, body.y + body.height - 20, 4);
      else { await moveTo(t.x, t.y); break; }
      await W(250);
    }
    // 가는 길에 가장자리 띠를 지나며 화면이 밀렸으면 놓을 곳이 움직였다 — 다시 재서 따라간다
    for (let i = 0; i < 4 && !direct; i++) { await W(150); const t = await p.evaluate(target.f, target.a); if (!t || Math.hypot(t.x - cur.x, t.y - cur.y) < 3) break; await moveTo(t.x, t.y, 3); }
    if (hold) await W(hold);
    if (rel) await release();
  }
  // 그 사진(placement)의 왼쪽 위 — 「그 앞」에 놓는 자리
  const at = (f, a) => ({f, a});   // 페이지 안에서 잴 함수 + 값
  const beforeFig = (pid) => at((pid) => { const e = document.querySelector(`#photo-edit .pe-fig[data-pe-fid="${pid}"]`); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + Math.min(30, r.width / 4), y: r.top + 30}; }, pid);
  // 그 문단의 「+ 사진 추가」 칸 — 그 문단 맨 끝
  const paraEnd = (ch, para) => at(([ch, para]) => { const e = document.querySelector(`#photo-edit [data-pe-para="${ch}:${para}"] .pe-slot`); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }, [ch, para]);
  const tabAt = (ch) => at((ch) => { const e = document.querySelector(`#photo-edit .pe-tab[data-pe-tab="${ch}"]`); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }, ch);
  const tab = async (ch) => { await p.locator(`#photo-edit .pe-tab[data-pe-tab="${ch}"]`).click(); await W(300); };
  const photosAt = (figs, ch, para) => figs.filter((f) => f.ch === ch && f.para === para && f.origin !== 'ai').map((f) => f.id);

  // ── 준비: 자서전 만들기 → 읽기 화면 → 사진 편집 ──
  await p.goto(`file://${file}?demo=1&unplaced=1`); await W(1300);
  await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(500);
  await p.click('[data-login-google]'); await W(1600);
  await go('records'); await p.click('#choose-style'); await W(600); await p.click('#choose-style'); await W(600);
  await p.click('[data-style="essay"]'); await p.click('#generate-draft');
  for (let i = 0; i < 40 && (await p.evaluate(() => document.querySelector('[data-screen]:not([hidden])')?.dataset.screen)) !== 'draft'; i++) await W(500);
  await W(1200);
  const id = await p.evaluate(() => state.savedMemoirId); // eslint-disable-line no-undef
  await go('draft'); await p.click('#save-volume'); await W(5500);
  await p.click('[data-library-book]'); await W(4500);
  await p.evaluate(() => { const t = document.getElementById('toast'); if (t) t.hidden = true; });
  await p.locator('#ebook-unplaced').click(); await W(1200);
  check(await p.locator('#photo-edit[open]').isVisible(), '준비: 사진 편집 창');
  const chs = await p.locator('#photo-edit .pe-tab').evaluateAll((xs) => xs.map((x) => Number(x.dataset.peTab)));
  check(chs.length >= 2, `준비: 장 ${chs.length}개`);
  const C1 = chs[0], C2 = chs[1];
  // 1장 1번째 문단에 사진 3장 넣기 (빨강 · 파랑 · 초록)
  const [chooser] = await Promise.all([p.waitForEvent('filechooser'), p.locator(`[data-pe-add="${C1}:0"]`).click()]);
  await chooser.setFiles(PICS); await W(500); await p.click('#photo-edit-sheet [data-ps="go"]');
  for (let i = 0; i < 40 && !(await p.locator('#photo-edit-sheet [data-ps="close"]:not([disabled])').count()); i++) await W(250);
  await p.click('#photo-edit-sheet [data-ps="close"]'); await idle();
  await countCalls();
  let s0 = await serverFigs(id);
  const before = photosAt(s0.figs, C1, 0);
  check(before.length >= 3, `준비: ${C1}장 1번째 문단 아래 사진 ${before.length}장 (${before.join(', ')})`);

  // ── 끌 수 있는 것 · 없는 것 ──
  const ui = await p.evaluate(() => ({ai: [...document.querySelectorAll('#photo-edit .pe-fig.is-ai')].map((f) => !!f.querySelector('[data-pe-drag]')),
    photos: [...document.querySelectorAll('#photo-edit .pe-fig[data-pe-fid]')].every((f) => f.querySelector('[data-pe-drag] .pe-grip')),
    unplaced: [...document.querySelectorAll('#photo-edit .pe-unplaced .pe-fig')].every((f) => f.querySelector('.pe-grip')),
    help: document.querySelector('#photo-edit .pe-help').textContent}));
  check(ui.photos && ui.unplaced, '[끌기] 모든 사진(자동 · 넣은 사진 · 넣지 못한 사진)에 「끌기」 손잡이');
  check(ui.ai.every((x) => !x), `[끌기] AI 그림은 끌 수 없다 (AI 그림 ${ui.ai.length}장)`);
  check(/끌어서/.test(ui.help), '[끌기] 맨 위 안내에 「끌어서 옮기기」');
  const gs = await p.evaluate(() => { const g = document.querySelector('#photo-edit .pe-grip'); const r = g.getBoundingClientRect(); return {h: r.height, ta: getComputedStyle(g).touchAction}; });
  check(gs.h >= 40 && gs.ta === 'none', `[끌기] 손잡이 높이 ${Math.round(gs.h)}px · 손가락으로 끌 때 화면이 밀리지 않음 (touch-action ${gs.ta})`);

  // ── ① 같은 문단 안: 맨 뒤 사진을 맨 앞 사진 앞으로 ──
  const last = before[before.length - 1], first = before[0];
  let c0 = await calls();
  const s = await grabPoint(`#photo-edit .pe-fig[data-pe-fid="${last}"]`); await press(s.x, s.y); await moveTo(s.x + 12, s.y + 14, 3);
  for (let i = 0; i < 30; i++) { const t = await p.evaluate(beforeFig(first).f, first); const body = await p.locator('#photo-edit .pe-body').boundingBox();
    const top = body.y;
    if (t && t.y > top + 80) { await moveTo(t.x, t.y); break; } await moveTo(body.x + body.width / 2, top + 20, 3); await W(250); }
  await W(200);
  const mark = await p.evaluate(() => { const m = document.querySelector('#photo-edit .pe-drop-mark'); return m ? m.textContent : ''; });
  const ghost = await p.locator('#photo-edit .pe-ghost').count();
  check(ghost === 1 && /1번째/.test(mark), `[끄는 중] 손을 따라오는 사진 + 놓을 자리 표시 「${mark}」`);
  await shot('1_끄는중');
  await release(); await idle();
  let s1 = await serverFigs(id);
  let now = photosAt(s1.figs, C1, 0);
  check(now[0] === last && now.length === before.length && JSON.stringify(now.slice(1)) === JSON.stringify(before.slice(0, -1)), `① 같은 문단 안 차례: 맨 뒤 사진 → 맨 앞 (${now.join(', ')}) · 요청 ${await calls() - c0}번`);
  const shown = await p.locator(`#photo-edit [data-pe-para="${C1}:0"] .pe-fig[data-pe-fid]`).evaluateAll((xs) => xs.map((x) => x.dataset.peFid));
  check(JSON.stringify(shown) === JSON.stringify(now), '① 화면 차례 = 서버 차례');

  // ── ② 가운데로: 맨 앞 사진을 2번째와 3번째 사이로 (틈이 없으면 차례를 다시 매긴다) ──
  c0 = await calls();
  const mid = now[2];
  await dragTo(`#photo-edit .pe-fig[data-pe-fid="${now[0]}"]`, beforeFig(mid)); await idle();
  s1 = await serverFigs(id);
  const want2 = [now[1], now[0], ...now.slice(2)];
  now = photosAt(s1.figs, C1, 0);
  check(JSON.stringify(now) === JSON.stringify(want2), `② 가운데 자리로 (${now.join(', ')}) · 요청 ${await calls() - c0}번`);

  // ── ③ 제자리에 놓기 · Esc 로 그만두기 → 서버 요청 없음 ──
  c0 = await calls();
  const nextOf = now[now.indexOf(now[1]) + 1];
  await dragTo(`#photo-edit .pe-fig[data-pe-fid="${now[1]}"]`, beforeFig(nextOf)); await idle();
  check(await calls() === c0 && JSON.stringify(photosAt((await serverFigs(id)).figs, C1, 0)) === JSON.stringify(now), '③ 제자리에 놓으면 아무것도 바뀌지 않는다 (요청 0)');
  if (!touch) {
    await dragTo(`#photo-edit .pe-fig[data-pe-fid="${now[0]}"]`, paraEnd(C1, 1), {release: false});
    await p.keyboard.press('Escape'); await W(200); await p.mouse.up(); await idle();
    check(await calls() === c0 && await p.locator('#photo-edit[open]').isVisible() && !await p.locator('#photo-edit .pe-ghost').count(), '③ 끄는 중 Esc → 그만두고 창은 그대로 (요청 0)');
  }

  // ── ④ 다른 장으로: 장 탭에 대고 기다리면 그 장이 열린다 → 그 장 1번째 문단 끝에 놓기 ──
  c0 = await calls();
  const mover = now[now.length - 1];
  await dragTo(`#photo-edit .pe-fig[data-pe-fid="${mover}"]`, tabAt(C2), {hold: 900, release: false, direct: true});
  const opened = await p.evaluate(() => Number(document.querySelector('#photo-edit .pe-tab.is-on').dataset.peTab));
  check(opened === C2, `④ 끄는 중 ${C2}장 탭에 잠깐 대면 ${C2}장이 열린다 (지금 ${opened}장)`);
  await shot('2_장탭');
  const t4 = await p.evaluate(paraEnd(C2, 0).f, [C2, 0]); const bd = await p.locator('#photo-edit .pe-body').boundingBox();
  check(t4 && t4.y > bd.y && t4.y < bd.y + bd.height, '④ 열린 장의 첫 문단이 바로 보인다');
  await moveTo(t4.x, t4.y); await W(200); await release(); await idle();
  s1 = await serverFigs(id);
  const moved = s1.figs.find((f) => f.id === mover);
  const c2p = photosAt(s1.figs, C2, 0);
  check(moved && moved.ch === C2 && moved.para === 0 && c2p[c2p.length - 1] === mover, `④ ${C2}장 1번째 문단 아래 맨 끝으로 옮겨짐 (요청 ${await calls() - c0}번)`);
  check(await p.locator(`#photo-edit .pe-tab[data-pe-tab="${C2}"].is-on`).count() === 1, '④ 옮긴 뒤 그 장을 보고 있다');

  // ── ⑤ 넣지 못한 사진을 끌어 넣기 ──
  const un0 = s1.unplaced;
  check(un0.length >= 1, `준비: 넣을 수 있는 넣지 못한 사진 ${un0.length}장`);
  if (un0.length) {
    c0 = await calls();
    await p.locator('#photo-edit .pe-body').evaluate((e) => { e.scrollTop = 0; });
    const uid = (await p.locator('#photo-edit .pe-unplaced .pe-fig [data-pe-drag]').first().getAttribute('data-pe-drag')).slice(2);
    await dragTo('#photo-edit .pe-unplaced .pe-fig', paraEnd(C2, 1)); await idle();
    const s5 = await serverFigs(id);
    const put = s5.figs.find((f) => f.photo === uid);
    check(put && put.ch === C2 && put.para === 1 && !s5.unplaced.includes(uid), `⑤ 넣지 못한 사진을 끌어 「${C2}장 2번째 문단 아래」에 넣음 (요청 ${await calls() - c0}번)`);
    await shot('3_넣은뒤');
  }

  // ── ⑦ 탭에 놓기 (v1.22): 장 탭 위에서 바로 손을 떼면 그 장 「1번째 문단 아래 맨 앞」 → 강조 · 되돌리기 ──
  const C3 = chs[2] || C2;
  await tab(C1);
  let s7 = await serverFigs(id);
  const src = photosAt(s7.figs, C1, 0)[0];
  const orig = s7.figs.find((f) => f.id === src), c1Before = photosAt(s7.figs, C1, 0);
  const firstPara = await p.evaluate((no) => Math.min(...state.document.sections.filter((x) => x.chapterNo === no).map((x) => x.paragraphIndex)), C3); // eslint-disable-line no-undef
  c0 = await calls();
  await dragTo(`#photo-edit .pe-fig[data-pe-fid="${src}"]`, tabAt(C3), {release: false, direct: true});
  // 안내: PC 는 끄는 사진 밑 말풍선, 휴대폰은 커진 탭 줄 위 글줄 (v1.24)
  const tip = await p.evaluate(() => { const d = document.getElementById('photo-edit'); if (d.classList.contains('is-overtab')) return d.querySelector('.pe-tabbar').dataset.msg || ''; const t = d.querySelector('.pe-ghost-tip'); return t && !t.hidden ? t.textContent : ''; });
  if (touch) {
    const grown = await p.evaluate(() => { const d = document.getElementById('photo-edit'); const t = [...d.querySelectorAll('.pe-tab')]; const sp = d.querySelector('.pe-tab.is-spring'); const g = d.querySelector('.pe-ghost').getBoundingClientRect(), tb = d.querySelector('.pe-tabs').getBoundingClientRect();
      return {solid: t.filter((x) => !x.classList.contains('is-on') && !x.classList.contains('is-spring')).every((x) => getComputedStyle(x).borderTopStyle === 'solid'), h: Math.round(t[0].getBoundingClientRect().height), spring: !!sp && getComputedStyle(sp).transform !== 'none', ghostBelow: g.top >= tb.bottom - 4}; });
    check(grown.solid, '⑦ [휴대폰] 끄는 동안 고르지 않은 탭은 실선 테두리 (v1.26)');
    check(grown.h >= 80 && grown.spring && grown.ghostBelow, `⑦ [휴대폰] 끄는 동안 탭이 커지고(${grown.h}px) 대고 있는 탭은 더 크게 · 끄는 사진은 탭 아래로`);
  }
  check(new RegExp(`${C3}장 맨 앞`).test(tip), `⑦ 탭 위에서 「${tip}」 안내`);
  await shot('4_탭위');
  await release(); await idle();
  s7 = await serverFigs(id);
  const m7 = s7.figs.find((f) => f.id === src);
  check(m7 && m7.ch === C3 && m7.para === firstPara && photosAt(s7.figs, C3, firstPara)[0] === src, `⑦ ${C3}장 탭에 놓으면 「${C3}장 1번째 문단 아래」 맨 앞 (요청 ${await calls() - c0}번)`);
  const after7 = await p.evaluate((pid) => ({tab: Number(document.querySelector('#photo-edit .pe-tab.is-on').dataset.peTab), just: !!document.querySelector(`#photo-edit .pe-fig.is-just[data-pe-fid="${pid}"]`),
    vis: (() => { const e = document.querySelector(`#photo-edit .pe-fig[data-pe-fid="${pid}"]`); const b = document.querySelector('#photo-edit .pe-body').getBoundingClientRect(); if (!e) return false; const r = e.getBoundingClientRect(); return r.bottom > b.top && r.top < b.bottom; })(),
    bar: (() => { const u = document.querySelector('#photo-edit .pe-undo'); return u.hidden ? '' : u.innerText; })()}), src);
  check(after7.tab === C3 && after7.just && after7.vis, `⑦ ${C3}장이 열리고 옮긴 사진이 노랗게 · 화면 안에 보인다`);
  check(/되돌리기/.test(after7.bar) && /맨 앞/.test(after7.bar), `⑦ 아래 띠 「${after7.bar.replace(/\s+/g, ' ')}」`);
  await shot('5_탭에놓은뒤');
  // ⑧ 되돌리기 → 원래 장 · 문단 · 차례
  c0 = await calls();
  await p.click('#photo-edit [data-pe="undo"]'); await idle();
  const s8 = await serverFigs(id);
  const m8 = s8.figs.find((f) => f.id === src);
  check(m8 && m8.ch === orig.ch && m8.para === orig.para && JSON.stringify(photosAt(s8.figs, C1, 0)) === JSON.stringify(c1Before), `⑧ 「되돌리기」로 원래 자리 · 차례 (${photosAt(s8.figs, C1, 0).join(', ')}) · 요청 ${await calls() - c0}번`);
  check(await p.evaluate(() => Number(document.querySelector('#photo-edit .pe-tab.is-on').dataset.peTab)) === C1, `⑧ 되돌린 뒤 ${C1}장을 보여 준다`);
  // ⑨ 이미 그 장 맨 앞인 사진을 그 장 탭에 놓으면 요청 없이 알림만
  c0 = await calls();
  await dragTo(`#photo-edit .pe-fig[data-pe-fid="${src}"]`, tabAt(C1), {direct: true}); await idle();
  const bar9 = await p.evaluate(() => { const u = document.querySelector('#photo-edit .pe-undo'); return u.hidden ? '' : u.innerText; });
  check(await calls() === c0 && /이미/.test(bar9), `⑨ 이미 맨 앞이면 요청 0 · 「${bar9.replace(/\s+/g, ' ')}」`);

  // ── ⑥ 손가락: 사진 위(손잡이 밖)를 밀면 끌지 않고 화면이 움직인다 ──
  if (touch) {
    c0 = await calls();
    await p.locator('#photo-edit .pe-body').evaluate((e) => { e.scrollTop = 0; });
    const th = await p.locator('#photo-edit .pe-fig[data-pe-fid] .pe-thumb img').first().boundingBox();
    await press(th.x + th.width * 0.7, th.y + th.height * 0.8); await moveTo(th.x + th.width * 0.7, th.y + th.height * 0.8 - 40, 4);
    const g = await p.locator('#photo-edit .pe-ghost').count(); await release(); await idle();
    check(g === 0 && await calls() === c0, '⑥ 손가락으로 사진 위(손잡이 밖)를 밀면 끌기가 시작되지 않는다');
  }
  // 「이동」 단추도 그대로
  check(await p.locator('#photo-edit [data-pe-move]').first().isEnabled(), '「이동」 단추(키보드 · 화면 읽기용)는 그대로 쓸 수 있다');
  const ov = await p.evaluate(() => { const b = document.querySelector('#photo-edit .pe-body'); return b.scrollWidth <= b.clientWidth + 1; });
  check(ov, '편집 화면이 옆으로 밀리지 않는다');
  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(fail.length ? `${which} 실패 ${fail.length}` : `${which} 모두 통과`);
  process.exit(fail.length ? 1 : 0);
})();
