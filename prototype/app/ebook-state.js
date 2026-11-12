(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MemoirReaderState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const progressPrefix = 'naemalssami.ui-review.reader.progress.v2.';
  const finite = (value, fallback) => typeof value === 'number' && Number.isFinite(value) ? value : fallback;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function normalizePreferences(value) {
    const input = value && typeof value === 'object' ? value : {};
    return {
      fontSize: Math.round(clamp(finite(input.fontSize, 24), 18, 32)),
      lineHeight: Math.round(clamp(finite(input.lineHeight, 1.9), 1.6, 2.3) * 10) / 10,
      theme: ['white', 'paper', 'night'].includes(input.theme) ? input.theme : 'white',
      fontFamily: ['serif', 'sans'].includes(input.fontFamily) ? input.fontFamily : 'serif',
      turnStyle: ['slide', 'paper', 'scroll'].includes(input.turnStyle) ? input.turnStyle : 'slide',
      reduceMotion: input.reduceMotion === true,
      fitToScreen: input.fitToScreen === true,
    };
  }

  function normalizeLocation(value, sectionCount) {
    const input = value && typeof value === 'object' ? value : {};
    return {
      section: Math.floor(clamp(finite(input.section, 0), 0, Math.max(0, sectionCount - 1))),
      offset: clamp(finite(input.offset, 0), 0, 1),
    };
  }

  function bookKey(title, paragraphs) {
    const text = JSON.stringify([title, paragraphs]);
    let hash = 2166136261;
    for (let index = 0; index < text.length; index++) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `book-${(hash >>> 0).toString(16)}`;
  }

  function chapterHeading(section,index){
    const structured=typeof section?.chapterTitle==='string'&&!!section.chapterTitle.trim();
    return {
      title:structured?section.chapterTitle:['첫 번째 기억','두 번째 기억','세 번째 기억','네 번째 기억','다섯 번째 기억'][index]||`${index+1}번째 기억`,
      number:structured?section.chapterNo:index+1,
      show:!structured||section.paragraphIndex===0,
    };
  }

  function contentsIndex(sections,index){
    const section=sections?.[index];
    if(!section?.chapterTitle)return index;
    const start=sections.findIndex(value=>value.chapterNo===section.chapterNo&&value.chapterTitle===section.chapterTitle&&value.paragraphIndex===0);
    return start<0?index:start;
  }

  function hasResumableProgress(value, sections) {
    if (!value || value.atStart !== false || !Array.isArray(sections) || !sections.length) return false;
    const location = value.location;
    return !!location && Number.isInteger(location.section) && location.section >= 0 && location.section < sections.length
      && Number.isFinite(location.offset) && location.offset >= 0 && location.offset <= 1;
  }

  function sameLocation(first, second) {
    return !!first && !!second && first.section === second.section && Math.abs(first.offset - second.offset) <= 0.08;
  }

  function locationFromBounds(bounds, previous, anchor = 104) {
    const visible = bounds.map((rect, index) => ({...rect,index})).filter((rect) => rect.height > 0);
    if (!visible.length) return normalizeLocation(previous, bounds.length);
    let current = visible[0];
    visible.forEach((rect) => { if (rect.top <= anchor) current = rect; });
    return normalizeLocation({section:current.index,offset:(anchor-current.top)/current.height}, bounds.length);
  }

  return {progressPrefix, normalizePreferences, normalizeLocation, bookKey, chapterHeading, contentsIndex, hasResumableProgress, sameLocation, locationFromBounds};
});
