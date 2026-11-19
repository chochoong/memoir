# prototype/tests — 화면 확인 도구

화면 코드를 고치기 전 · 뒤에 돌려, 겉모습과 흐름이 그대로인지 확인한다.
서버나 유료 API 를 부르지 않는다 (예시 모드 `?demo=1` 로만 돈다). 빌드(`build.py`)에는 들어가지 않는다.

## 준비

```bash
python prototype/build.py          # prototype/index.html 을 만든다 — 시험은 이 파일을 연다
npm install playwright             # 처음 한 번 (크로미움: npx playwright install chromium)
```

## 시험

| 명령 | 하는 일 |
|---|---|
| `node prototype/tests/screens.js pc` | PC(1366×900)로 23개 화면을 차례로 누르며 자바스크립트 오류 · 실패한 단계를 찾는다 |
| `node prototype/tests/screens.js m` | 같은 것을 휴대폰(390×844)으로 |
| `node prototype/tests/screens.js pc 사진폴더 before` | 화면마다 사진도 찍는다 → 고친 뒤 `after` 로 다시 찍어 나란히 비교 |
| `node prototype/tests/share-open-book.js` | 책 읽기 화면 「공유」가 펼친 그 책을 보내는지 (11-19 제보 되풀이 막기) |

- 끝 코드 0 = 통과, 1 = 실패 (사유를 출력).
- 다른 파일을 보려면 `FILE=/경로/index.html`, 주소 뒤 값을 더하려면 `Q='&tone=buttons'`.
- 23개 화면: 첫화면 · 로그인창 · 처음가기 · 이용안내 · 시작고르기 · 내 이야기 · 초대주소 · 엽서보드 · 엽서 펼치기 · 주인공 고르기 · 이름 고치기 · 엽서 고르기 · 문체 고르기 · 만드는 중 · 초안 · 초안 글 수정 · 책장 · 책 읽기 · 보기 설정 · 인터뷰(말로) · 인터뷰(글로) · 글 보낸 뒤 · 마치기 확인.
- 실제 서버 · 실제 휴대폰에서만 드러나는 것(녹음, 목소리, 마이크 표시)은 이 시험으로 확인할 수 없다.
