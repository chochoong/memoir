const {chromium} = require('playwright');
/* 가족 음성편지 시험 (v1.27) — 업무지시서 「가족 음성편지」(11/26) 완료 기준 · 서버 계약 10-C1 (develop 1dffd3b) 을 따라간다. 예시 모드.
     node prototype/tests/voice-letter.js [pc|m] [사진 폴더]
   가짜 마이크(크롬 --use-fake-device-for-media-stream)로 실제 MediaRecorder 녹음을 한다. 실제 서버 · 유료 API 는 부르지 않는다.
   ?voiceMax=4 (예시 모드 전용) 로 5분 자동 종료를 4초로 줄여 본다. 실패 흉내는 localStorage 'demo.failVoice'. 실패하면 끝 코드 1. */
const path = require('path'); const fs = require('fs');
const [,, which = 'pc', out = ''] = process.argv;
const file = process.env.FILE || path.resolve(__dirname, '..', 'index.html');
if (out) fs.mkdirSync(out, {recursive: true});
const mobile = which === 'm';
const ctxOpt = (perm) => Object.assign(mobile ? {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true} : {viewport: {width: 1366, height: 900}}, perm ? {permissions: ['microphone']} : {});

(async () => {
  const fail = []; const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(ok ? 'ok  ' : 'FAIL', msg); };
  // ── 마이크 권한 거부 (허락 창에서 「차단」) ──
  {
    const b = await chromium.launch({args: ['--allow-file-access-from-files', '--use-fake-device-for-media-stream']});
    const p = await (await b.newContext(ctxOpt(false))).newPage();
    if (process.env.ROUTE) require(process.env.ROUTE)(p);
    await p.goto(`file://${file}?demo=1`); await p.waitForTimeout(1200);
    await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await p.waitForTimeout(400);
    await p.click('[data-login-google]'); await p.waitForTimeout(1500);
    await p.evaluate(() => { location.hash = 'records'; }); await p.waitForTimeout(800);
    await p.click('#choose-style'); await p.waitForTimeout(500); await p.click('#choose-style'); await p.waitForTimeout(500);
    await p.click('[data-style="essay"]'); await p.click('#generate-draft'); await p.waitForTimeout(800);
    await p.click('#generation-dialog [data-vl="start"]'); await p.waitForTimeout(1500);
    const t = await p.locator('#generation-dialog .vl-box').innerText();
    const ph = await p.evaluate(() => document.querySelector('#generation-dialog .vl-box').dataset.phase);
    check(ph === 'denied' && !/녹음 중/.test(t) && /허락|허용/.test(t) && /다시 시도/.test(t), `[권한 거부] 「녹음 중」으로 보이지 않고 권한 안내 + 다시 시도 (${ph})`);
    await b.close();
  }

  const b = await chromium.launch({args: ['--allow-file-access-from-files', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']});
  const ctx = await b.newContext(ctxOpt(true));
  const p = await ctx.newPage();
  if (process.env.ROUTE) require(process.env.ROUTE)(p);
  const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const confirms = []; p.on('dialog', (d) => { confirms.push(d.message()); d.accept(); });
  const W = (ms) => p.waitForTimeout(ms);
  let n = 0; const shot = async (t) => { if (out) await p.screenshot({path: path.join(out, `${which}_voice_${String(++n).padStart(2, '0')}_${t}.jpg`), type: 'jpeg', quality: 85}); };
  const G = '#generation-dialog .vl-box';
  const phase = (sel = G) => p.evaluate((s) => document.querySelector(s)?.dataset.phase, sel);
  const text = (sel = G) => p.locator(sel).innerText();
  const until = async (fn, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await W(200); } return false; };
  const hash = () => p.evaluate(() => location.hash);
  const login = async () => { await p.evaluate(() => document.querySelector('[data-nav="records"]').click()); await W(400); await p.click('[data-login-google]'); await W(1500); };
  const startGen = async () => {
    await p.evaluate(() => { location.hash = 'records'; }); await W(800);
    for (let i = 0; i < 3 && await hash() !== '#style'; i++) { if (await p.locator('#choose-style').isVisible()) await p.click('#choose-style'); await W(600); }   // 엽서 고르기 → 문체
    await p.click('[data-style="essay"]'); await p.click('#generate-draft'); await W(900);
  };
  // 서버로 가는 음성 요청 지켜보기
  const spy = () => p.evaluate(() => {
    const a = window.Srv.api; window.__vl = {up: [], link: [], del: [], discard: []};
    const wrap = (k, f) => { const o = a[k]; a[k] = function (...x) { window.__vl[f].push(x.map((v) => (v instanceof Blob ? {blob: v.size} : v))); return o.apply(this, x); }; };
    wrap('voiceUpload', 'up'); wrap('voiceLink', 'link'); wrap('voiceDelete', 'del'); wrap('voiceDiscard', 'discard');
  });
  const calls = () => p.evaluate(() => JSON.parse(JSON.stringify(window.__vl)));
  const serverVoice = (id) => p.evaluate(async (id) => window.Srv.call(`/memoirs/saved/${id}/voice-message`), id);
  const failNext = (v) => p.evaluate((v) => localStorage.setItem('demo.failVoice', v), v);

  // ═══ 1. 진행 창 — 녹음 전 · 녹음 중 · 일찍 끝내기 · 책이 먼저 끝나도 화면이 그대로 ═══
  await p.goto(`file://${file}?demo=1`); await W(1300); await login(); await spy();
  await startGen();
  const t0 = await text();
  check(await phase() === 'idle' && /최대 5분/.test(t0) && await p.locator(`${G} [data-vl="start"]`).isVisible(), '[녹음 전] 진행 창에 「최대 5분」 안내 · 큰 「녹음 시작」');
  const bigH = (await p.locator(`${G} [data-vl="start"]`).boundingBox()).height;
  check(bigH >= 56, `[녹음 전] 「녹음 시작」 높이 ${Math.round(bigH)}px`);
  await shot('녹음전');
  await p.click(`${G} [data-vl="start"]`);
  await until(async () => (await phase()) === 'recording');
  await W(1800);
  const t1 = await text();
  check(/녹음 중/.test(t1) && /00:0[1-3] \/ 05:00/.test(t1) && await p.locator(`${G} [data-vl="stop"]`).isVisible(), `[녹음 중] 「녹음 중」 · 경과시간 / 05:00 · 「녹음 종료」 (${(t1.match(/\d\d:\d\d \/ 05:00/) || [''])[0]})`);
  await shot('녹음중');
  // 그동안 책이 다 만들어진다 — 녹음을 끊거나 화면을 옮기지 않는다
  const before = await hash();
  check(await until(async () => await p.locator('#generation-dialog .vl-gen-done:not([hidden])').count() === 1, 20000), '[책 완성] 녹음 중에 자서전이 다 만들어지면 진행 창에 「초안 보기」만 생기고');
  check(await phase() === 'recording' && await hash() === before && await p.locator('#generation-dialog[open]').count() === 1, `[책 완성] 녹음은 이어지고 화면도 그대로 (${before})`);
  await W(800);
  await p.click(`${G} [data-vl="stop"]`);
  check(await until(async () => (await phase()) === 'preview', 5000), '[녹음 종료] 5분 전에 언제든 끝낼 수 있다 → 미리듣기');
  const t2 = await text();
  check(/아직 저장되지 않았습니다/.test(t2) && /들어보기/.test(t2) && /다시 녹음/.test(t2) && /저장/.test(t2), '[녹음 종료 후] 「아직 저장되지 않았습니다」 · 들어보기 / 다시 녹음 / 저장');
  const mic = await p.evaluate(() => { const st = window.MemoirVoiceLetter.gen.st; return {stream: st.stream, size: st.blob && st.blob.size}; });
  check(mic.stream === null && mic.size > 0, `[녹음 종료] 마이크를 놓고(트랙 종료) 녹음 ${mic.size}B`);
  check((await calls()).up.length === 0, '[녹음 종료] 「저장」 전에는 아무것도 올리지 않는다');
  await shot('미리듣기');
  // 들어보기 — 실제로 재생된다
  await p.click(`${G} [data-vl="listen"]`); await W(700);
  check(/멈추기/.test(await text()), '[미리듣기] 들어보기를 누르면 재생 (멈추기로 바뀜)');
  await p.click(`${G} [data-vl="listen"]`); await W(200);
  // 다시 녹음은 확인을 받는다
  confirms.length = 0;
  await p.click(`${G} [data-vl="again"]`); await until(async () => (await phase()) === 'recording');
  check(confirms.some((m) => /사라져요/.test(m)), '[다시 녹음] 지금 음성이 사라진다는 확인을 받는다');
  await W(2200); await p.click(`${G} [data-vl="stop"]`); await until(async () => (await phase()) === 'preview');
  // 저장 — 연결 실패를 한 번 흉내: 업로드만으로 「저장 완료」 를 보이지 않는다, 같은 request_id 로 다시
  await failNext('LINK');
  await p.click(`${G} [data-vl="save"]`);
  await until(async () => ['error', 'ready'].includes(await phase()));
  const t3 = await text();
  check(await phase() === 'error' && !/저장 완료/.test(t3) && /아직 저장되지 않았습니다/.test(t3), '[연결 실패] 업로드(uploaded)만으로 「저장 완료」를 보이지 않는다 · 음성은 남는다');
  await shot('연결실패');
  await p.click(`${G} [data-vl="retry"]`);
  await until(async () => (await phase()) === 'ready');
  const c1 = await calls();
  check(await phase() === 'ready' && /책에 저장 완료/.test(await text()), '[저장] 연결 응답 message.state = ready 를 확인한 뒤에만 「책에 저장 완료」');
  check(c1.up.length === 1 && c1.link.length === 2 && c1.link[0][1].requestId === c1.link[1][1].requestId, `[연결 다시] 다시 저장은 업로드를 다시 하지 않고 같은 request_id 로 연결 (업로드 ${c1.up.length} · 연결 ${c1.link.length})`);
  const memo1 = await p.evaluate(() => window.MemoirVoiceLetter.gen.st.memoir);
  const sv1 = await serverVoice(memo1);
  check(sv1.message && sv1.message.state === 'ready', '[저장] 서버에도 그 책의 음성편지로 연결됨');
  await shot('저장완료');
  // 초안 보기
  await p.click('#generation-dialog [data-vl-view]'); await W(1200);
  check(await hash() === '#draft' && await p.locator('#generation-dialog[open]').count() === 0, '[초안 보기] 음성편지를 마친 뒤 사용자가 눌러 초안으로');

  // ═══ 2. 전자책 마지막 쪽 — 길이 · 「음성편지 듣기」(눌러야 재생) ═══
  await p.click('#save-volume'); await W(5000);
  await p.click('[data-library-book]'); await W(4500);
  const toEnd = async () => { for (let i = 0; i < 60; i++) { const d = await p.evaluate(() => { const x = document.getElementById('ebook-page-next'); if (!x || x.disabled || document.getElementById('ebook-page-controls').hidden) return true; x.click(); return false; }); if (d) break; await W(250); } await W(500); };
  await toEnd();
  const card = p.locator('[data-vl-card]').last();
  await card.scrollIntoViewIfNeeded().catch(() => {});
  const ct = await card.innerText().catch(() => '');
  check(/음성 길이/.test(ct) && /음성편지 듣기/.test(ct), `[마지막 쪽] 저장된 음성의 길이 · 「음성편지 듣기」`);
  const auto = await p.evaluate(() => [...document.querySelectorAll('audio')].every((a) => a.paused));
  check(auto, '[마지막 쪽] 자동재생하지 않는다');
  await shot('마지막쪽');
  await card.locator('[data-vlc="play"]').click(); await W(1500);
  check(await card.locator('[data-vlc="play"]').getAttribute('aria-pressed') === 'true' && /\d\d:\d\d \/ \d\d:\d\d/.test(await card.locator('.ebv-pos').textContent()), '[마지막 쪽] 눌러야 재생 (위치 표시)');
  await card.locator('[data-vlc="play"]').click(); await W(300);

  // ═══ 3. 교체 — 새 연결이 성공하기 전에는 이전 음성 유지 · 충돌 · 기한 지남 ═══
  const oldId = sv1.message.message_id;
  await card.locator('[data-vlc="replace"]').click(); await W(600);
  const B = '#voice-letter-dialog .vl-box';
  check(await p.locator('#voice-letter-dialog[open]').count() === 1 && /지금 음성편지가 그대로/.test(await p.locator('#voice-letter-dialog').innerText()), '[교체] 「다시 녹음해 바꾸기」 창 — 저장 전까지 지금 음성이 그대로라고 안내');
  await p.click(`${B} [data-vl="start"]`); await until(async () => (await phase(B)) === 'recording'); await W(2200);
  await p.click(`${B} [data-vl="stop"]`); await until(async () => (await phase(B)) === 'preview');
  await failNext('LINK');
  await p.click(`${B} [data-vl="save"]`); await until(async () => ['error', 'ready'].includes(await phase(B)));
  const svMid = await serverVoice(memo1);
  check(await phase(B) === 'error' && svMid.message && svMid.message.message_id === oldId, '[교체 실패] 연결이 실패하면 이전 음성편지가 그대로');
  // 충돌: 다른 곳에서 바뀌었다 → 다시 읽고 사용자에게 묻는다
  await failNext('LINK-conflict');
  await p.click(`${B} [data-vl="retry"]`); await until(async () => ['conflict', 'ready', 'error'].includes(await phase(B)));
  check(await phase(B) === 'conflict' && /다른 곳에서/.test(await text(B)), '[409 revision_conflict] 다시 읽고 사용자에게 「지금 녹음으로 바꾸기」를 묻는다');
  await shot('충돌');
  // 기한 지남: 탭에 원본이 있으면 새 X-Request-ID 로 다시 올리고 연결
  await failNext('LINK-expired');
  const upBefore = (await calls()).up.length;
  await p.click(`${B} [data-vl="take"]`); await until(async () => ['ready', 'error'].includes(await phase(B)), 20000);
  const c2 = await calls(), ups = c2.up.slice(upBefore);
  check(await phase(B) === 'ready' && ups.length === 1 && ups[0][1] !== c2.up[upBefore - 1][1], `[410 upload_expired] 원본이 탭에 있어 새 X-Request-ID 로 다시 올리고 연결 → 저장 완료`);
  const sv2 = await serverVoice(memo1);
  check(sv2.message && sv2.message.message_id !== oldId, '[교체] 연결이 성공한 뒤에야 새 음성편지로 바뀜');
  await p.click('#voice-letter-dialog [data-vld="close"]'); await W(800);
  await toEnd();

  // ═══ 4. 삭제 — 확인 후 · 서버가 지우기 전에는 화면에서 빼지 않는다 ═══
  await failNext('DELETE');
  confirms.length = 0;
  await p.locator('[data-vl-card] [data-vlc="delete"]').last().click(); await W(1500);
  check(confirms.some((m) => /지울까요/.test(m)) && /음성편지 듣기/.test(await p.locator('[data-vl-card]').last().innerText()), '[삭제 실패] 확인 후 지우기 — 서버가 실패하면 음성편지를 화면에서 지우지 않는다');
  await p.locator('[data-vl-card] [data-vlc="delete"]').last().click(); await W(1800);
  const after = await p.locator('[data-vl-card]').last().innerText().catch(() => '');
  check(/아직 음성편지가 없어요/.test(after) && !(await serverVoice(memo1)).message, '[삭제] 서버가 지운(204) 뒤 다시 읽어 「아직 음성편지가 없어요」');
  await shot('지운뒤');

  // ═══ 5. 생성 실패 · 취소 — 음성을 버리지 않고, 다음 책에는 물어보고 붙인다 ═══
  await p.evaluate(() => { document.querySelector('#ebook-back, [data-reader-back]')?.click(); location.hash = 'records'; }); await W(1200);
  await startGen();
  await p.click(`${G} [data-vl="start"]`); await until(async () => (await phase()) === 'recording'); await W(2000);
  await p.click(`${G} [data-vl="stop"]`); await until(async () => (await phase()) === 'preview');
  await p.click('#generation-dialog [data-gen="stop"]'); await W(900);     // 그만두기 (확인은 자동 수락)
  check(await phase() === 'preview' && await p.locator('#generation-dialog[open]').count() === 1, '[생성 취소] 자서전 만들기를 그만둬도 녹음한 음성은 그대로 · 창도 열려 있다');
  await p.click(`${G} [data-vl="save"]`); await until(async () => ['orphan', 'error'].includes(await phase()));
  const t5 = await text();
  check(await phase() === 'orphan' && /저장하지 못했어요/.test(t5) && /아직 저장되지 않았습니다/.test(t5), '[책 ID 없음] 올려 두되 어느 책에도 붙이지 않고 안내');
  await shot('책없음');
  const lib0 = await p.evaluate(async () => (await window.Srv.call('/memoirs/saved')).memoirs.map((m) => m.memoir_id));
  // 닫지 않고 다시 만든다 → 새 책이 끝나면 붙일지 묻는다 (최신 책에 저절로 붙이지 않음)
  await p.evaluate(() => { document.getElementById('generation-dialog').close(); }); await W(300);
  await startGen();
  check(await phase() === 'orphan', '[다시 만들기] 앞서 남은 음성이 진행 창에 그대로');
  check(await until(async () => (await phase()) === 'ask_attach', 25000), '[다시 만들기] 새 책이 다 만들어지면 「이 책에 저장할까요?」 묻는다');
  const lib1 = await p.evaluate(async () => (await window.Srv.call('/memoirs/saved')).memoirs.map((m) => m.memoir_id));
  const newId = lib1.find((x) => !lib0.includes(x));
  check(newId && !(await serverVoice(newId)).message, '[다시 만들기] 묻기 전에는 새 책에 붙이지 않는다');
  await shot('붙일지묻기');
  await p.click(`${G} [data-vl="attach"]`); await until(async () => ['ready', 'error'].includes(await phase()));
  const sv3 = await serverVoice(newId);
  check(await phase() === 'ready' && sv3.message && sv3.message.state === 'ready', '[다시 만들기] 「이 책에 저장」 → 그 책에 연결 · 저장 완료');

  // ═══ 6. 5분 자동 종료 (?voiceMax=4) — 마지막 부분까지 · 자동 저장 없음 · 끝나기 전 안내 ═══
  await p.goto(`file://${file}?demo=1&voiceMax=4`); await W(1400); await spy();
  await startGen();
  await p.click(`${G} [data-vl="start"]`); await until(async () => (await phase()) === 'recording');
  await W(2600);
  check(await p.locator(`${G} .vl-soon:not([hidden])`).count() === 1, '[끝나기 전 안내] 「30초 후 녹음이 끝납니다」 (시험에서는 끝 2초 전)');
  const stopped = await until(async () => (await phase()) === 'preview', 6000);
  const dur = await p.evaluate(async () => { const st = window.MemoirVoiceLetter.gen.st; try { const buf = await new OfflineAudioContext(1, 44100, 44100).decodeAudioData(await st.blob.arrayBuffer()); return {ms: st.ms, real: Math.round(buf.duration * 1000)}; } catch (e) { return {ms: st.ms, real: -1}; } });
  check(stopped && /4초/.test(await text()) && /끝났어요/.test(await text()), `[자동 종료] 정한 시간이 되면 녹음 종료 → 미리듣기 (기록 ${dur.ms}ms)`);
  check(dur.real >= 3500, `[자동 종료] 마지막 부분까지 들어 있다 — 녹음 실제 길이 ${dur.real}ms / 4000ms`);
  check((await calls()).up.length === 0, '[자동 종료] 저절로 올리거나 저장하지 않는다');
  // 닫기 · 새로고침 경고 (저장 전 음성)
  const warn = await p.evaluate(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; });
  check(warn, '[이탈 경고] 저장하지 않은 음성이 있으면 닫기 · 새로고침 경고');
  // 진행 창을 닫으려 하면 확인
  confirms.length = 0;
  await p.locator('#generation-dialog [data-gen="hide"]').click().catch(() => {}); await W(400);
  check(confirms.some((m) => /사라져요/.test(m)), '[이탈 확인] 저장 전 음성이 있는데 진행 창을 닫으면 사라진다는 확인');
  check(errs.length === 0, '자바스크립트 오류 없음' + (errs.length ? ': ' + errs.join(' | ') : ''));
  await b.close();
  console.log(fail.length ? `${which} 실패 ${fail.length}` : `${which} 모두 통과`);
  process.exit(fail.length ? 1 : 0);
})();
