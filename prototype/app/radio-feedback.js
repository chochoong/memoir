/* Static review only. Uses the existing radio SVG and InterviewVisualState.
 * Load after interview-state.js; setInterviewMode calls RadioFeedback.update(mode).
 * The range is a manual example: no microphone, audio, timer, or network access.
 */
(function () {
  'use strict';

  let scene;
  let controls;
  let range;
  let output;
  let silentButton;
  let description;
  let mode;
  let inputValue = 65;

  function paint() {
    if (!scene) return;
    const visual = window.InterviewVisualState.visualFor(mode);
    const listening = visual.onAir;
    const level = listening ? inputValue / 100 : 0;
    scene.dataset.radioState = visual.radioState;
    scene.dataset.inputLevel = level === 0 ? 'silent' : level <= .5 ? 'low' : 'high';
    scene.style.setProperty('--radio-input-level', String(level));
    scene.style.setProperty('--radio-input-wave-scale', String(.85 + level * .25));
    scene.style.setProperty('--radio-mic-wave-1-opacity', level > 0 ? String(.25 + .65 * level) : '0');
    scene.style.setProperty('--radio-mic-wave-2-opacity', level > .3 ? String((level - .3) * .8) : '0');
    const activeLights = level > 0 ? Math.ceil(level * 5) : 0;
    for (let light = 1; light <= 5; light += 1) {
      scene.style.setProperty(`--radio-meter-${light}-opacity`, light <= activeLights ? '1' : '.18');
    }

    if (!controls) return;
    range.disabled = !listening;
    silentButton.disabled = !listening;
    range.value = String(inputValue);
    output.value = `${inputValue}%`;
    range.setAttribute('aria-valuetext', inputValue === 0 ? '0%, 무음 예시' : `${inputValue}% 입력 크기 예시`);
    description.textContent = listening
      ? '입력 크기에 따라 파형과 레벨만 바뀝니다. 0% 무음에서도 ON AIR는 켜져 있습니다.'
      : mode === 'reading'
        ? '질문 낭독 예시입니다. 헤드폰의 금색 빛과 파형이 켜집니다.'
        : '쉬기와 글쓰기에서는 ON AIR, 파형과 입력 레벨이 꺼집니다.';
  }

  function update(nextMode) {
    mode = nextMode;
    paint();
  }

  function initialise() {
    scene = document.querySelector('#radio-scene');
    if (!scene || !window.InterviewVisualState) return;
    mode = mode || scene.closest('.interview-studio')?.dataset.interviewState || scene.dataset.radioState || 'idle';
    scene.dataset.feedbackReady = 'true';

    const preview = scene.closest('.interview-studio')?.querySelector('details.preview-hint');
    if (preview) {
      controls = document.createElement('fieldset');
      controls.className = 'radio-feedback-controls';
      const legend = document.createElement('legend');
      legend.textContent = '반응 예시';
      const label = document.createElement('label');
      label.htmlFor = 'radio-feedback-level';
      label.textContent = '입력 크기 예시';
      output = document.createElement('output');
      output.setAttribute('for', 'radio-feedback-level');
      output.className = 'radio-feedback-value';
      label.append(output);
      range = document.createElement('input');
      range.id = 'radio-feedback-level';
      range.type = 'range';
      range.min = '0';
      range.max = '100';
      range.step = '1';
      range.value = String(inputValue);
      range.setAttribute('aria-describedby', 'radio-feedback-description');
      range.addEventListener('input', function () {
        inputValue = Math.max(0, Math.min(100, Number(range.value) || 0));
        paint();
      });
      silentButton = document.createElement('button');
      silentButton.type = 'button';
      silentButton.className = 'text-button radio-feedback-silent';
      silentButton.textContent = '무음 예시';
      silentButton.addEventListener('click', function () {
        inputValue = 0;
        paint();
      });
      description = document.createElement('p');
      description.id = 'radio-feedback-description';
      description.className = 'radio-feedback-description';
      const note = document.createElement('p');
      note.className = 'radio-feedback-note';
      note.textContent = '말씀하시는 차례에서 슬라이더를 조작해 보세요. 실제 마이크·음성 재생을 사용하지 않습니다.';
      controls.append(legend, label, range, silentButton, description, note);
      preview.append(controls);
    }
    paint();
  }

  // 실제 마이크 크기(0~1) — srv-interview 가 듣는 동안 매 프레임 넘긴다
  function setLevel(v) { inputValue = Math.max(0, Math.min(100, Math.round((Number(v) || 0) * 100))); paint(); }
  window.RadioFeedback = Object.freeze({ update, setLevel });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise, { once: true });
  } else {
    initialise();
  }
}());
