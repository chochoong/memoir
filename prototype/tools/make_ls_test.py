"""자간(글자 사이 간격) 시험판 3개를 만든다 — prototype/ls-test/ls-1.html · ls-2.html · ls-3.html

원본 prototype/index.html 은 건드리지 않는다. 복사본에 자간을 바꾸는 작은 스크립트만 끼워 넣는다.
  1안 살짝     : 모든 글자 자간을 지금보다 +0.02em
  2안 넉넉하게 : 모든 글자 자간을 지금보다 +0.04em
  3안 역할별   : 제목(h1~h4 · 24px 이상)은 음수 자간을 0으로, 15px 이하 작은 글씨 +0.05em,
                 버튼 · 링크 · 메뉴 +0.02em, 나머지 본문 +0.03em (음수 자간은 먼저 0으로)
시험판은 늘 예시 모드(가짜 서버)로 열린다. index.html 을 다시 빌드했으면 이 파일도 다시 돌린다:
  python prototype/tools/make_ls_test.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'index.html')
OUT_DIR = os.path.join(ROOT, 'ls-test')

OPTIONS = {
    1: '1안 · 살짝 (+0.02em)',
    2: '2안 · 넉넉하게 (+0.04em)',
    3: '3안 · 역할별',
}

SCRIPT = r"""
<script data-from="ls-test">
(function () {
  'use strict';
  var OPT = %(opt)d, LABEL = %(label)r;
  // 원래 자간(em)을 data-ls-orig 에 적어 두고, 그 값에 더한 새 자간을 style 로 덮는다
  function next(e, em, fs) {
    if (OPT === 1) return em + 0.02;
    if (OPT === 2) return em + 0.04;
    var base = Math.max(em, 0);
    if (/^H[1-4]$/.test(e.tagName) || fs >= 24) return base;
    if (fs <= 15) return base + 0.05;
    if (e.closest('button,a,nav,label,[role=tab]')) return base + 0.02;
    return base + 0.03;
  }
  function apply(root) {
    var list = (root.querySelectorAll ? root.querySelectorAll('*') : []);
    var els = [root].concat(Array.prototype.slice.call(list));
    els.forEach(function (e) {
      if (!e.tagName || e.hasAttribute('data-ls-orig') || e.closest('#ls-test-badge')) return;
      var hasText = Array.prototype.some.call(e.childNodes, function (n) { return n.nodeType === 3 && n.textContent.trim(); });
      if (!hasText) return;
      var cs = getComputedStyle(e), fs = parseFloat(cs.fontSize) || 16;
      var em = cs.letterSpacing === 'normal' ? 0 : (parseFloat(cs.letterSpacing) || 0) / fs;
      e.setAttribute('data-ls-orig', em.toFixed(3));
      e.style.setProperty('letter-spacing', next(e, em, fs).toFixed(3) + 'em', 'important');
    });
  }
  var pending = new Set(), timer = 0;
  function flush() { timer = 0; pending.forEach(function (n) { if (n.isConnected) apply(n); }); pending.clear(); }
  function start() {
    apply(document.body);
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var t = m.type === 'characterData' ? m.target.parentElement : m.target;
        if (t) pending.add(t);
        if (m.type === 'childList') m.addedNodes.forEach(function (n) { if (n.nodeType === 1) pending.add(n); });
      });
      if (!timer) timer = setTimeout(flush, 30);
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
    var b = document.createElement('div');
    b.id = 'ls-test-badge';
    b.textContent = '자간 시험판 ' + LABEL;
    b.style.cssText = 'position:fixed;right:10px;bottom:10px;z-index:2147483647;padding:6px 12px;border-radius:999px;background:#1f6f5c;color:#fff;font:600 13px/1.4 var(--sans);pointer-events:none;box-shadow:0 2px 8px #0003';
    document.body.appendChild(b);
  }
  var go = function () { (document.fonts ? document.fonts.ready : Promise.resolve()).then(start); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
})();
</script>
"""

html = open(SRC, encoding='utf-8').read()
assert html.count('</body>') == 1
os.makedirs(OUT_DIR, exist_ok=True)
for opt, label in OPTIONS.items():
    out = html
    if 'window.MEMOIR_FORCE_DEMO = true;' not in out:
        out = out.replace('<head>', '<head>\n<script>window.MEMOIR_FORCE_DEMO = true;</script>', 1)
    out = out.replace('<title>', f'<title>[자간 {opt}안] ', 1)
    out = out.replace('</body>', SCRIPT % {'opt': opt, 'label': label} + '</body>')
    path = os.path.join(OUT_DIR, f'ls-{opt}.html')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    print(path, f'{os.path.getsize(path) // 1024} KB')
