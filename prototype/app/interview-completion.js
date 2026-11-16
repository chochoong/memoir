(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.InterviewCompletion = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Tab-memory UI preview only. These IDs never represent a server-saved session.
  function createStore({now=()=>new Date().toISOString()}={}) {
    let interviewSequence = 0;
    let storySequence = 0;
    const interviews = new Map();
    const completedInterviews = new Map();
    const stories = new Map();
    const postcards = new Map();

    function beginInterview() {
      const id = `interview-${++interviewSequence}`;
      const createdAt=now();
      if(typeof createdAt!=='string'||!Number.isFinite(Date.parse(createdAt)))throw new TypeError('Invalid interview start time');
      interviews.set(id,createdAt);
      return id;
    }

    function completeInterview({interviewId, answers = [], pendingText = ''}) {
      const existingId = completedInterviews.get(interviewId);
      if (existingId) return {completed:true, created:false, story:stories.get(existingId)};
      if (!interviews.has(interviewId)) return {completed:false, created:false, story:null};
      const copiedAnswers = answers.filter((answer) => typeof answer === 'string' && answer.trim());
      const copiedPending = typeof pendingText === 'string' && pendingText.trim() ? pendingText : '';
      const parts = copiedPending ? [...copiedAnswers, copiedPending] : copiedAnswers;
      if (!parts.length) return {completed:false, created:false, story:null};

      const number = ++storySequence;
      const story = Object.freeze({
        id:`story-${number}`,
        interviewId,
        session_id:`10000000-0000-4000-8000-${String(number).padStart(12, '0')}`,
        created_at:interviews.get(interviewId),
        title:`오늘 나눈 이야기 ${number}`,
        answers:Object.freeze(copiedAnswers),
        pendingText:copiedPending,
        body:parts.join('\n\n'),
        linkedRecordId:null,
      });
      stories.set(story.id, story);
      completedInterviews.set(interviewId, story.id);
      return {completed:true, created:true, story};
    }

    function getStory(id) { return stories.get(id) || null; }
    function pendingStories() { return [...stories.values()].filter((story) => story.linkedRecordId === null); }

    function makePostcard(storyId, records) {
      const story = stories.get(storyId);
      if (!story) return {created:false, story:null, record:null};
      if (postcards.has(storyId)) return {created:false, story, record:postcards.get(storyId)};
      const maximum = records.reduce((max, record) => Number.isSafeInteger(record.id) ? Math.max(max, record.id) : max, 0);
      if (maximum === Number.MAX_SAFE_INTEGER) throw new RangeError('No numeric postcard ID is available.');
      const record = Object.freeze({
        id:maximum + 1,
        session_id:story.session_id,
        created_at:story.created_at,
        category:'childhood',
        title:story.title,
        date:'오늘 · 미리보기',
        description:story.body.replace(/\s+/g, ' ').slice(0, 100),
        body:story.body,
        icon:'pen',
      });
      const linkedStory = Object.freeze({...story, linkedRecordId:record.id});
      stories.set(storyId, linkedStory);
      postcards.set(storyId, record);
      return {created:true, story:linkedStory, record};
    }

    return Object.freeze({beginInterview, completeInterview, getStory, pendingStories, makePostcard});
  }

  return {createStore};
});
