(function () {
  'use strict';

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Set();
  const byElement = new WeakMap();
  const pointers = new Map();
  let keyboardPress = null;
  let lastScreen = document.querySelector('[data-screen]:not([hidden])')?.dataset.screen;

  function cancel(element) {
    const animation = byElement.get(element);
    if (animation) {
      animation.cancel();
      running.delete(animation);
      byElement.delete(element);
    }
  }

  function animate(element, frames, duration, easing = 'linear') {
    cancel(element);
    if (!element.isConnected || reducedMotion.matches || document.hidden || typeof element.animate !== 'function') return;
    const animation = element.animate(frames, {duration, easing});
    byElement.set(element, animation);
    running.add(animation);
    const finish = () => {
      running.delete(animation);
      if (byElement.get(element) === animation) byElement.delete(element);
    };
    animation.finished.then(finish, finish);
  }

  function targetFor(eventTarget) {
    if (!(eventTarget instanceof Element)) return null;
    const control = eventTarget.closest('button, .mobile-nav a[data-nav], .side-nav a[data-nav], label.record-card');
    if (!control || control.matches(':disabled, [aria-disabled="true"], [data-motion="off"]') || control.closest('[inert]')) return null;
    // Reading owns its own animation and reduced-motion preference.
    if (control.closest('.ebook-reader, .ebook-sheet')) return null;
    if (control.matches('.mobile-nav a[data-nav]')) {
      const element = control.querySelector(':scope > .icon');
      return element ? {control, element, nav: true} : null;
    }
    // Desktop labels remain still, just like the mobile labels.
    if (control.matches('.side-nav a[data-nav]')) return null;
    return {control, element: control.querySelector(':scope .ml-cover') || control, nav: false};
  }

  function begin(target) {
    if (!target || reducedMotion.matches) return null;
    cancel(target.element);
    const original = target.element.style.scale;
    const base = Number.parseFloat(getComputedStyle(target.element).scale) || 1;
    const factor = target.nav ? .91 : .975;
    target.element.style.scale = String(base * factor);
    target.element.classList.add('motion-press');
    return {...target, original, base, pressedScale: base * factor};
  }

  function release(press, immediate = false) {
    if (!press) return;
    if (press.original) press.element.style.scale = press.original;
    else press.element.style.removeProperty('scale');
    press.element.classList.remove('motion-press');
    if (immediate) {cancel(press.element);return;}
    const overshoot = press.nav ? 1.055 : 1.006;
    animate(press.element, [
      {scale: String(press.pressedScale), offset: 0},
      {scale: String(press.base * overshoot), offset: .48},
      {scale: String(press.base * .995), offset: .78},
      {scale: String(press.base), offset: 1},
    ], press.nav ? 165 : 210);
  }

  document.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.isPrimary === false) return;
    const target = targetFor(event.target);
    if (!target || [...pointers.values()].some(press => press.element === target.element)) return;
    const press = begin(target);
    if (press) pointers.set(event.pointerId, {...press, x: event.clientX, y: event.clientY});
  }, {passive: true});

  function releasePointer(event) {
    const press = pointers.get(event.pointerId);
    pointers.delete(event.pointerId);
    release(press);
  }
  window.addEventListener('pointerup', releasePointer, {passive: true});
  window.addEventListener('pointercancel', releasePointer, {passive: true});
  window.addEventListener('pointermove', event => {
    const press = pointers.get(event.pointerId);
    if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 12) releasePointer(event);
  }, {passive: true});

  document.addEventListener('keydown', event => {
    if (event.repeat || !['Enter', ' '].includes(event.key)) return;
    const target = targetFor(event.target);
    if (!target || (target.control.tagName === 'A' && event.key === ' ')) return;
    release(keyboardPress, true);
    keyboardPress = begin(target);
  });
  document.addEventListener('keyup', event => {
    if (['Enter', ' '].includes(event.key)) {
      release(keyboardPress);
      keyboardPress = null;
    }
  });
  document.addEventListener('focusout', event => {
    if (keyboardPress?.control.contains(event.target)) {
      release(keyboardPress);
      keyboardPress = null;
    }
  });

  function resetPresses() {
    pointers.forEach(press => release(press, true));
    pointers.clear();
    release(keyboardPress, true);
    keyboardPress = null;
  }
  window.addEventListener('blur', resetPresses);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) resetPresses();
  });
  reducedMotion.addEventListener('change', () => {
    if (!reducedMotion.matches) return;
    resetPresses();
    running.forEach(animation => animation.cancel());
    running.clear();
  });

  window.addEventListener('memoir:screen', event => {
    const screen = event.detail?.screen;
    if (lastScreen === screen) return;
    lastScreen = screen;
    if (!screen || screen === 'reader') return;
    const panel = [...document.querySelectorAll('[data-screen]')].find(element => element.dataset.screen === screen && !element.hidden);
    if (panel) animate(panel, [
      {opacity: .65, translate: '0 8px'},
      {opacity: 1, translate: '0 0'},
    ], 180, 'cubic-bezier(.2,.7,.2,1)');
  });

  // Observe presentation state, without wrapping showModal/close or delaying focus.
  const dialogs = '.review-dialog, .generation-dialog, .memoir-login-dialog, .postcard-dialog';
  new MutationObserver(records => {
    records.forEach(record => {
      const element = record.target;
      if (record.attributeName === 'open' && element.matches(dialogs) && element.open) {
        animate(element, [
          {opacity: .4, translate: '0 14px', scale: '.985'},
          {opacity: 1, translate: '0 0', scale: '1'},
        ], 220, 'cubic-bezier(.2,.7,.2,1)');
      } else if (record.attributeName === 'aria-pressed' && element.getAttribute('aria-pressed') === 'true') {
        const marker = element.querySelector('.style-check, .mlg-choice-check');
        if (marker) animate(marker, [{scale: '.8'}, {scale: '1.04', offset: .6}, {scale: '1'}], 190);
      }
    });
  }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['open', 'aria-pressed']});

  document.addEventListener('change', event => {
    if (event.target.matches?.('input[data-record]:checked')) {
      animate(event.target, [{scale: '.84'}, {scale: '1.04', offset: .6}, {scale: '1'}], 190);
    }
  });
})();
