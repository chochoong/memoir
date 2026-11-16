/* 자서전 초안 — 검증 결과 알림 (다섯 단계의 ⑤ 검증이 응답에 실어 준 것만 보인다)
 *
 * 응답의 verification.outcome 이 있을 때만 그린다 (다섯 단계 결과). 예전 한 번 호출의 초안에는 아무것도 더하지 않는다.
 *   passed               인터뷰 기록과 대조했고 문제를 찾지 못했다
 *   issues_found         기록과 다르게 쓰인 듯한 곳 — 문장과 까닭을 보인다
 *   needs_confirmation   사람이 확인해야 하는 곳 (to_confirm) — 받아 적기가 틀린 듯한 말 등
 *   failed · not_run · incomplete   검토를 거치지 않은 초안이라고 알린다 — 「검증 완료」 로 보이지 않게
 * 글을 고치지 않는다. 고치기는 「글 수정하기」 로 사람이 한다. 본문에는 아무것도 넣지 않는다.
 */
(function () {
  'use strict';
  var MAX = 8;                                   // 한 번에 보이는 항목 수 — 넘으면 개수만 알린다

  function el(tag, text, style) {
    var n = document.createElement(tag);
    if (text) n.textContent = text;
    if (style) n.setAttribute('style', style);
    return n;
  }

  function view() {
    try { return (typeof state !== 'undefined' && state.document) || null; } catch (e) { return null; }
  }

  function paint() {
    var aside = document.querySelector('.draft-aside');
    if (!aside) return;
    var box = document.getElementById('draft-verify');
    var doc = view();
    var v = doc && doc.verification;
    if (!v || !v.outcome) { if (box) box.remove(); return; }
    if (!box) {
      box = el('div', '', 'padding:18px 20px;margin-top:14px;font-size:17px;line-height:1.6');
      box.className = 'panel';
      box.id = 'draft-verify';
      box.setAttribute('role', 'status');
      var note = aside.querySelector('.draft-note');
      if (note && note.nextSibling) aside.insertBefore(box, note.nextSibling); else aside.appendChild(box);
    }
    box.textContent = '';
    var asks = ((doc.sourceResult && doc.sourceResult.to_confirm) || []).filter(function (x) { return x && x.issue; });
    var issues = (v.issues || []).filter(function (x) { return x && x.category === 'fact' && !x.needs_user; });
    // 코드 판정이 막은 곳 (정정 전 값 · 인터뷰를 멈추는 말 등) — 검증 모델의 지적과 따로 센다
    var blocks = (v.code && v.code.state === 'blocked' && v.code.blocks) || [];
    var found = issues.length + blocks.length;
    var head = {
      // state=completed 는 「검토가 끝까지 돌았다」 일 뿐이다 — 문제가 없다는 말은 outcome=passed 일 때만, 그것도 AI 의 검토라는 단서와 함께
      passed: issues.length
        ? '큰 문제는 찾지 못했지만 살펴볼 곳이 ' + issues.length + '군데 있어요. AI의 검토라 놓친 곳이 있을 수 있어요.'
        : '인터뷰 기록과 대조해 보았어요. 큰 문제는 찾지 못했지만, AI의 검토라 놓친 곳이 있을 수 있어요. 읽어 보며 확인해 주세요.',
      issues_found: '인터뷰 기록과 다르게 쓰인 듯한 곳이 ' + found + '군데 있어요. 읽어 보고 고쳐 주세요.',
      needs_confirmation: '확인이 필요한 곳이 ' + asks.length + '군데 있어요.',
      failed: '이 초안은 인터뷰 기록과 대조하는 검토를 끝내지 못했어요. 사실과 다른 곳이 있을 수 있어요.',
      not_run: '이 초안은 아직 인터뷰 기록과 대조하는 검토를 거치지 않았어요.',
      incomplete: '검토가 끝까지 이루어지지 않았어요. 사실과 다른 곳이 있을 수 있어요.'
    }[v.outcome] || '검토 상태를 알 수 없어요.';
    box.appendChild(el('strong', v.outcome === 'passed' ? 'AI 검토를 마쳤어요' : '검토 결과', 'display:block;margin-bottom:6px'));
    box.setAttribute('data-outcome', v.outcome);
    box.appendChild(el('p', head));
    var rows = asks.map(function (x) { return { text: x.issue, quote: '' }; })
      .concat(issues.map(function (x) { return { text: x.explanation || '기록과 다를 수 있어요', quote: x.sentence || '' }; }))
      .concat(blocks.map(function (x) { return { text: x.detail || '자동 점검에서 고쳐야 할 곳으로 표시됐어요', quote: '' }; }));
    if (!rows.length) return;
    var list = el('ul', '', 'margin:10px 0 0;padding-left:20px');
    rows.slice(0, MAX).forEach(function (r) {
      var li = el('li', '', 'margin-bottom:8px');
      if (r.quote) li.appendChild(el('span', '「' + r.quote + '」 ', 'display:block;opacity:.75'));
      li.appendChild(el('span', r.text));
      list.appendChild(li);
    });
    box.appendChild(list);
    if (rows.length > MAX) box.appendChild(el('p', '그 밖에 ' + (rows.length - MAX) + '군데가 더 있어요.', 'opacity:.75'));
  }

  var original = window.renderDraft;
  if (typeof original === 'function') {
    window.renderDraft = function () {
      var out = original.apply(this, arguments);
      try { paint(); } catch (e) { /* 알림은 덤이다 — 초안 화면을 막지 않는다 */ }
      return out;
    };
  }
  window.draftVerifyPaint = paint;
})();
