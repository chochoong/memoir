# 표지 전용 무료 명조 폰트

이 폴더의 `memoir-cover-serif-600-ko.woff2`는 기존 서체 비교 시안에 보관돼 있던 **Noto Serif KR** 원본에서 만든 표지 전용 파생본이다. 사용자가 선택한 B 방향인 미세 질감·무광·명조체를 책장 표지에 적용하기 위한 파일이다. 일반 UI·본문·독서 리더의 서체는 바꾸지 않는다.

## 출처와 라이선스

- 재사용한 로컬 원본: `C:/Users/nda01/.codex/visualizations/2026/11/09/01a1bf4c-e6ca-76a1-956a-16925fe50f78/type-preview/assets/NotoSerifKR.ttf`
- 함께 있던 라이선스: 같은 `assets/`의 `OFL.txt`. 이 폴더에 `OFL-NotoSerifKR.txt`로 원문 그대로 보관했다.
- 원본 메타데이터: typographic family `Noto Serif KR`, 가변 축 `wght` 200–900, 기본값 200. legacy family가 `Noto Serif KR ExtraLight`로 표시되는 것은 가변폰트의 기본 인스턴스 이름이며, 제품용 파생본은 600으로 정적화했다.
- 원본에 들어 있는 라이선스: SIL Open Font License 1.1. 원본의 저작권·라이선스·라이선스 URL 이름 레코드를 파생본에도 보존했다.
- 원본 공식 프로젝트 참고: [Google Fonts / Noto Serif KR](https://github.com/google/fonts/tree/main/ofl/notoserifkr). 이번 작업은 기존 로컬 파일을 재사용했으며 폰트 파일을 새로 다운로드하지 않았다. 정확한 로컬 입력·출력 SHA-256과 파일 크기는 `cover-font-metadata.json`에 기록한다.

## 처리와 지원 범위

- `wght=600`으로 정적화하고 WOFF2로 압축했다. 파생 family는 `Memoir Cover Serif`, subfamily는 `SemiBold`로 명확히 구분했다.
- 현대 한글 완성형 **U+AC00–D7A3의 11,172자 전체**와 출력 가능한 ASCII 전체를 자동 검증한다. 프리뷰의 고정 문구용 `subset.woff2`는 사용하지 않았다.
- Latin, 한글 Jamo·호환 Jamo·확장 Jamo, 일반·CJK 문장부호, 통화·전각 문자 범위에서 원본이 제공하는 문자를 포함했다. 정확한 요청 범위와 최종 매핑 수는 메타데이터에 기록한다.
- 한자·범위 밖 문자 또는 원본에도 없는 글리프는 CSS의 Batang/바탕/serif 폴백을 사용한다. 모든 유니코드 문자나 모든 한자의 지원을 주장하지 않는다.
- `cover-font.css`는 600 굵기 한 개만 선언하고 `font-display: swap`을 사용한다. `library-view.css`의 국소 `--cover-serif`를 통해 책 표지의 live 제목에만 연결한다.
- 기존 제목 21px/600, 태블릿·모바일 18px, 좁은 화면 20px, 줄간격 1.65를 유지하고 자간만 -0.05em에서 -0.02em으로 완화했다. 표지·책장 크기, 3색 순환, 본문·리더 레이아웃은 유지한다.

## 재생성

`build-cover-font.py`는 입력 폰트 경로를 명시적으로 받아 같은 폴더에 WOFF2와 메타데이터를 만든다. 원본 24MB TTF를 제품에 복사하거나 OS 폰트로 설치하지 않는다.

PowerShell 예시(패키지는 작업용 temp 경로에만 설치):

```powershell
python -m pip install --target "$env:TEMP/codex-cover-fonttools" "fonttools[woff]==4.68.0"
$env:PYTHONPATH = "$env:TEMP/codex-cover-fonttools"
python ./build-cover-font.py --source '원본 NotoSerifKR.ttf의 절대 경로'
```

실제 작업 패키지: fonttools 4.68.0, brotli 1.2.1, zopfli 0.4.3. 작업 temp 이외의 전역 Python·OS에는 설치하지 않았다. 생성 후 다시 WOFF2를 열어 600 정적 굵기·임베딩 fsType 0·완성형 한글 전체·ASCII 전체를 검증한다.
