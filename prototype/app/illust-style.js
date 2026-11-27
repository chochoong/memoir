(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     illust-style — 자서전 만들기 「문체 선택」 화면의 「삽화 그림체」 고르기 (2026-11-25)
       · 수채화(watercolor · 기본) · 애니풍(anime) · 유화(oil_painting) 셋 중 하나.
       · 고른 값은 POST /api/memoirs 본문의 illust_style 로 간다 (srv-memoir.js generate → api.memoirStart).
         고르지 않으면 수채화다 — 서버도 값이 없으면 수채화로 그린다. 모르는 값은 서버가 400 unsupported_illust_style.
       · 그 책의 모든 AI 삽화(사진이 없는 장)가 같은 그림체로 그려진다. 사진은 원본 그대로. 장마다 고르거나 승인하는 단계는 없다.
       · 문체(style)와 따로다. 이 화면의 문체 카드(app.js · data-style)는 건드리지 않는다 — 카드 모양(.style-card)만 빌려 쓴다.
       · 고른 값은 이 화면을 연 동안만 기억한다 (새로고침하면 수채화로 돌아온다).
     ═══════════════════════════════════════════════════════════════ */
  const LIST = [
    {id: 'watercolor', title: '수채화', note: '부드러운 번짐과 종이결, 따뜻하고 절제된 색'},
    {id: 'anime', title: '애니풍', note: '깔끔한 선과 맑은 색, 애니메이션 영화 같은 그림'},
    {id: 'oil_painting', title: '유화', note: '붓 자국과 겹친 물감, 깊이 있는 색감'},
  ];
  const DEFAULT = 'watercolor';
  let chosen = DEFAULT;

  function paint(box) {
    box.querySelectorAll('[data-illust-style]').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.illustStyle === chosen)));
  }

  function mount() {
    const screen = document.querySelector('section[data-screen="style"]');
    if (!screen || screen.querySelector('.illust-style')) return;
    const box = document.createElement('div');
    box.className = 'panel illust-style';
    box.innerHTML = '<div class="illust-style-head"><div class="eyebrow" id="illust-style-heading">삽화 그림체</div>'
      + '<p class="small-copy">사진이 없는 장에 들어갈 그림이에요. 책 한 권이 같은 그림체로 그려지고, 넣은 사진은 원본 그대로 실려요.</p></div>'
      + '<div class="illust-style-options" role="group" aria-labelledby="illust-style-heading">'
      + LIST.map((s) => `<button type="button" class="style-card illust-style-card" data-illust-style="${s.id}" aria-pressed="false">`
        + `<span><strong>${s.title}</strong><small>${s.note}</small></span><span class="style-check" aria-hidden="true"></span></button>`).join('')
      + '</div>';
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-illust-style]');
      if (!b || !LIST.some((s) => s.id === b.dataset.illustStyle)) return;
      chosen = b.dataset.illustStyle;
      paint(box);
    });
    const footer = screen.querySelector('.build-footer');
    if (footer) footer.before(box); else screen.appendChild(box);
    paint(box);
  }

  window.SrvIllustStyle = {
    value: () => chosen,
    label: () => (LIST.find((s) => s.id === chosen) || LIST[0]).title,
    list: () => LIST.map((s) => Object.assign({}, s)),
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
