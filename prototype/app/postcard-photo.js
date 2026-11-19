(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     postcard-photo — 이야기를 시작할 때 넣은 사진을 엽서에 붙인다 (B안: 지금 엽서 + 인화한 사진)
       · 엽서 목록(GET /api/sessions)의 photo_id → GET /api/photos/{photo_id} 를 받아 이 화면에서만 쓰는 주소(blob)로.
         <img src> 로 서버 주소를 바로 쓰지 않는 까닭: 로그인 머리글(idHeaders)을 실어야 하고, 엽서 그림(캔버스)에도 그려야 해서.
       · 보드의 엽서: 윗부분에 흰 테를 두른 사진 / 펼친 엽서: 사진 + 사진 설명(엽서의 caption) / 공유 그림: 사진을 함께 그린다.
       · 사진을 못 받으면 사진 칸을 조용히 뺀다 — 엽서 글은 그대로.
     ═══════════════════════════════════════════════════════════════ */
  const S = window.Srv;
  const cache = new Map(); // photo_id → Promise<string|null> (blob 주소)

  function src(id) {
    if (!id || !S) return Promise.resolve(null);
    if (!cache.has(id)) {
      cache.set(id, (async () => {
        try {
          const res = await fetch(`${S.CONFIG.apiBase}/api/photos/${encodeURIComponent(id)}`, {credentials: 'include', headers: S.idHeaders(`/photos/${id}`)});
          if (!res.ok) throw new Error(String(res.status));
          return URL.createObjectURL(await res.blob());
        } catch (_) { cache.delete(id); return null; }
      })());
    }
    return cache.get(id);
  }
  /** 캔버스에 그릴 수 있게 다 읽은 그림 */
  async function image(id) {
    const url = await src(id); if (!url) return null;
    return new Promise((res) => { const img = new Image(); img.onload = () => res(img); img.onerror = () => res(null); img.src = url; });
  }
  // 서버 주소(/api/…)로 된 그림 — 자서전 속 사진 · 삽화
  const byPath = new Map();
  function srcPath(path) {
    if (!path || !S) return Promise.resolve(null);
    if (!byPath.has(path)) {
      byPath.set(path, (async () => {
        try {
          const p = path.replace(/^\/api/, '');
          const res = await fetch(`${S.CONFIG.apiBase}/api${p}`, {credentials: 'include', headers: S.idHeaders(p.split('?')[0])});
          if (!res.ok) throw new Error(String(res.status));
          return URL.createObjectURL(await res.blob());
        } catch (_) { byPath.delete(path); return null; }
      })());
    }
    return byPath.get(path);
  }
  /** [data-pc-photo] 자리에 사진을 채운다. 못 받으면 자리를 없앤다 */
  function fill(root) {
    (root || document).querySelectorAll('[data-pc-photo]:not([data-filled])').forEach((box) => {
      box.dataset.filled = '1';
      src(box.dataset.pcPhoto).then((url) => {
        if (!url) { box.remove(); return; }
        const img = box.querySelector('img'); img.src = url;
        img.addEventListener('load', () => box.classList.add('ready'), {once: true});
      });
    });
  }
  /** 자서전 그림 — 쪽을 넘길 때마다 새로 그려지므로 늘 다시 채운다(받은 주소는 기억해 둔다). 못 받으면 그림 칸을 접는다 */
  function fillFigures(root) {
    (root || document).querySelectorAll('img[data-fig-src]:not([src])').forEach((img) => {
      img.setAttribute('src', 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==');
      srcPath(img.dataset.figSrc).then((url) => { if (url) img.src = url; else img.closest('figure')?.classList.add('fig-missing'); });
    });
  }
  // 엽서 보드 · 펼친 엽서 · 자서전 쪽이 그려질 때마다
  new MutationObserver(() => { fill(); fillFigures(); }).observe(document.body, {childList: true, subtree: true});

  window.MemoirPostcardPhoto = {src, image, fill, srcPath};
}());
