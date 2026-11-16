(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MemoirServiceContract = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Pure adapters only. A job identifies a temporary generation task, and the
  // document below lives in this tab; neither represents a saved server book.
  function object(value, label) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new TypeError(label + ' must be an object');
    }
    return value;
  }

  function array(value, label) {
    if (!Array.isArray(value)) throw new TypeError(label + ' must be an array');
    for (let i = 0; i < value.length; i += 1) {
      if (!Object.prototype.hasOwnProperty.call(value, i)) {
        throw new TypeError(label + ' must not contain missing entries');
      }
    }
    return value;
  }

  function text(value, label, allowEmpty = false) {
    if (typeof value !== 'string' || (!allowEmpty && !value.trim())) {
      throw new TypeError(label + ' must be ' + (allowEmpty ? 'text' : 'nonempty text'));
    }
    return value;
  }

  function clone(value) {
    if (Array.isArray(value)) return value.map(clone);
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, clone(entry)]));
    }
    return value;
  }

  function turns(value, label) {
    array(value, label);
    if (value.some(turn => !Number.isInteger(turn) || turn < 0)) {
      throw new TypeError(label + ' must contain nonnegative turn numbers');
    }
    return value.slice();
  }

  function postcardView(session, postcard, presentation = {}) {
    object(session, 'session');
    object(postcard, 'postcard');
    object(presentation, 'presentation');
    text(session.session_id, 'session.session_id');
    text(postcard.text, 'postcard.text');
    if (postcard.title !== undefined && postcard.title !== null) text(postcard.title, 'postcard.title', true);
    const title = [postcard.title,session.postcard_title,session.title]
      .find(value => typeof value === 'string' && value.trim()) || '제목 없는 이야기';
    const display = clone(presentation);
    return {
      id:display.id === undefined ? session.session_id : display.id,
      session_id:session.session_id,
      elder_id:session.elder_id,
      title,
      body:postcard.text,
      created_at:postcard.created_at ?? session.created_at,
      category:display.category,
      icon:display.icon,
      date:display.date,
      description:display.description,
      presentation:display,
      sourceSession:clone(session),
      sourcePostcard:clone(postcard),
    };
  }

  function bodyLines(value) {
    // Keep the original nonblank text. Reader positions use these paragraphs.
    if (typeof value === 'string') return value.split(/\r\n|\r|\n/).filter(line => line.trim());
    array(value, 'body');
    value.forEach(line => text(line, 'body paragraph', true));
    return value.filter(line => line.trim());
  }

  function plainSections(body) {
    return body.map((paragraph, index) => ({
      text:paragraph,
      chapterTitle:null,
      chapterNo:null,
      paragraphIndex:index,
      sentences:[{text:paragraph,turns:[]}],
    }));
  }

  function chapterSections(chapters) {
    const sections = [];
    let complete = chapters.length > 0;
    chapters.forEach(chapter => {
      object(chapter, 'chapter');
      text(chapter.title, 'chapter.title', true);
      if (!Number.isInteger(chapter.no) || chapter.no < 1) throw new TypeError('chapter.no must be a positive integer');
      const paragraphs = array(chapter.paragraphs, 'chapter.paragraphs');
      if (chapter.status !== 'ready' || !chapter.title.trim() || !paragraphs.length) complete = false;
      paragraphs.forEach((paragraph, paragraphIndex) => {
        object(paragraph, 'paragraph');
        const sentenceValues = array(paragraph.sentences, 'paragraph.sentences');
        if (!sentenceValues.length) throw new TypeError('paragraph.sentences must not be empty');
        const sentences = sentenceValues.map(sentence => {
          object(sentence, 'sentence');
          return {
            text:text(sentence.text, 'sentence.text'),
            turns:turns(sentence.turns === undefined ? [] : sentence.turns, 'sentence.turns'),
          };
        });
        sections.push({
          text:sentences.map(sentence => sentence.text).join(' '),
          chapterTitle:chapter.title,
          chapterNo:chapter.no,
          paragraphIndex,
          sentences,
        });
      });
    });
    return {sections,complete};
  }

  function sourceView(value) {
    if (value === undefined) return [];
    array(value, 'sources').forEach(source => {
      object(source, 'source');
      if (!Number.isInteger(source.sentence) || source.sentence < 0) throw new TypeError('source.sentence must be a nonnegative integer');
      turns(source.turns, 'source.turns');
    });
    return clone(value);
  }

  function verificationView(value) {
    if (value === undefined || value === null) return {state:'not_run'};
    object(value, 'verification');
    const verification = clone(value);
    if (verification.state === undefined || verification.state === null || verification.state === '') {
      verification.state = 'not_run';
    } else {
      text(verification.state, 'verification.state');
    }
    return verification;
  }

  function memoirView(result, context = {}) {
    object(result, 'result');
    object(context, 'context');
    const statuses = ['ready','insufficient_material','partial','incomplete','failed','needs_context','needs_confirmation','not_final'];
    if (!statuses.includes(result.status)) throw new TypeError('Unknown memoir result status');
    text(result.title, 'result.title', true);
    if (result.body !== undefined) text(result.body, 'result.body', true);
    const sources = sourceView(result.sources);
    const verification = verificationView(result.verification);
    let sections;
    let complete;
    if (Object.prototype.hasOwnProperty.call(result, 'chapters')) {
      const chapters = array(result.chapters, 'result.chapters');
      const adapted = chapterSections(chapters);
      sections = adapted.sections;
      complete = adapted.complete;
      if (result.status === 'ready' && !chapters.length) throw new TypeError('Ready result must have chapters');
    } else {
      text(result.body, 'result.body', true);
      sections = plainSections(bodyLines(result.body));
      complete = sections.length > 0;
    }
    if (result.status === 'ready' && (!result.title.trim() || !sections.length)) {
      throw new TypeError('Ready result must contain a title and text');
    }
    return {
      title:result.title,
      body:sections.map(section => section.text),
      sections,
      sourceResult:clone(result),
      sources,
      verification,
      elder_id:context.elder_id,
      job_id:context.job_id,
      uiStyle:context.uiStyle,
      style:result.style,
      canRead:result.status === 'ready' && complete && sections.length > 0,
      edited:false,
      sourceAlignment:'original',
      preview:context.preview === true,
      storage:'tab-memory',
    };
  }

  function editMemoir(document, update) {
    object(document, 'document');
    object(update, 'update');
    const title = text(update.title, 'edited title', true);
    const body = bodyLines(update.body);
    const next = clone(document);
    const changed = title !== document.title || body.length !== document.body.length
      || body.some((paragraph, index) => paragraph !== document.body[index]);
    if (!changed) return next;
    next.title = title;
    next.body = body;
    next.sections = plainSections(body);
    next.edited = true;
    next.sourceAlignment = 'stale';
    // The immutable source snapshot remains available for comparison, but its
    // sentence references cannot substantiate the edited title or paragraphs.
    next.sources = [];
    next.verification = {state:'not_run'};
    next.canRead = memoirView(document.sourceResult).canRead && !!title.trim() && body.length > 0;
    return next;
  }

  function jobView(response, context = {}) {
    object(response, 'job response');
    object(context, 'context');
    text(response.job_id, 'job_id');
    if (!['running','done','failed'].includes(response.status)) throw new TypeError('Unknown memoir job status');
    const job = {
      job_id:response.job_id,
      status:response.status,
      stage:response.stage,
      style:response.style,
      run:clone(response.run),
      chapter:response.chapter,
      chapters:response.chapters,
      elapsed:response.elapsed,
      code:response.code,
      detail:response.detail,
      canRead:false,
      document:null,
    };
    if (response.status === 'done') {
      const document = memoirView(response.result, {...context,job_id:response.job_id});
      job.result = clone(response.result);
      job.document = document;
      job.canRead = document.canRead;
    }
    return job;
  }

  return {postcardView,memoirView,editMemoir,jobView};
});
