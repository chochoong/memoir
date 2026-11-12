(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-core — 서버와 이야기하는 부분 (운영 index.html v0.54 에서 그대로 옮김)
       · CONFIG · api 는 v0.54 와 같은 이름 · 같은 경로다. 고칠 일이 있으면 여기 한 곳에서.
       · 신원은 msid 쿠키(로그인)만 쓴다. 서버가 X-User-Id 를 더 이상 읽지 않는다 (develop 0a5227c).
       · ?authMock=ok 로 열면 서버 없이 로그인 흐름만 흉내 낸다 (실제 계정을 만들지 않는다).
     ═══════════════════════════════════════════════════════════════ */
    const CONFIG = {
    // 화면 아래와 개발용 패널에 그대로 찍힌다. 「고친 게 반영이 안 된 것 같다」는
    // 대부분 예전 파일이 열려 있는 경우라서, 눈으로 확인할 자리를 만들어 둔다.
    version: 'v0.60 · 2026-11-12 (시안 2차 B안 화면으로 교체 — 로그인 · 화자 · 인터뷰 · 엽서 · 자서전 · 책장 · 공유 · 초대 링크 서버 연결)',

    // 이 화면을 백엔드가 직접 서빙하면(web/ 폴더) 빈 문자열 그대로 둔다.
    // 다른 포트에서 열어 시험할 때만 'http://127.0.0.1:8010' 처럼 채운다.
    // (그때는 백엔드 .env 의 ALLOWED_ORIGINS 에 이 화면 주소를 넣어야 한다)
    apiBase: '',
    userId: 'dev-user',          // auth.mode 'dev' 에서만 보낸다 (백엔드 X-User-Id). 'session' 에서는 보내지 않는다

    session: {
      title: '',                 // 비우면 날짜로 자동 생성
      seed: '',                  // 회차를 여는 씨앗 문장(0번 조각). 비워도 된다
                                 // 예전 백엔드에서는 이 필드 이름이 postcard 였다 (2cbb124 에서 바뀜)
      pace: 'normal',            // fast(T2 3초) / normal(5초) / slow(7초)
      max_turn: 0,               // 0 = 제한 없음. 끝은 AI 의 close 판단이 정한다
      // 「녹음 정지」를 누르기 직전에 하신 말씀을 확정하고 닫는다.
      // 끄면 말을 마치자마자 누른 말씀이 엽서에서 빠진다 (confirmLastSpeech 주석 참조).
      confirmBeforeStop: true,
      confirmWaitMs: 12000,      // 그 확정을 기다리는 상한
    },

    // ── 1차 인터뷰 흐름 (업무지시서 03 v1.0) ─────────────────────
    //   테마 · 구체 주제 · 보조 사진 → 음성 / 키보드 → 「인터뷰 마치기」 → 나눈 이야기 읽기
    // 이 흐름에서는 엽서를 만들지 않는다 — 엽서 요청 · 임시 정리(polish)를 부르지 않는다.
    // 엽서 기능은 지우지 않았다. flow 를 'postcard' 로 두거나 주소 뒤에 ?flow=postcard 를
    // 붙이면 예전 흐름(녹음 → 엽서)으로 돈다.
    interview: {
      flow: 'interview',         // 'interview' (1차 기본) | 'postcard' (예전 흐름)
      themes: ['가족', '나', '취미'],
      // 낱말 카드 고르기. true 면
      //   · 「이 기기에서 시작」 → 낱말 카드 → 카드를 누르면 그 낱말로 인터뷰 시작
      //   · 어르신이 링크를 열고 「이야기 시작하기」 → 낱말 카드 → 카드를 누르면 인터뷰 시작
      //     고른 낱말은 POST /api/i/start 에 { topic } 으로 싣는다. **서버가 아직 이 칸을 읽지 않는다** —
      //     읽기 전까지 링크 회차의 주제는 링크를 만들 때 적은 구체 주제다.
      // 준비 화면에 적은 구체 주제는 「자녀가 궁금한 낱말」 맨 앞 카드로 나온다. false 면 예전처럼 바로 시작한다.
      wordPick: true,
      // 기본 낱말 카드. 묶음(group)마다 이름 단추가 하나씩 생기고, 누르면 그 묶음 카드가 나온다
      wordDefaults: [
        { group: '어린 시절',  words: ['고향', '우리 집', '골목', '동무', '첫 기억', '별명', '꾸중', '심부름'] },
        { group: '학교',      words: ['학교 가는 길', '선생님', '도시락', '운동회', '소풍', '졸업'] },
        { group: '젊은 날',    words: ['첫 월급', '첫 직장', '상경', '연애편지', '맞선', '결혼식'] },
        { group: '가정',      words: ['신혼집', '첫아이', '이사', '가장', '살림', '명절'] },
        { group: '일',        words: ['내 일터', '손재주', '고생', '보람', '동료'] },
        { group: '요즘',      words: ['손주', '취미', '건강', '친구', '하루 일과', '소원'] },
        { group: '살림 지혜',  words: ['음식 레시피', '바느질', '단추 달기', '뜨개질', '이불 손질', '화분 가꾸기', '텃밭 가꾸기', '얼룩 빼는 법', '옷 오래 입는 법', '장 보는 요령'] },
        { group: '집안 내력',  words: ['집안 내력', '조상 이야기', '족보', '고향 마을', '내 부모님', '이사 다닌 곳'] },
        { group: '물건과 사연', words: ['오래된 사진', '반지', '시계', '편지', '살림살이', '물려줄 물건'] },
        { group: '배운 것',    words: ['돈 관리', '아끼는 법', '사람 보는 눈', '힘들 때 버틴 법', '후회되는 일', '잘한 결정', '부부로 사는 법', '자식 키우며'] },
        { group: '말과 노래',  words: ['말버릇', '속담', '자장가', '어릴 적 노래', '고향 사투리', '아이 달래던 말'] },
        { group: '놀이와 풍습', words: ['공기놀이', '고무줄놀이', '딱지치기', '명절 풍습', '제사', '차례', '집안 행사'] },
        { group: '건강 습관',  words: ['민간요법', '생활 습관', '몸 관리 비결'] },
        { group: '마음 전하기', words: ['못다 한 말', '고마웠던 순간', '손주에게 할 말', '꼭 지킬 것'] },
      ],
      // 서버 C1 §1 의 theme 값 (feature/theme-interview 8e55163). 모르는 값은 422.
      themeCodes: { '가족': 'family', '나': 'self', '취미': 'hobby' },
      // 준비 화면에서 테마를 고르나. false 면 「궁금한 주제」 하나만 받는다 — 서버는 theme 없이도 연다
      // (StartReq · LinkReq 의 theme 은 선택). 회차 제목(title)은 주제를 쓴다.
      themePick: false,
      // C1 §1 의 theme · topic 칸에도 싣는다. 이 칸이 없는 예전 서버는 모르는 칸을 그냥 버리므로
      // 켜 둬도 안전하다 (StartReq 에 extra 금지가 없음을 확인).
      sendC1: true,
      topicMax: 60,
      // 테마 이름 · 주제를 **서버가 돌려주는 칸**에도 싣는다 — 「나눈 이야기」 가 서버 값을 읽어 보여 주는 자리다.
      // C1 §1 의 theme · topic 은 아직 DB 에 저장되지 않아 /record 로 돌아오지 않는다 (SV-06 에서 정함).
      // 그래서 테마 이름은 title, 주제는 seed(0번 조각) 에도 함께 싣는다. 서버는 seed 가 topic 과 같으면 한 번만 쓴다.
      // SV-06 에서 /record 가 theme · topic 을 주기 시작하면 여기를 { theme: 'theme', topic: 'topic' } 로 바꾼다.
      startKeys: { theme: 'title', topic: 'seed' },
      keyboard: true,            // 마이크 옆 「글로 쓰기」. 마이크를 못 쓰면 글로만 진행한다
      // 앞서 말씀하신 소리가 서버에 남아 있으면(audio_bytes) 그 말씀이 먼저 확정될
      // 때까지 글을 보내지 않는다 — 지금 서버는 한 턴에 소리가 있으면 글을 버린다
      // (controller._transcribe). 이 시간이 지나도 안 비면 「말로 하기」로 안내한다.
      voiceDrainMs: 9000,
      // 내용 확인. 마지막 답변이 DB 에 닿기 전일 수 있어 몇 번 다시 읽는다.
      recordTimeoutMs: 15000,
      recordWaitMs: 8000,
      recordRetryMs: 1000,
    },

    // ── 보관함 ────────────────────────────────────────────────────
    // GET /api/sessions (main.py list_sessions). 못 읽으면 503 이 온다 —
    // 서버가 일부러 그렇게 둔다. 빈 목록으로 답하면 화면이 「기록이 없습니다」
    // 라고 말하게 되고, 그건 어르신에게 조각이 사라졌다는 말이 되기 때문이다.
    archive: {
      // 서버 상한이 100 이다 (최충 회신 2026-10-22). 20 이면 기록이 21개만 넘어도 오래된 것이 안 보였다.
      // 커서 방식 「더 보기」 는 정렬 작업 때 서버와 같이 붙인다
      limit: 100,
      // 확정된 회차만 보여준다 (FR-AR-501). 아직 안 끝난 회차는 목록에 넣지 않는다.
      closedOnly: true,
      // 목록 응답에 엽서 제목·본문이 실리면 true 로 바꾼다 — 그때 카드에 본문
      // 두 줄이 같이 나온다. 지금은 session 표 컬럼만 와서 끌 수밖에 없다.
      previewInList: false,
      // 목록 응답의 「저장된 엽서 제목」 칸 이름 (엽서 목록 제목 업무지시서 v1.0 §3 의 제안 이름).
      // 최충 님 확정 (feature/theme-interview 5a9fddd) — 모든 회차에 늘 있고, 엽서가 없거나 006 이전 엽서면 null.
      // 서버는 저장값 그대로 준다(공백 정리 없음). 정리는 화면이 한다.
      postcardTitleField: 'postcard_title',
      // 아직 서버에 없는 칸 — 이름이 정해지면 여기만 고친다 (연결 점검판이 이 이름으로 찾는다)
      cursorField: 'next_cursor',   // 「더 보기」 다음 쪽 표시 (6-C1 §4 · 정렬 작업 때)
      timeField: '',                // 사건 시점 칸 (6-C1 §3 · 대원 님 DW-12 형식 대기) — 미정이면 빈 값
      // 연대기순은 서버가 정렬한다 (6-C1 §4). 그 요청을 무엇으로 하는지 (예: 'order=chrono') — 미정이면 빈 값.
      // timeField · chronoQuery 가 둘 다 정해지면 「일어난 순」 탭이 나타난다. 미리 보기: ?listMock=chrono
      chronoQuery: '',
      // 서버 없이 목록 제목 규칙을 볼 때: ?listMock=title (여러 경우) · old (칸 없는 예전 응답)
      //   · empty (빈 목록) · fail (503). 예시일 때는 화면 위에 「예시 목록」 이 뜬다.
      mock: '',
      // 목록이 이 안에 안 오면 「불러오지 못했다」로 접는다. 예전에는 서버가 답하지
      // 않으면 불러오는 화면에 갇혀 돌아갈 버튼도 없었다.
      timeoutMs: 15000,
    },

    // ── 자서전 초안 (업무지시서 04 v1.1 · 연결 규격 C1 v1.1) ───────────
    // POST /api/memoirs/preview 에 엽서 3~5장을 보내고, 다 쓸 때까지 한 번 기다린다.
    // 서버에 붙었다 (main 66acce1 · backend-agent/app/session/memoir.py). 실패 문구는
    // 서버의 _MEMOIR_SAYS 와 같다.
    memoir: {
      path: '/memoirs/preview',
      // 엽서가 있는 회차의 session_id(UUID) 를 담는다 (C1 v1.1). 엽서는 회차당 한
      // 장이라 따로 ID 가 없고, postcard 표의 키가 session_id 다.
      idsField: 'session_ids',
      min: 3,
      // 상한 · 요청 모양은 **서버가 정한다** (PR #14 · 501f13e). 화자별 목록(?elder_id=) 응답의
      //   memoir_max — null 이면 상한 없음(다섯 단계 · 같은 화자 전체 선택 후 제외 · 'exclude'),
      //   숫자면 그 개수까지 고른 것('ids'). 다섯 단계는 시험 대상 계정만 써서 사람마다 다르다 (태헌 10-28).
      // 아래 max · requestShape 는 그 칸이 없는 서버(예전 · 개발 모드)에서만 쓴다 — 서버 MEMOIR_MAX_SESSIONS 와 같게.
      // 6개 이상이면 「모두 고르기 · 모두 빼기」 가 나온다.
      max: 5,
      // 요청 모양. 'ids' = {session_ids, style} (지금) ·
      // 'exclude' = {elder_id, exclude_session_ids, style} — 최종 정책 「같은 화자 전체 선택 후 제외」 (7-C1 §4 · 태헌 10-26).
      // 'exclude' 면 고르기 화면이 **처음부터 전부 골라진 채** 열리고, 넣지 않을 것만 눌러 뺀다
      requestShape: 'ids',
      // 시작하고 나중에 받기 (PR #14 · 최충 10-28). 다섯 단계는 몇 분 걸리고(39회차 약 6분)
      // Cloudflare 가 100초 넘는 응답을 끊는다 → POST /memoirs 202 {job_id} · GET /memoirs/{job_id} 를 몇 초마다.
      // 'auto' — 작업 주소가 없는 서버(404 · 405, code 없음)면 예전 기다리는 요청(path)으로. 'preview' — 늘 예전 길
      flow: 'auto',
      jobPath: '/memoirs',
      pollMs: 4000,
      // 작업 방식에서 화면이 기다리는 끝. 서버 전체 상한 30분(MEMOIR_PIPE_TOTAL_TIMEOUT=1800)보다 길게
      jobMaxMs: 35 * 60 * 1000,
      // 고를 엽서 수 (서버 상한 100). 서버에 「엽서 있는 회차만」(?has_postcard=1) 을 달라고 하므로
      // 최근 회차에 엽서 없는 회차가 많아도 밀려나지 않는다. (v0.26 에서 잠깐 100 으로 늘렸다가 되돌림)
      listLimit: 100,
      // 엽서 그림(썸네일)을 한 번에 몇 장씩 받나. 100장을 한꺼번에 받지 않는다
      thumbParallel: 6,
      // 화면 쪽 안전장치일 뿐이다. 모델 호출 제한(서버 MEMOIR_TEXT_TIMEOUT)을 넘기면 서버가 504 로
      // 먼저 답한다. 연결이 걸려 버렸을 때만 여기서 접는다 — **서버 제한보다 길어야 한다.**
      // 운영 .env 는 100초 (최충 10-28 · 기본 20초). 60초였을 때는 서버가 61~100초에 만든 글을 화면이 먼저 버렸다.
      // 예전 기다리는 요청(path)에만 쓴다. 작업 방식은 jobMaxMs
      timeoutMs: 120000,
      // '' 이면 실제 서버를 부른다 (기본). 서버 없이 화면만 볼 때 예시 응답을 고른다:
      //   ready · 400 · 404 · 422 · 502 · 503 · 504 · invalid · timeout · insufficient · unsupported(400 문체)
      // 주소 뒤에 ?memoirMock=ready 처럼 붙여도 된다. 예시일 때는 화면 위에 「예시 응답 모드」가 뜬다.
      mock: '',
      mockDelayMs: 1500,
      // 장 · 문단 형식 (자서전 고도화 v1.0 §7.1 의 제안 — 아직 서버 API 에 없다).
      // 응답에 chapters 가 있으면 장 읽기로, 없으면 예전처럼 body 한 줄 한 문장으로 읽는다.
      // 예시 (7-C1 모양): ?memoirMock=chapters · partial · nodata · html · badshape · mismatch(다른 회차의 결과)
      //       (독립 실행 ② 모양): proposal · verified · badref     · code 붙은 오류: 502:invalid_model_output 등
      chapters: {
        // 일부 장 실패를 보여 줄까 — **태헌 님 10-26 결정: A (전체 미완료 안내)**. 서버도 장 내용 없이 503 incomplete 를 준다.
        // B 는 비교용으로 남겨 둔다 (?memoirPartial=show). 서비스에서는 켜지 않는다.
        //   false (A · 기본) 완성본으로 열지 않고 「일부 장을 만들지 못했어요」
        //   true  (B)        만든 장만 보여 주고 위에 「○장을 만들지 못했어요. 지금 보이는 글은 자서전의 일부예요」
        // 주소 뒤 ?memoirPartial=show 로 B 를 미리 볼 수 있다
        showPartial: false,
        // ② 모양(독립 실행 파일)의 generation_state 뜻
        ok: ['generated'],
        lack: ['insufficient_material', 'no_material'],
        partial: ['partial'],
      },
    },

    // ── 사진 ──────────────────────────────────────────────────────
    // 백엔드 POST /api/photos 에 연결되어 있다 (main.py upload_photo).
    // 서버에 DB 가 없으면 503 이 오는데, 그래도 사진은 이 화면 안에서 엽서에 들어간다.
    photo: {
      upload: true,              // false 면 서버에 올리지 않고 화면 안에서만 쓴다
      maxUploadMB: 20,           // 백엔드 .env 의 MAX_UPLOAD_MB 와 맞춘다. 넘으면 줄여서 올린다
      previewPixel: 1600,        // 화면 미리보기용 긴 변. 서버는 따로 1024px 로 만든다

      // ── 사진을 보고 먼저 물어보기 (기획서 §2 사진 분석 에이전트) ──
      // 백엔드가 **사진을 올리는 그 자리에서** 분석을 걸어 둔다 (photo.analyze_later).
      // 그래서 고르는 순간 올려 두면, 시작을 누를 때쯤 단서가 준비되어
      // **여는 말부터 사진 질문**이 된다.
      uploadOnPick: true,       // 고르는 순간 올린다 (분석 시간을 벌어 준다)
      sendIdOnCreate: true,     // 회차를 열 때 photo_id 를 함께 보낸다
      waitBeforeStartMs: 8000,  // 시작을 눌렀을 때 올리는 중이면 이만큼까지 기다린다
    },

    // ── 엽서 글 (기획서 §4 카드 작성 에이전트) ────────────────────
    // 백엔드 main.py 의 make_postcard 에 연결되어 있다.
    //   POST /api/sessions/{id}/postcard → { url, title, text, caption, width, height, bytes }
    // 기다리는 요청이라 수 초 걸린다. 그동안 화면은 「정리 중」에 머문다.
    // 실패하면 **안내 화면**을 띄운다 — 자료가 부족하면 「엽서를 만들 만큼 이야기가 모이지 않았어요」,
    // 그 밖의 실패(키 · 글꼴 · 시간 초과 · AI 답 이상)는 「엽서를 만들지 못했어요」 + 다시 만들기.
    // 예전에는 화면 안의 임시 정리(polish)로 만든 엽서를 대신 보여 줘서, 실패가 사용자에게 보이지 않았다.
    card: {
      server: true,              // false 로 두면 언제나 임시 정리만 쓴다
      path: '/sessions/{id}/postcard',
      method: 'POST',
      waitMs: 40000,             // 「굽는 중」이라고 할 때 기다리는 상한
      pollMs: 1500,              // /record 를 다시 보는 간격
      retryMs: 8000,             // 기다리는 동안 다시 구워 보게 하는 간격
      useServerImage: true,      // 저장할 때 서버가 구운 그림을 쓴다 (없으면 화면에서 그린다)
      // 서버 엽서가 실패했을 때 예전처럼 화면 안의 임시 정리 엽서로 대신할까. 기본은 끔 —
      // 실패를 엽서처럼 꾸미지 않는다. 서버 없이 보는 비상 화면(offlineDemo)은 이 값과 상관없이 임시 정리다.
      localFallback: false,
    },

    // ── 화면 문구·버튼 ────────────────────────────────────────────
    // 버튼 이름은 여기서만 바꾼다. 코드 안을 뒤질 필요가 없다.
    ui: {
      labels: {
        start:   '녹음 시작',
        pause:   '일시정지',
        resume:  '이어서 말하기',
        stop:    '녹음 정지 · 엽서 만들기',   // 예전 흐름(?flow=postcard) — 닫으면 바로 엽서를 만든다
        end:     '인터뷰 마치기',          // 1차 흐름의 정지 버튼 — 닫기만 한다. 엽서는 나눈 이야기에서 따로
        card:    '엽서 만들기',            // 나눈 이야기 — POST /postcard (서버 설계: 닫힐 때 자동으로 만들지 않는다)
        cardView: '엽서 보기',             // 이미 엽서가 있는 회차
        cardBusy: '엽서를 만드는 중이에요…',
        begin:   '이 기기에서 시작',       // 1차 흐름의 시작 버튼
        reading: '읽어 드리는 중…',
        skip:    '소리 없이 넘어가기',
        done:    '다 말했어요',
        save:    '엽서 저장',
        exit:    '마치기',
      },
      // 일시정지 버튼. 팀 논의로 뺐다 (2026-09-23).
      // true 로 바꾸면 그대로 살아난다 — 서버에는 일시정지가 없어서, 멈춘 동안
      // 아주 짧은 무음을 2초마다 올려 회차를 붙들어 두는 방식이다 (setHold 참조).
      showPauseButton: false,
      // 「다 말했어요」(다음 질문으로 즉시 넘어가기). 기본은 숨김 —
      // 말을 마치고 3초 기다리면 저절로 넘어가므로 어르신께는 버튼이 하나 더
      // 있는 셈이 된다. 개발용 패널에는 항상 있다.
      showDoneButton: false,
      // 녹음 화면(대화 · 정리 중)만 앱 모양으로 두고, 준비 · 내용 확인 · 지난 이야기 · 자서전 ·
      // 엽서는 넓은 웹 화면으로 그린다 (PC 처럼 폭이 760px 이상일 때). false 면 전부 앱 모양.
      webLayout: true,
      // 책장 넘김 시안. 화면이 바뀔 때만 책장이 넘어간다 (대화 중 버튼 · 녹음 화면끼리는 넘기지 않음).
      // 기본은 꺼 둔다 — 업무지시서 03 에서 「전체 UI 재디자인」 은 1차 제외라 팀 합의 전 시안이다.
      // 파일을 고치지 않고 보려면 주소 뒤에 ?book=1 (끄기 ?book=0). 기기의 「동작 줄이기」 가 켜져 있으면 넘기지 않는다.
      bookFlip: false,
      bookFlipMs: 550,           // 휴대전화 — 한 쪽 넘김
      bookSpreadMs: 750,         // PC (폭 760px 이상) — 두 쪽 펼침에서 한 장 넘김
      // 엽서 내려받기 형식. png = 이미지 한 장 (지금 지원)
      download: 'png',
      // 내려받는 파일 이름을 영문으로. false 면 한글 제목을 파일명에 쓴다
      // (환경에 따라 이름이 깨지거나 버려질 수 있다)
      filenameAscii: true,
    },

    // ── 3차 인증 · 인터뷰 링크 (3-C1 초안 · develop cd65dfa) ──────────
    // **서버 코드는 아직 없다.** 기본값은 지금처럼 dev-user 헤더로 돈다. 규격 모양대로 미리 만들어 두고
    // 주소 뒤 값으로 켜서 본다: ?auth=session · ?authMock=ok · ?linkMock=ready (README 「3차 인증 · 링크」)
    auth: {
      // 'dev'     = 지금처럼 X-User-Id: dev-user 헤더 (서버에 인증이 붙기 전)
      // 'session' = 구글 로그인 → 서버가 msid 쿠키를 준다. 화면은 X-User-Id 를 보내지 않는다
      // 'auto'    = 주소로 고른다 (최충 님 부탁 · 2026-10-22). 내 PC(localhost · 127.0.0.1)와 같은 와이파이
      //             안의 주소(192.168.… · 10.… · 172.16~31.…)면 dev, 그 밖(naemalssami.com 같은 배포 주소)이면 session.
      //             그래서 원본을 그대로 web\index.html 로 복사하면 배포 서버에서는 로그인 모드로 돈다.
      // 주소 뒤 ?auth=dev · ?auth=session 이 언제나 먼저다.
      mode: 'auto',
      // Google Cloud 웹 클라이언트 ID (비밀값 아님 — 로그인 버튼이 있는 화면은 누구나 볼 수 있는 값).
      // 최충 님 전달 (2026-10-22). 서버 .env 의 GOOGLE_CLIENT_ID 와 같아야 한다. 비우면 버튼 자리에 「준비 중」
      googleClientId: '169728982875-hj9sagsch1fuk4dgrlkusvg2ith1m5th.apps.googleusercontent.com',
      // 모의 로그인 (서버 없이): '' | ok | new(화자 없음) | cancel | invalid_token | expired_token
      mock: '',
      // 화자 만들기 — POST {name} → 201 {elder_id, name} (최충 답변 2026-10-21). 부를 때마다 새 화자가 생긴다
      elderPath: '/elders',
    },
    link: {
      path: '/i',                // 어르신 링크 주소 https://<고정 주소>/i#<토큰>
      // 모의 링크 (서버 없이): '' | ready · in_progress · elsewhere · ended · interrupted · expired · revoked · invalid
      mock: '',
    },

    // ── 4차 문체 (4-C1 · 최충 답변 2026-10-21) ─────────────────────
    // 엽서 POST /api/sessions/{id}/postcard {style} · 자서전 POST /api/memoirs/preview {session_ids, style}.
    // 보내지 않으면 서버도 구어체. 이 셋 말고는 400 code unsupported_style.
    // **라벨은 언제나 응답의 style 로 붙인다** — 고른 값이 아니다 (다시 만들다 실패하면 옛 글이 남는다).
    // 서버가 style 을 아직 모르면(지금 develop) 칸을 무시하고 구어체로 만든다 — 응답에 style 이 없으면 구어체로 본다.
    style: {
      names: { spoken: '구어체', essay: '수필체', literary: '문학체', novel: '소설체', cyworld: '싸이월드체' },
      default: 'spoken',
      pick: true,                // 자서전 · 엽서 화면에 문체 고르기를 보인다
      // 서버가 지금 받는 문체 (feature/theme-interview 4c8d0f7 · 1단계는 spoken 하나).
      // 나머지는 고르기에서 숨긴다 — 누르면 400 unsupported_style 만 온다. 4-P1 뒤 서버가 열면 여기에 더한다.
      // 고를 것이 하나뿐이면 고르기 줄은 숨기고 「문체: ○○」 라벨만 둔다. ?styles=all 이면 전부 보인다 (400 시험용)
      open: ['spoken'],
      // 자서전은 수필체 · 문학체 · 소설체도 받는다 (서버 memoir_styled · memoir_novel — 태헌 문체 전달 3판, develop 0a5227c). 엽서는 아직 구어체만
      memoirOpen: ['spoken', 'essay', 'literary', 'novel'],
      regenWaitMs: 40000,        // 엽서를 다른 문체로 다시 만들 때 기다리는 상한
    },

    pollMs: 300,                 // 서버 상태를 물어보는 주기 (frontend-client 와 동일)
    dev: false,                  // true 면 개발용 패널이 처음부터 열려 있다
    // 개발 패널(⚙) 버튼을 보일까. 'auto' = 내 PC · 같은 와이파이 주소면 보이고, 배포 주소(naemalssami.com)에서는
    // 숨긴다 — 실제 이용자에게 「마이크 없이 발화 보내기」 같은 시험 도구를 내보이지 않는다.
    // 배포 주소에서도 필요하면 주소 뒤에 ?dev=1. true = 언제나 보임 · false = 언제나 숨김
    devPanel: 'auto',
  };

  const QS = new URLSearchParams(location.search);
  const AUTH = {
    mode: 'session',
    mock: QS.get('authMock') ?? CONFIG.auth.mock,
    user: null, elders: [],
    elderId: '',
  };
  // 어르신 링크 https://<주소>/i#<토큰>. 토큰은 # 뒤라 서버로 가지 않는다 — 화면이 읽어 헤더로만 보낸다.
  // **토큰은 로그 · 화면 어디에도 찍지 않는다.**
  const LINK = { on: false, token: '', mock: QS.get('linkMock') ?? CONFIG.link.mock, preview: null, topic: '' };
  (() => {
    const atPath = location.pathname.replace(/\/+$/, '') === CONFIG.link.path;
    if (!atPath && !LINK.mock) return;
    LINK.on = true;
    const h = location.hash.replace(/^#/, '');
    if (h) {
      LINK.token = h;
      try { history.replaceState(null, '', location.pathname + location.search); } catch (_) {}
    }
  })();
  function idHeaders(path) {
    if (path.startsWith('/i/')) return LINK.token ? { 'X-Interview-Token': LINK.token } : {};
    return {};
  }
  const sp = (id) => LINK.on ? '/i/session' : `/sessions/${id}`;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  function log(tag, msg) { if (window.console) console.log(`${new Date().toTimeString().slice(0, 8)} ${tag} ${msg}`); }

  class ApiError extends Error {
    constructor(status, message, retryAfter) {
      super(message);
      this.status = status;
      this.retryAfter = retryAfter || 0;
    }
  }

  async function call(path, init) {
    const res = await fetch(`${CONFIG.apiBase}/api${path}`, Object.assign({}, init, {
      credentials: 'include',
      headers: Object.assign({ 'Content-Type': 'application/json' }, idHeaders(path), init && init.headers),
    }));
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      const d = body.detail;
      const err = new ApiError(res.status,
        (typeof d === 'string' ? d : d && d.message) || '요청에 실패했습니다',
        Number(res.headers.get('Retry-After')) || 0);
      err.code = String(body.code || (d && typeof d === 'object' && d.code) || '');
      err.body = body;
      // 로그인이 풀렸다 — 자녀 경로가 401 이면 화면을 비우고 처음으로 (링크 · 로그인 경로는 제외)
      if (res.status === 401 && !path.startsWith('/auth/') && !path.startsWith('/i/')) authLost(err.code);
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function memoirBody(req, style) {
    return JSON.stringify(Object.assign(req.exclude
      ? { elder_id: req.elderId, exclude_session_ids: req.exclude }
      : { [CONFIG.memoir.idsField]: req.ids }, style ? { style } : {}));
  }

  /** 로그인이 풀렸다 · 로그아웃했다. 화면 메모리를 통째로 비운다 — 다시 불러오기가 가장 확실하다. */
  let authLosing = false;
  function authLost(code) {
    if (authLosing) return;
    authLosing = true;
    try { sessionStorage.setItem('authMsg', AUTH_SAYS[code] || AUTH_SAYS.session_expired); } catch (_) {}
    location.reload();
  }

    const api = {
    health: () => call('/health'),

    // POST /api/sessions  →  StartReq(title, seed, pace, max_turn, photo_id?)
    start: (body) => call('/sessions', { method: 'POST', body: JSON.stringify(body) }),

    get: (id) => call(sp(id)),

    ttsDone: (id) => call(`${sp(id)}/tts-done`, { method: 'POST' }),

    // 마이크 없이 흐름을 돌려볼 때 쓰는 텍스트 경로 (SpeechReq.text)
    speech: (id, text) => call(`${sp(id)}/speech`, { method: 'POST', body: JSON.stringify({ text }) }),

    // 오디오는 JSON 으로 감싸지 않는다. 본문은 바이트 그대로, mime 은 Content-Type.
    audio: (id, pcm, mime) => call(`${sp(id)}/speech/audio`, {
      method: 'POST', body: pcm, headers: { 'Content-Type': mime },
    }),

    // 소리가 없으면 204 → null. 오류가 아니다. 화면은 글자만 띄우면 된다.
    questionAudio: async (id) => {
      const path = `${sp(id)}/question/audio`;
      const res = await fetch(`${CONFIG.apiBase}/api${path}`, { credentials: 'include', headers: idHeaders(path) });
      if (res.status === 204) return null;
      if (!res.ok) throw new ApiError(res.status, '소리를 받지 못했습니다');
      const blob = await res.blob();
      return blob.size ? blob : null;
    },

    // 낭독을 조각으로 (서버 TTS_STREAM=1). **본문을 읽지 않고 응답째 돌려준다** — 다 받고
    // 나서 틀면 흘려 받는 뜻이 없다. 204 면 null (소리 없음, 오류 아님). 본문은 날 PCM
    // 16비트 모노이고 rate 는 Content-Type 에 실려 온다.
    questionStream: async (id) => {
      const path = `${sp(id)}/question/stream`;
      const res = await fetch(`${CONFIG.apiBase}/api${path}`, { credentials: 'include', headers: idHeaders(path) });
      if (res.status === 204) return null;
      if (!res.ok || !res.body) throw new ApiError(res.status, '소리를 받지 못했습니다');
      return res;
    },

    done: (id) => call(`${sp(id)}/done`, { method: 'POST' }),
    abort: (id) => call(`${sp(id)}/abort`, { method: 'POST' }),

    // ── 3차 — 자녀 로그인 (3-C1 §4 초안). 오류는 { detail, code } — 화면은 code 로 가른다
    authGoogle: (credential) => AUTH.mock ? authFake('google')
      : call('/auth/google', { method: 'POST', body: JSON.stringify({ credential }) }),
    authMe: () => AUTH.mock ? authFake('me') : call('/auth/me'),
    authLogout: () => AUTH.mock ? authFake('logout') : call('/auth/logout', { method: 'POST' }),
    // POST /api/elders {name} → 201 {elder_id, name}
    elderCreate: (name) => AUTH.mock ? authFake('elder', name)
      : call(CONFIG.auth.elderPath, { method: 'POST', body: JSON.stringify({ name }) }),
    // ── 3차 — 어르신 링크 (3-C1 §5). 헤더 X-Interview-Token 은 call() 이 붙인다
    linkPreview: () => LINK.mock ? linkFake('preview') : call('/i/preview'),
    // 어르신이 고른 낱말(topic)을 싣는다 — 서버가 읽기 전까지는 무시된다 (CONFIG.interview.wordPick)
    linkStart: (topic) => LINK.mock ? linkFake('start') : call('/i/start', { method: 'POST', ...(topic ? { body: JSON.stringify({ topic }) } : {}) }),
    linkTranscript: () => LINK.mock ? linkFake('transcript') : call('/i/transcript'),
    // ── 3차 — 자녀가 링크를 발급 · 회수 · 재발급 (feature/theme-interview 40551ea)
    //    발급 201 {link_id, elder_id, title, theme, topic, state, session_id, created_at, expires_at, token, url}
    //    **token · url 은 발급 응답에만 한 번 온다** (서버 표에는 해시만). 재발급 409 already_started
    linkCreate: (body) => AUTH.mock ? linkOutFake('create', body) : call('/links', { method: 'POST', body: JSON.stringify(body) }),
    linkRevoke: (id) => AUTH.mock ? linkOutFake('revoke') : call(`/links/${encodeURIComponent(id)}/revoke`, { method: 'POST' }),
    linkReissue: (id) => AUTH.mock ? linkOutFake('reissue') : call(`/links/${encodeURIComponent(id)}/reissue`, { method: 'POST' }),
    // 보낸 링크 — 최근 순 · 기본 20 · ?limit= 최대 100 · ?elder_id= 로 화자별. 토큰은 없다
    linkList: (limit, elderId) => AUTH.mock ? linkOutFake('list')
      : call(`/links?limit=${limit || 20}${elderId ? `&elder_id=${encodeURIComponent(elderId)}` : ''}`),

    // 지난 회차 목록. 빈 목록(없음)과 503(못 읽음)은 다른 사건이다.
    // ?has_postcard=1 이면 엽서 있는 회차만, DB 에서 걸러 최근 순으로 (feature/theme-interview e1efd0d).
    // 회차마다 has_postcard(true/false) 도 실린다. 이 옵션을 모르는 예전 서버는 그냥 전부 준다.
    sessions: (limit, signal, opts) => call(`/sessions?limit=${limit || CONFIG.archive.limit}${opts && opts.hasPostcard ? '&has_postcard=1' : ''}`
                                           + `${opts && opts.elderId ? `&elder_id=${encodeURIComponent(opts.elderId)}` : ''}`
                                           + `${opts && opts.query ? `&${opts.query}` : ''}`,
                                           signal ? { signal } : undefined),
    // 화자 미지정 회차에 화자를 한 번 정한다 (태헌 10-26 · a2454a9). 200 {session_id, elder_id}
    // 이미 다른 화자 → 409 elder_already_set · 남의 회차 · 화자 → 404. 같은 화자를 다시 보내면 200
    assignElder: (id, elderId) => call(`/sessions/${id}/elder`, { method: 'PUT', body: JSON.stringify({ elder_id: elderId }) }),

    // ── 사진 (main.py upload_photo · get_photo) ──
    // 본문은 바이트 그대로. 형식은 서버가 앞머리 바이트로 가린다 (HEIC 도 받는다).
    // session_id 는 선택 — 주면 그 회차에 붙는다.
    // 응답: { photo_id, url, mime, width, height, bytes }
    uploadPhoto: (bytes, mime, sessionId) =>
      call(`/photos${sessionId ? '?session_id=' + encodeURIComponent(sessionId) : ''}`, {
        method: 'POST', body: bytes, headers: { 'Content-Type': mime || 'application/octet-stream' },
      }),
    // <img src> 에 그대로 넣는 주소. 서버 응답의 url 과 같은 모양이다.
    photoUrl: (photoId) => `${CONFIG.apiBase}/api/photos/${photoId}`,

    // ── 엽서 (main.py make_postcard · get_record · get_postcard) ──
    // 굽기를 시작하고 끝날 때까지 기다린다. 409=아직/굽는 중, 503=서버 사정.
    // style 을 주면 {"style": …} 본문 (4-C1). 주지 않으면 예전처럼 본문 없이 — 서버가 구어체로 만든다
    card: (id, style) => call(CONFIG.card.path.replace('{id}', id),
      Object.assign({ method: CONFIG.card.method }, style ? { body: JSON.stringify({ style }) } : {})),
    // DB 에 저장된 회차. 서버가 저절로 구운 엽서를 여기서 되찾는다.
    record: (id, signal) => call(`/sessions/${id}/record`, signal ? { signal } : undefined),
    // 서버가 구운 엽서 그림. <img> 로는 헤더를 못 보내므로 fetch 로 받는다.
    postcardImage: async (url) => {
      const res = await fetch(`${CONFIG.apiBase}${url}`, {
        credentials: 'include', headers: idHeaders('/sessions'),
      });
      if (!res.ok) throw new ApiError(res.status, '엽서 그림을 받지 못했습니다');
      return res.blob();
    },

    // ── 자서전 초안 (C1 v1.1) ──
    // 다른 API 와 같은 call() 을 쓴다. 실패는 HTTP 상태 + {"detail": …} 로 온다.
    // 화면 안내는 상태로만 고르고 detail 은 화면에 내지 않는다 (mmWhy).
    // 사용자 신원은 본문이 아니라 call() 이 붙인다 (dev 모드 X-User-Id · 로그인 모드 msid 쿠키).
    // 작업 방식 (PR #14) — 본문은 preview 와 같다. 202 {job_id, status, stage, run}
    memoirStart: (req, style) => call(CONFIG.memoir.jobPath, { method: 'POST', body: memoirBody(req, style) }),
    memoirJob: (id) => call(`${CONFIG.memoir.jobPath}/${encodeURIComponent(id)}`),
    // GET /memoirs/latest (내 최근 작업) 는 쓰지 않는다 (태헌 10-28) — 작업 번호는 localStorage 로 기억한다
    memoirCancel: (id) => call(`${CONFIG.memoir.jobPath}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    // req = { ids } 또는 { elderId, exclude } (mmRequest 가 만든다)
    memoirPreview: (req, signal, style) => call(CONFIG.memoir.path, {
      method: 'POST', signal, body: memoirBody(req, style),
    }),

    // 이 회차에 엽서가 있나. GET /postcard 는 JPEG 라 json() 으로 읽지 않는다.
    // 있으면 받은 그림을 그대로 썸네일로 쓰고(주소 하나), 404 면 null 이다.
    // 그 밖의 실패(502 · 503 · 연결 끊김)는 던진다 — 「엽서 없음」 으로 숨기지 않는다.
    postcardThumb: async (sessionId) => {
      const res = await fetch(`${CONFIG.apiBase}/api/sessions/${sessionId}/postcard`, {
        credentials: 'include', headers: idHeaders('/sessions'),
      });
      if (res.status === 404) return null;
      if (!res.ok) throw new ApiError(res.status, '엽서를 확인하지 못했습니다');
      return URL.createObjectURL(await res.blob());
    },
  };

    const THEME_LABEL = { family: '가족', self: '나', hobby: '취미' };
  // 문구는 예시다 — 김대원 님과 맞춘다 (3-C1 §4 · §5-3)
  const AUTH_SAYS = {
    invalid_token: '로그인을 확인하지 못했어요. 다시 시도해 주세요.',
    expired_token: '로그인 시간이 지났어요. 다시 로그인해 주세요.',
    login_required: '',
    session_expired: '오래 쉬셔서 로그아웃되었어요. 다시 로그인해 주세요.',
    other: '지금은 로그인할 수 없어요. 잠시 뒤 다시 시도해 주세요.',
  };
  const LINK_SAYS = {
    ready:       { h: '들려주실 이야기', p: '준비되시면 아래 버튼을 눌러 주세요. 누르면 마이크를 써도 되는지 여쭤봐요.', btn: '이야기 시작하기', topic: true, friend: true,
                   pick: '이야기하고 싶은 낱말을 고르고 아래 「이야기 시작하기」를 눌러 주세요. 누르면 마이크를 써도 되는지 여쭤봐요.' },
    in_progress: { h: '이야기를 이어서 해요', p: '이 기기에서 하던 이야기가 남아 있어요.', btn: '이어서 하기', topic: true, friend: true },
    in_progress_elsewhere: { h: '다른 곳에서 진행 중이에요', p: '처음 시작한 기기에서 이어서 해 주세요.' },
    interrupted: { h: '연결이 끊겼어요', p: '링크를 보내 주신 분께 새 링크를 부탁해 주세요.' },
    expired:     { h: '기간이 지난 링크예요', p: '링크를 보내 주신 분께 알려 주세요.' },
    revoked:     { h: '더 이상 쓸 수 없는 링크예요', p: '링크를 보내 주신 분께 알려 주세요.' },
    invalid_link:{ h: '링크를 다시 확인해 주세요', p: '받으신 링크가 끝까지 열렸는지 확인해 주세요.' },
    neterr:      { h: '연결이 잠깐 끊겼어요', p: '잠시 뒤 다시 눌러 주세요.', btn: '다시 시도' },
    mock_started:{ h: '(모의) 시작 요청까지 확인했어요', p: '실제 인터뷰는 서버가 준비되면 지금의 대화 화면으로 이어집니다.', friend: true },
  };
  // 상태 코드 → 화면 상태. 410 · 404 에는 주제 · 이름이 오지 않는다 (3-C1 §5-3)
  const linkStateOf = (e) => (e.code && LINK_SAYS[e.code]) ? e.code
    : e.status === 410 ? 'expired' : e.status === 404 ? 'invalid_link' : 'neterr';

    async function linkOutFake(kind, body) {
    await sleep(300);
    const base = { link_id: 'mock-l1', elder_id: 'mock-e1', state: 'ready', session_id: null, token: null, url: null };
    if (kind === 'revoke') return Object.assign({}, base, { state: 'revoked' });
    if (kind === 'list') {
      const t = (d) => new Date(Date.now() - d * 864e5).toISOString(), until = new Date(Date.now() + 2 * 864e5).toISOString();
      const row = (id, state, sid, theme, topic, d) => ({ link_id: id, elder_id: 'mock-e1', title: THEME_LABEL[theme], theme, topic, state, session_id: sid, created_at: t(d), expires_at: until });
      return { links: [row('l1', 'ready', null, 'family', '첫 직장', 0), row('l2', 'in_progress', 's2', 'hobby', '사진 찍기', 0),
        row('l3', 'ended', 's3', 'self', '어린 시절', 1), row('l4', 'revoked', null, 'family', '이사', 2), row('l5', 'expired', null, 'family', '결혼식', 5)] };
    }
    return Object.assign({}, base, body || {});
  }

  /* ── 모의 응답 (서버 없이 화면 흐름만) — 실제 계정 · 링크를 만들지 않는다 ── */
  const mockLogged = { get: () => { try { return sessionStorage.getItem('mockLogin') || ''; } catch (_) { return ''; } },
                       set: (v) => { try { v ? sessionStorage.setItem('mockLogin', v) : sessionStorage.removeItem('mockLogin'); } catch (_) {} } };
  async function authFake(kind, arg) {
    await sleep(300);
    const err = (status, code) => { const e = new ApiError(status, '모의'); e.code = code; return e; };
    const user = { user_id: 'mock-u1', name: '예시 자녀', email: 'child@example.com' };
    if (kind === 'me') {
      const v = mockLogged.get();
      if (!v) throw err(401, 'login_required');
      return { user, elders: v === 'new' ? [] : [{ elder_id: 'mock-e1', name: v === 'ok' ? '어머니' : v }] };
    }
    if (kind === 'logout') { mockLogged.set(''); return null; }
    if (kind === 'elder') { mockLogged.set(arg); return { elder_id: 'mock-e1', name: arg }; }   // 201
    // google
    if (AUTH.mock === 'cancel') return { cancelled: true };
    if (AUTH.mock === 'invalid_token' || AUTH.mock === 'expired_token') throw err(401, AUTH.mock);
    mockLogged.set(AUTH.mock === 'new' ? 'new' : 'ok');
    return { user, elders: AUTH.mock === 'new' ? [] : [{ elder_id: 'mock-e1', name: '어머니' }] };
  }
  async function linkFake(kind) {
    await sleep(300);
    const m = LINK.mock;
    const err = (status, code) => { const e = new ApiError(status, '모의'); e.code = code; return e; };
    const info = { theme: 'family', topic: '첫 직장' };
    if (m === 'expired' || m === 'revoked') throw err(410, m);
    if (m === 'invalid') throw err(404, 'invalid_link');
    if (kind === 'preview') {
      const state = m === 'elsewhere' ? 'in_progress' : m;
      return Object.assign({ state }, info);
    }
    if (kind === 'start') {
      if (m === 'elsewhere') throw err(409, 'in_progress_elsewhere');
      if (m === 'ended' || m === 'interrupted') throw err(409, m);
      return { mock: true };
    }
    // transcript
    if (m !== 'ended') throw err(409, 'not_ended');
    return Object.assign({ turns: [
      { question: '오늘은 「첫 직장」 이야기를 나눠 볼까요?', answer: '광주 인쇄소에서 첫 월급을 받았어요.' },
      { question: '그 돈으로 무엇을 하셨어요?', answer: '어머니께 빨간 목도리를 사 드렸어요.' },
    ] }, info);
  }

  const curElder = () => AUTH.elders.find(e => e.elder_id === AUTH.elderId) || null;
  window.Srv = { CONFIG, QS, AUTH, LINK, api, call, ApiError, sleep, log, sp, idHeaders, curElder,
    AUTH_SAYS, LINK_SAYS, THEME_LABEL, linkStateOf, authLost };
}());
