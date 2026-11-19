(function () {
  'use strict';
  // 엽서보기 — 「엽서 n장 · 엽서 지우기 · 짧은 설명」을 맨 아래에서 주제(분류) 줄 바로 아래로 옮긴다.
  // 맨 아래에는 「자서전 만들기」 버튼만 남는다. (엽서 고르기 중에는 같은 자리에 「n장 선택 · 고르는 안내」가 나온다)
  const list = document.getElementById('record-list');
  const footer = document.querySelector('.selection-footer');
  const info = footer && footer.firstElementChild;
  if (!list || !info || info.tagName === 'BUTTON') return;
  const box = document.createElement('div');
  box.className = 'records-info';
  box.append(info);
  list.before(box);
  footer.classList.add('only-action');
}());
