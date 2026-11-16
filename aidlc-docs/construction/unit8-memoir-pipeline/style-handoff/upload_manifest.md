# 올릴 파일 · 올리지 않을 파일

**아직 아무것도 올리지 않았다.** 커밋 · push · PR · `git add` 를 하지 않았고 팀 저장소의 파일을 바꾸지 않았다. 이 문서는 올릴 때 쓸 목록이다. 실제 업로드는 별도 지시가 있을 때 한다.

## 1. 올릴 파일 — 27개 · 전부 신규

`develop`(7400e51 · 원격과 같은 커밋)에 같은 경로의 파일이 없는 것을 확인했다. **추가 27 · 수정 0 · 삭제 0.** 전달 묶음의 `upload/` 폴더가 저장소 루트와 같은 모양이다 — 그대로 겹쳐 놓으면 된다.

### `backend-agent/첨부프롬프트_md/문체/` (17개)

| 파일 | 종류 | 2판 대비 |
|---|---|---|
| `essay/7c_고픽션문학수필_리듬v1.md` | **수필체** 기준 프롬프트 | 같음 |
| `literary/prompt_극서정문학체_v2.md` | **문학체** 기준 프롬프트 | 같음 |
| `novel/prompt_소설체_최소수정v1.md` | **소설체** 기준 프롬프트 — 구운몽ST 최소 수정 v1 · 다애님 승인 완료 | 같음 |
| `analysis/0_원문분석_목차통합_안전사본.md` | **분석 지시문 안전 사본** — 수필체 · 문학체 입력의 바탕 | **새로 넣음** |
| `style_manifest.json` | 명칭 · ID · 해시 · 출처 · 검증된 설정 · 승인 상태 · 분석 의존성 | 승인 · 분석 항목 갱신 |
| `.gitattributes` | 이 폴더의 줄바꿈 변환을 끈다(`*.md -text` 등) — `analysis/` 에도 걸린다 | 같음 |
| `schemas/essay_output.schema.json` · `literary_output.schema.json` · `analysis_output.schema.json` | 출력 스키마 3개 | 같음 |
| `reference/bundle_reference.py` | 장 자료 묶음 조립 참조 구현(표준 라이브러리만) | 같음 |
| `examples/` 의 7개 | 가상 분석 결과 · 가상 원문 · 묶음 2개 · 출력 예시 3개 | 같음 |

### `backend-agent/tests/` (1개)

| 파일 | 종류 | 2판 대비 |
|---|---|---|
| `test_style_handoff.py` | 무료 점검 20개. 모델 · 네트워크 · 환경변수를 쓰지 않는다 | 승인 문구 1줄 · 분석 지시문 점검 3개 추가 |

### `aidlc-docs/construction/unit8-memoir-pipeline/style-handoff/` (9개)

`README.md` · `input_output_contract.md` · `backend_handoff.md` · `compatibility_report.md` · `validation_report.md` · `upload_manifest.md` · `remaining_decisions.md` · `novel_prompt_diff.md` · `analysis_prompt_safety.md`(새 문서)

- 프롬프트 파일의 **이름을 바꾸지 않는다.** 정식 명칭(수필체 · 문학체 · 소설체)은 `style_manifest.json` 의 매핑으로 관리한다.
- `novel_prompt_diff.md` 에는 구운몽ST 원본에서 지운 구절이 인용돼 있다. 원본 파일 자체는 올리지 않는다.
- `analysis_prompt_safety.md` 에는 분석 지시문에서 **바꾸기 전의 값이 없다.** 바꾼 자리 · 개수 · 구조 검사 결과 · 사본의 해시만 있다.
- 올린 뒤 `python -m pytest tests/test_style_handoff.py -q` 가 통과하면 사본이 손상되지 않은 것이다.

### 기존 파일의 변경 예상

