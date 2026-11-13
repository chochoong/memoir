(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     postcard-image — 엽서를 그림(PNG) 한 장으로 그린다. 「엽서 공유」가 글 대신 엽서 그 자체를 보내게.
       · 1080×1350(4:5) — 카카오톡 · 문자에서 잘리지 않고 크게 보이는 비율
       · 코르크 보드 위에 핀으로 꽂힌 엽서: 분류 · 날짜 · 제목 · 줄 친 본문 · 우표 · 누구의 이야기
       · 서버 없이 이 기기에서만 그린다. 글이 길면 글자를 줄이고, 그래도 넘치면 「…」로 끝낸다(전체 글은 함께 보내는 글에)
     ═══════════════════════════════════════════════════════════════ */
  const W = 1080, H = 1350;
  const TITLE_FONT = '"Memoir Cover Serif", "Noto Serif KR", "Batang", "바탕", serif';
  const BODY_FONT = '"Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "Noto Sans CJK KR", sans-serif';
  const PAPER = ['#fffdf6', '#fbf3e3'], YELLOW = ['#fdeba4', '#f8df8c'];

  /** 글자 단위로 줄을 나눈다 — 한국어는 띄어쓰기 없이 길게 이어지는 경우가 많아 단어보다 글자로 끊는 게 안전하다 */
  function wrap(ctx, text, width) {
    const lines = [];
    String(text).split('\n').forEach((para) => {
      if (!para.trim()) { if (lines.length && lines[lines.length - 1] !== '') lines.push(''); return; }
      let line = '';
      for (const word of para.trim().split(/(\s+)/)) {
        const next = line + word;
        if (ctx.measureText(next).width <= width) { line = next; continue; }
        if (line.trim()) { lines.push(line.trimEnd()); line = ''; }
        if (ctx.measureText(word).width <= width) { line = word.trimStart(); continue; }
        for (const ch of word) { if (ctx.measureText(line + ch).width > width) { lines.push(line); line = ''; } line += ch; }
      }
      if (line.trim()) lines.push(line.trimEnd());
    });
    while (lines.length && lines[lines.length - 1] === '') lines.pop();
    return lines;
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  /** 화면의 아이콘(SVG 심볼)을 그림으로 — 우표 안에 넣는다 */
  function iconImage(name, color) {
    const sym = document.getElementById(`i-${name}`) || document.getElementById('i-letter');
    if (!sym) return Promise.resolve(null);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${sym.getAttribute('viewBox') || '0 0 24 24'}" width="96" height="96" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${sym.innerHTML}</svg>`;
    return new Promise((res) => { const img = new Image(); img.onload = () => res(img); img.onerror = () => res(null); img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`; });
  }
  function cork(ctx) {
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, '#c99e70'); g.addColorStop(1, '#b4865a');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    // 코르크 알갱이 — 늘 같은 무늬가 나오게 정해진 수열로 찍는다
    let s = 7;
    const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
    for (let i = 0; i < 2600; i++) {
      ctx.fillStyle = rnd() > .5 ? 'rgba(92,58,30,.16)' : 'rgba(255,236,200,.14)';
      ctx.fillRect(rnd() * W, rnd() * H, 2 + rnd() * 3, 2 + rnd() * 3);
    }
    ctx.strokeStyle = '#7a5235'; ctx.lineWidth = 26; ctx.strokeRect(13, 13, W - 26, H - 26);
  }

  /**
   * @param {{title:string, body:string, date:string, category?:string, icon?:string, who?:string, yellow?:boolean}} card
   * @returns {Promise<{blob: Blob, clipped: boolean, url: string}>}
   */
  async function render(card) {
    try { await Promise.all([document.fonts.load(`600 56px ${TITLE_FONT}`, card.title || '가'), document.fonts.ready]); } catch (_) { /* 기본 글꼴로 그린다 */ }
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const ctx = c.getContext('2d');
    cork(ctx);

    // 엽서 종이 — 보드 위에 살짝 기울여 꽂는다
    const px = 110, py = 150, pw = W - 220, ph = H - 330;
    ctx.save();
    ctx.translate(W / 2, py + ph / 2); ctx.rotate(-1.2 * Math.PI / 180); ctx.translate(-W / 2, -(py + ph / 2));
    ctx.shadowColor = 'rgba(59,34,14,.38)'; ctx.shadowBlur = 38; ctx.shadowOffsetY = 18;
    const paper = ctx.createLinearGradient(0, py, 0, py + ph);
    const tone = card.yellow ? YELLOW : PAPER;
    paper.addColorStop(0, tone[0]); paper.addColorStop(1, tone[1]);
    ctx.fillStyle = paper; roundRect(ctx, px, py, pw, ph, 10); ctx.fill();
    ctx.shadowColor = 'transparent';

    const ix = px + 70, iw = pw - 140;
    // 우표
    const sw = 150, sh = 170, sx = px + pw - 70 - sw, sy = py + 64;
    ctx.fillStyle = '#fffaf0'; ctx.fillRect(sx, sy, sw, sh);
    ctx.setLineDash([7, 6]); ctx.strokeStyle = '#b89a7c'; ctx.lineWidth = 3; ctx.strokeRect(sx + 9, sy + 9, sw - 18, sh - 18); ctx.setLineDash([]);
    const ic = await iconImage(card.icon || 'letter', '#8a465e');
    if (ic) ctx.drawImage(ic, sx + (sw - 84) / 2, sy + (sh - 84) / 2, 84, 84);

    // 분류 · 날짜
    ctx.fillStyle = '#8a7568'; ctx.font = `500 30px ${BODY_FONT}`; ctx.textBaseline = 'alphabetic';
    ctx.fillText([card.category, card.date].filter(Boolean).join('  ·  '), ix, py + 112);
    // 제목 — 우표 옆 폭 안에서 두 줄까지
    ctx.fillStyle = '#2f2622'; ctx.font = `600 58px ${TITLE_FONT}`;
    const tw = sx - ix - 30, tAll = wrap(ctx, card.title || '엽서', tw), tLines = tAll.slice(0, 2);
    if (tAll.length > 2) { let t = tLines[1]; while (t && ctx.measureText(`${t}…`).width > tw) t = t.slice(0, -1); tLines[1] = `${t.trimEnd()}…`; }
    tLines.forEach((t, i) => ctx.fillText(t, ix, py + 196 + i * 78));
    let top = Math.max(py + 196 + (tLines.length - 1) * 78 + 60, sy + sh + 40);

    // 본문 — 줄 친 종이. 넘치면 글자를 줄이고, 그래도 넘치면 마지막 줄을 「…」로
    const footH = 120, bottom = py + ph - footH;
    let size = 40, lh = 72, lines;
    for (;;) {
      ctx.font = `400 ${size}px ${BODY_FONT}`;
      lines = wrap(ctx, card.body || '', iw);
      if (top + lines.length * lh <= bottom || size <= 30) break;
      size -= 2; lh = Math.round(size * 1.78);
    }
    const max = Math.max(1, Math.floor((bottom - top) / lh));
    const clipped = lines.length > max;
    if (clipped) { lines = lines.slice(0, max); let last = lines[max - 1]; while (last && ctx.measureText(`${last}…`).width > iw) last = last.slice(0, -1); lines[max - 1] = `${last.trimEnd()}…`; }
    ctx.strokeStyle = 'rgba(160,130,105,.32)'; ctx.lineWidth = 2;
    const rows = Math.floor((bottom - top) / lh);
    for (let i = 0; i < rows; i++) { const y = top + (i + 1) * lh - lh * .28; ctx.beginPath(); ctx.moveTo(ix, y); ctx.lineTo(ix + iw, y); ctx.stroke(); }
    ctx.fillStyle = '#3d322d';
    lines.forEach((t, i) => ctx.fillText(t, ix, top + (i + 1) * lh - lh * .42));

    // 누구의 이야기
    ctx.fillStyle = '#7a4a55'; ctx.font = `600 34px ${TITLE_FONT}`; ctx.textAlign = 'right';
    ctx.fillText(card.who ? `— ${card.who}의 이야기` : '— 나의 이야기', px + pw - 70, py + ph - 56);
    ctx.textAlign = 'left';
    ctx.restore();

    // 핀
    const pinX = W / 2, pinY = py + 6;
    ctx.fillStyle = 'rgba(40,20,10,.35)'; ctx.beginPath(); ctx.ellipse(pinX + 8, pinY + 14, 22, 12, 0, 0, Math.PI * 2); ctx.fill();
    const pin = ctx.createRadialGradient(pinX - 8, pinY - 8, 4, pinX, pinY, 26);
    pin.addColorStop(0, '#e46b5f'); pin.addColorStop(1, '#8d1f1c');
    ctx.fillStyle = pin; ctx.beginPath(); ctx.arc(pinX, pinY, 24, 0, Math.PI * 2); ctx.fill();

    // 맨 아래 — 내말싸미
    ctx.fillStyle = '#fff6e6'; ctx.textAlign = 'center';
    ctx.font = `600 38px ${TITLE_FONT}`; ctx.fillText('내말싸미', W / 2, H - 92);
    ctx.font = `400 26px ${BODY_FONT}`; ctx.fillStyle = 'rgba(255,246,230,.85)';
    ctx.fillText('목소리로 남긴 이야기 · naemalssami.com', W / 2, H - 52);
    ctx.textAlign = 'left';

    const blob = await new Promise((res) => c.toBlob(res, 'image/png'));
    return {blob, clipped, url: URL.createObjectURL(blob)};
  }
  const fileName = (title) => `${String(title || '엽서').replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 40) || '엽서'}.png`;
  window.MemoirPostcardImage = {render, fileName};
}());
