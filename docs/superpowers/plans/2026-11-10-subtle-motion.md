# Subtle Motion Implementation Plan

> **For agentic workers:** Execute the approved motion choice in the current session; this file records the small implementation and verification tasks.

**Goal:** 실제 UI에 전체 은은한 탄성과 하단 아이콘 스냅을 적용한다.
**Architecture:** 마지막에 로드하는 독립 CSS/JS가 조작·등장 효과를 담당한다. 기존 라우팅과 네이티브 대화상자 동작은 변경하지 않는다. 독서 드래그는 기존 리더에 결합한다.
**Tech Stack:** Existing HTML/CSS, browser Web Animations API, JavaScript, Node offline verification.
**Spec:** `../specs/2026-11-10-subtle-motion-design.md`

## Global Constraints

- 현재 브랜치의 기존 미커밋 작업을 보존한다. UI 파일만 수정하며 이번 작업에서 커밋·푸시·배포하지 않는다.
- 동작 때문에 클릭·상태 변경·초점 이동을 기다리게 하지 않는다. 추가 의존성을 설치하지 않는다.
- 색상과 터치 영역, 독서 설정과 페이지 위치를 보존한다.

## Review Focus

- 320px에서 여러 줄 메뉴 이름과 아이콘 배경이 겹치지 않아야 한다.
- 연속 탭·취소·초점 변경 뒤 눌림 상태가 남지 않아야 한다.
- 줄이기 설정에서는 장식 동작이 없어야 한다.
- 대화상자의 닫기와 초점 복원이 즉시 작동해야 한다.
- 독서 세로 스크롤·텍스트 선택·첫/마지막 쪽 경계가 유지되어야 한다.

## Tasks

- [x] `interaction-motion.css`와 `interaction-motion.js`를 추가하고 `index.html`에 연결한다. 일반 버튼의 은은한 눌림, 화면·대화상자 등장, 모바일 하단 아이콘만의 스냅을 구현한다.
- [x] `ebook-reader.js`에 터치 가로 추적과 취소 복귀를 추가한다. 기존 넘김·위치·접근성 설정을 사용한다.
- [x] `node prototype/ui-review/verify-server-ready.cjs`와 브라우저에서 주요 조작·320px·PC·독서를 확인하고 결정·검증 기록을 갱신한다.

자동 단위 테스트를 조작 프레임의 복사본으로 추가하지 않는다. 이번 가역적인 시각 변경은 실제 브라우저 조작으로 확인하며 기존 계약/독서 테스트 전체를 실행한다.

## Verification

- 오프라인 전체175/175, 구문32개, 서버 기준 소스9개 일치.
- Chrome PC/320px에서 실제 로드와 선택 상태·팝업·독서 드래그 확인. 320px 링크69px, 가로 넘침 없음.
- 독립 리뷰의 포인터 영역 밖 해제 잔류 문제를 수정했다. 브라우저에서 빈 공간 마우스 드래그가 줄바꿈 선택으로 취소되던 문제도 마우스 한정 기본 선택 방지로 수정해5/5쪽 이동을 확인했다.
- 실기기 터치 검증, 커밋·푸시·배포는 이번 범위에 포함하지 않는다.
