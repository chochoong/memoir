(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     memoir-order — 「엽서 정리 · 책 정리」에서 끌어 바꾼 순서를 기억하고, 보드 · 책장에 그 순서대로 늘어놓는다.
       · 서버에는 순서를 받는 API 가 없다 → 이 브라우저(localStorage)에만 기억한다. 다른 기기에서는 원래 순서로 보인다.
         (서버 변경 요청서 「순서 저장」 항목 — 서버가 생기면 load/save 두 곳만 바꾸면 된다)
       · 이야기 주인공마다 따로 기억한다: memoir.order.<kind>.<elderId>
       · 기억한 적 없는 새 엽서 · 새 책은 원래 자리(서버가 준 순서)에 그대로 둔다 — 순서를 정한 것들만 그 자리들 안에서 바꾼다.
       · 보기 순서일 뿐이다. 「최근 나눈 이야기」는 늘 최근 순, 자서전 장 순서는 늘 엽서를 만든 날짜 순.
     ═══════════════════════════════════════════════════════════════ */
  const key = (kind) => `memoir.order.${kind}.${(typeof currentElderId === 'function' && currentElderId()) || '-'}`;
  function load(kind) {
    try { const v = JSON.parse(localStorage.getItem(key(kind)) || '[]'); return Array.isArray(v) ? v.map(String) : []; } catch (_) { return []; }
  }
  function save(kind, ids) {
    try { localStorage.setItem(key(kind), JSON.stringify(ids.map(String))); } catch (_) { /* 저장이 막혀도 지금 화면에서는 바뀐 순서로 보인다 */ }
  }
  /** list 를 기억한 순서로 늘어놓은 새 배열. idOf(item) → 그 항목의 id */
  function apply(kind, list, idOf) {
    const saved = load(kind);
    if (!saved.length) return list.slice();
    const rank = new Map(saved.map((id, i) => [id, i]));
    const known = list.filter((item) => rank.has(String(idOf(item))));
    known.sort((a, b) => rank.get(String(idOf(a))) - rank.get(String(idOf(b))));
    let k = 0;
    return list.map((item) => (rank.has(String(idOf(item))) ? known[k++] : item));
  }
  window.MemoirOrder = {load, save, apply};
}());
