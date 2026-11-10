# White Rose Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 승인된 흰 바탕·차콜 글씨·버건디 로즈 테마를 정적 검토 UI 전체에 적용한다.

**Architecture:** 마지막에 로드하는 CSS 레이어로 색상만 교체한다. 독서 모드에는 새 변수를 상속하지 않으며 삽화·책표지·의미 있는 상태색은 보존한다.

**Tech Stack:** HTML, CSS, Node 내장 검증, Chrome 브라우저.

**Spec:** `docs/superpowers/specs/2026-11-10-white-rose-design.md`

## Global Constraints

- 사용자 승인: “이버전으로 하자”. 별도 재승인 없이 이 명세 범위에서 반영한다.
- 기존 기능·문구·치수·서체와 입력 데이터를 유지한다.
- 백엔드·React·리더 JS·삽화·표지 파일은 수정하지 않는다.
- 커밋·푸시·배포는 이번 작업에 포함하지 않는다.

## Review Focus

- 마지막 CSS의 우선순위와 하드코딩된 베이지·갈색 잔여.
- PC/모바일 활성 메뉴의 명확한 상태 및 키보드 초점.
- 입력·선택·로그인·확인 대화상자의 실제 전경/배경 대비.
- 독서 모드의 종이·야간 테마와 책표지 3색 보존.
- 320px 화면에서 기존 줄바꿈·조작 영역·가로 넘침 유지.

### Task 1: 색상 레이어 적용

**Files:** Create `prototype/ui-review/white-rose-theme.css`; modify `prototype/ui-review/index.html`.

**Interfaces:** 기존 클래스·ARIA 상태·CSS 변수만 사용한다. 함수·데이터 인터페이스 변경 없음.

- [x] 기존 검증 실행: `node prototype/ui-review/verify-server-ready.cjs` → 175/175, 구문31개, 서버9개 지문 일치.
- [x] 본문·배경·보조문구·컨트롤·대화상자·선택상태 색을 교체하고 PC/모바일 메뉴 밑줄 적용.
- [x] 실제 브라우저에서 홈/인터뷰/엽서/책장/선택/로그인/독서 및 작은 화면 확인.

### Task 2: 결정 기록과 최종 확인

**Files:** `prototype/ui-review/{README.md,UI_DECISIONS.md,USER_FEEDBACK.md,CHANGE_IMPACT.md}`.

**Interfaces:** Task 1의 실제 결과를 최신 결정으로 기록한다.

- [x] 기존 기록 위에 새 승인 범위와 검증 결과 추가.
- [x] `node prototype/ui-review/verify-server-ready.cjs`, `git diff --check` 실행.
- [x] 독립 검토를 받고 중요한 지적을 해결한다.

## 실행 기록

- Pre-flight: CSS 링크 순서 → 테마 레이어 → 실제 색상 → 결정 기록의 순서로 진행한다.
- Ruling: 이미 사용자 검토용 `codex/frontend-ui-review` 브랜치의 깨끗한 작업공간이므로 현재 위치에서 실행한다. 사용자 승인은 선택한 시안의 반영이며 다른 브랜치·푸시까지 확장하지 않는다.
- Ruling: 새 동작이 없는 가역적 색상 변경이므로 구현을 복제하는 테스트는 추가하지 않는다. 기존 검사와 브라우저에서 실제 적용 색·상태·크기·리더 예외를 검증한다.
- Task 1 complete: CSS 레이어 67규칙, 실제 PC/320px/좁은 PC 확인, 키보드 초점·독서 종이/야간 복구 확인.
- Final review: 독립 리뷰가 발견한 본문 색 우선순위를 브라우저에서 재현(회색)하고 수정 후 차콜을 확인했다. 단계 강조도 로즈색으로 복구했고 hover 잔여 베이지를 정리했다. 남은 지적 없음.
- Task 2 complete: 최종 테스트175/175, 구문31개, 서버9개 지문 일치. 결정 문서4개와 검증 기록 갱신. 커밋·푸시·배포 없음.
