(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-voice — 질문을 읽어 주는 목소리 고르기
       · 서버(develop 11dcd93): POST /api/sessions · POST /api/links 에 voice = "default" | "young"
         default = 지금 목소리(Gemini Kore) · young = 젊고 밝은 여성 목소리(Gemini Leda). 그 밖의 값은 422.
       · 「내 이야기」 · 「초대 주소 만들기」 화면에서 고른다. 고른 값은 이 기기에 기억해 다음에도 그대로.
       · 미리 듣기는 없다 (서버에 샘플 API 가 없고, 들을 때마다 유료 낭독이 든다).
       · 서버가 Gemini 로 읽을 때만 목소리가 달라진다(TTS_PROVIDER=gemini). Azure 로 읽으면 늘 같은 목소리.
     ═══════════════════════════════════════════════════════════════ */
  const VOICES = [
    {key: 'default', label: '차분한 목소리', sub: '기본'},
    {key: 'young', label: '밝고 젊은 목소리', sub: ''},
  ];
  const KEY = 'memoir.voice';
  const valid = (k) => VOICES.some((v) => v.key === k);
  function get() { try { const k = localStorage.getItem(KEY); return valid(k) ? k : 'default'; } catch (_) { return 'default'; } }
  function set(k) { if (!valid(k)) return; try { localStorage.setItem(KEY, k); } catch (_) {} }
  const label = (k) => (VOICES.find((v) => v.key === k) || VOICES[0]).label;

  /** 고르는 칸 — 주제 고르기와 같은 동그란 칩 모양 (start-choice 의 .sc-chips) */
  function fieldset(step) {
    const now = get();
    return `<fieldset class="sc-voice"><legend>${step ? `<span class="sc-step">${step}</span>` : ''}질문을 읽어 줄 목소리</legend>
      <div class="sc-chips" role="group" aria-label="목소리">${VOICES.map((v) => `<label class="sc-chip"><input type="radio" name="voice" value="${v.key}" ${v.key === now ? 'checked' : ''}><span>${v.label}${v.sub ? `&nbsp;<small>· ${v.sub}</small>` : ''}</span></label>`).join('')}</div>
      <p class="sc-voice-note">말씀을 들려주실 분이 편하게 들으실 목소리를 골라 주세요.</p></fieldset>`;
  }
  /** 폼에서 고른 값을 읽고 기억한다 */
  function fromForm(form) {
    const k = form?.querySelector('input[name="voice"]:checked')?.value;
    if (valid(k)) set(k);
    return get();
  }
  // 칩을 누르는 순간 기억 — 다른 화면(옛 「이 기기에서 시작하기」)에서 시작해도 같은 목소리
  document.addEventListener('change', (e) => { if (e.target.matches?.('input[name="voice"]')) set(e.target.value); });

  window.MemoirVoice = {VOICES, get, set, label, fieldset, fromForm};
}());
