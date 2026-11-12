(function () {
  'use strict';
  // 엽서 · 자서전이 함께 쓰는 「지우기」 부품: 한 번 더 묻는 창, 여러 개 고를 때 아래 막대, 지운 뒤 「되돌리기」.

  // ── 한 번 더 묻는 창 ──
  const dialog = document.createElement('dialog');
  dialog.className = 'review-dialog trash-dialog';
  dialog.setAttribute('aria-labelledby', 'trash-title');
  dialog.innerHTML = `<h2 id="trash-title"></h2><ul class="trash-items"></ul><p class="trash-desc"></p>
    <div class="dialog-actions"><button type="button" class="button outline" data-trash-keep>그대로 두기</button><button type="button" class="button trash-ok" data-trash-ok></button></div>`;
  document.body.append(dialog);
  let settle = null;
  function confirm({title, items = [], desc, ok}) {
    dialog.querySelector('#trash-title').textContent = title;
    const shown = items.slice(0, 5);
    dialog.querySelector('.trash-items').innerHTML = shown.map((t) => `<li>${escapeText(t)}</li>`).join('') + (items.length > shown.length ? `<li class="trash-more">그 밖에 ${items.length - shown.length}개</li>` : '');
    dialog.querySelector('.trash-items').hidden = !items.length;
    dialog.querySelector('.trash-desc').textContent = desc;
    dialog.querySelector('[data-trash-ok]').textContent = ok;
    dialog.showModal();
    dialog.querySelector('[data-trash-keep]').focus();
    return new Promise((resolve) => { settle = resolve; });
  }
  function finish(value) { if (!settle) return; const s = settle; settle = null; dialog.close(); s(value); }
  dialog.querySelector('[data-trash-keep]').addEventListener('click', () => finish(false));
  dialog.querySelector('[data-trash-ok]').addEventListener('click', () => finish(true));
  dialog.addEventListener('cancel', (e) => { e.preventDefault(); finish(false); });
  dialog.addEventListener('click', (e) => { if (e.target === dialog) finish(false); });

  // ── 지운 뒤 「되돌리기」 ──
  // onCommit — 되돌리기 시간이 끝나면(또는 다른 것을 지우거나 화면을 떠나면) 그때 서버에서 지운다.
  // 서버에는 되살리기 API 가 없어서, 「되돌리기」를 누를 수 있는 동안은 서버에 보내지 않는다.
  let undoBar = null, undoTimer = null, pendingCommit = null;
  function flush() { const fn = pendingCommit; pendingCommit = null; if (fn) { try { fn(); } catch (_) {} } }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });
  window.addEventListener('pagehide', flush);
  function undo(message, onUndo, onCommit) {
    clearTimeout(undoTimer); undoBar?.remove(); flush();
    pendingCommit = onCommit || null;
    undoBar = document.createElement('div');
    undoBar.className = 'trash-undo'; undoBar.setAttribute('role', 'status');
    undoBar.innerHTML = `<span>${escapeText(message)}</span><button type="button">되돌리기</button>`;
    document.body.append(undoBar);
    const bar = undoBar;
    bar.querySelector('button').addEventListener('click', () => { clearTimeout(undoTimer); bar.remove(); if (undoBar === bar) { undoBar = null; pendingCommit = null; } onUndo(); });
    undoTimer = setTimeout(() => { bar.remove(); if (undoBar === bar) { undoBar = null; flush(); } }, 8000);
  }
  function clearUndo() { clearTimeout(undoTimer); undoBar?.remove(); undoBar = null; flush(); }

  // ── 여러 개 고를 때 아래 막대 ──
  function selectBar({unit, counter, empty, onAll, onCancel, onDelete}) {
    const bar = document.createElement('div');
    bar.className = 'trash-select-bar'; bar.hidden = true;
    bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', `${unit} 고르기`);
    bar.innerHTML = `<span class="tsb-count" aria-live="polite"></span>
      <div class="tsb-actions"><button type="button" class="text-button" data-tsb-all>모두 고르기</button>
      <button type="button" class="button outline compact" data-tsb-cancel>그만두기</button>
      <button type="button" class="button compact trash-ok" data-tsb-delete disabled></button></div>`;
    document.body.append(bar);
    bar.querySelector('[data-tsb-all]').addEventListener('click', onAll);
    bar.querySelector('[data-tsb-cancel]').addEventListener('click', onCancel);
    bar.querySelector('[data-tsb-delete]').addEventListener('click', onDelete);
    return {
      el: bar,
      show() { bar.hidden = false; document.body.classList.add('trash-selecting'); const t = document.getElementById('toast'); if (t) t.hidden = true; },
      hide() { bar.hidden = true; document.body.classList.remove('trash-selecting'); },
      update(n, total) {
        bar.querySelector('.tsb-count').textContent = n ? `${unit} ${n}${counter} 골랐어요` : empty;
        const del = bar.querySelector('[data-tsb-delete]');
        del.disabled = !n; del.textContent = n ? `${n}${counter} 지우기` : '지우기';
        bar.querySelector('[data-tsb-all]').textContent = total && n === total ? '모두 풀기' : '모두 고르기';
      },
    };
  }

  window.MemoirTrash = {confirm, undo, clearUndo, selectBar};
}());