**없음.** 새 파일만 더한다. 운영 코드(`app/` · `tools/`) · 서비스 로더가 읽는 폴더(`파이프라인/` · `파이프라인_통합/`) · 저장소 루트의 `.gitattributes` 와 `.gitignore` 를 건드리지 않는다. 연동을 구현할 때 백엔드 담당자가 바꾸게 될 파일(이번 전달과 별개): `backend-agent/app/session/style.py`(지원 값) · `backend-agent/app/session/memoir.py`(문체에 따른 분기) · 응답 규격 문서.

### 줄바꿈

팀 저장소는 Windows 기본 설정(`core.autocrlf=true`)을 쓰고, 저장소 루트의 `.gitattributes` 는 시험 자료 한 파일만 다룬다. 이 상태로 프롬프트를 올리고 다시 받으면 **작업 폴더의 파일이 CRLF 로 풀려 해시가 달라진다**(임시 저장소에서 확인). 그래서 문체 폴더 안에 `.gitattributes` 를 넣었다 — 그 파일이 있으면 올리고 받아도 문체 프롬프트 세 개와 분석 지시문의 바이트가 그대로다.

## 2. 올리지 않을 파일

| 대상 | 까닭 |
|---|---|
| 전달 묶음의 `local_only/` 전체 | **분석 지시문 원본의 실제 이름 · 원본과 사본의 전체 차이 · 치환 전후의 값**이 있다. 빌드 · 점검 스크립트도 로컬 경로를 읽는다 |
| **분석 지시문 원본**(`0_원문분석_목차통합.md`)과 그 해시 | 예시에 실제 인터뷰의 인물 이름이 있다. 해시도 올리지 않는다 — 사본과 짧은 이름 하나만 달라, 해시로 이름을 맞춰 볼 수 있다 |
| 실제 인터뷰 원문(주제별 txt · `stories.json` · 팀 공유 자료의 원문) | 실존 인물의 구술이다 |
| 실험 원고 · 모델 원본 응답 · 호출 로그 · 실행 기록 · 검증 원고 · 저장된 분석 결과 | 실제 인터뷰로 만든 것이다 · 대용량 · 연동에 필요 없음 |
| PDF · 조판 HTML · 블라인드 평가 자료 | 같다 |
| **구운몽ST 원본 프롬프트**(`범용프롬프트.txt`) · 팀 공유 ZIP 의 나머지 | 정식 소설체가 아니다. 원본의 해시만 출처로 적었다 |
| 그 밖의 구버전 · 탈락 프롬프트(수필체 리듬 이전 판 · 자체 소설체 v1/v2/v2.1 · 고밀도 문학체 v1 · 분석 지시문의 앞선 판 · 문체 편집 · 문단 편집) | 정식 자산이 아니다 |
| 실험 실행기 · 제목 선정 지시문과 로직 | 문체 프롬프트의 범위를 넘는다 |
| 이전 전달 묶음(1판 · 2판) | 로컬에 그대로 보존한다 |
| API 키 · 인증 정보 | 처음부터 저장소 밖에 있다 |

## 3. 올릴 때 주의

1. **`upload/` 만 올린다.** `local_only/` 가 한 파일이라도 섞이면 가명 처리가 무의미해진다.
2. 커밋 메시지 · PR 본문 · 리뷰 댓글에 **분석 지시문 원본의 해시나 바꾸기 전의 값을 적지 않는다.**
3. 문체 폴더의 `.gitattributes` 를 빼지 않는다.
4. `develop` 이 7400e51 에서 움직였다면 경로 충돌을 다시 본다.

## 4. 올리기 전 마지막 확인

1. `python -m pytest tests/test_style_handoff.py -q` — 20개 통과.
2. 문체 프롬프트 세 개와 분석 지시문 안전 사본의 SHA-256 이 `style_manifest.json` · 테스트의 고정값과 같다.
3. 올리는 파일이 위 27개뿐이다.
4. 올릴 브랜치와 위치를 백엔드 담당자와 맞췄다.
