"""표지 글꼴 줄이기 — 현대 한글 11,172자 → 자주 쓰는 2,350자(KS X 1001 완성형).

    python prototype/tools/subset_cover_font.py

입력: app/fonts/memoir-cover-serif-600-ko.woff2 (그대로 둔다 — 덮어쓰지 않는다)
출력: app/fonts/memoir-cover-serif-600-ko-ks.woff2 + cover-font-ks-metadata.json
필요: fonttools[woff]==4.68.0 (brotli 포함)

한글 완성형 가운데 KS X 1001 의 2,350자만 남기고, 한글이 아닌 글자(영문 · 숫자 · 문장부호 · 자모 등)는
원본이 가진 것을 모두 남긴다. 빠진 드문 글자(예: 똠 · 햏)는 cover-font.css 의 Batang/바탕/serif 로 그려진다.
표지 글꼴은 Noto Serif KR(SIL OFL 1.1) 파생본이라 잘라 써도 된다. 본문 글꼴(부크크 명조)은 사용 허락을
확인하기 전이라 잘라내지 않는다 (PROVENANCE-bookk.md).
"""
import hashlib, json
from pathlib import Path
from fontTools import subset
from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parent.parent / 'app' / 'fonts'
SRC, OUT = FONTS / 'memoir-cover-serif-600-ko.woff2', FONTS / 'memoir-cover-serif-600-ko-ks.woff2'
KS = {c for c in range(0xAC00, 0xD7A4) if len(chr(c).encode('euc_kr')) == 2}
assert len(KS) == 2350

font = TTFont(SRC)
cmap = set(font.getBestCmap())
keep = sorted(c for c in cmap if not (0xAC00 <= c <= 0xD7A3) or c in KS)
opt = subset.Options()
opt.flavor = 'woff2'; opt.recalc_timestamp = False
opt.name_IDs = ['*']; opt.name_legacy = True; opt.name_languages = ['*']
opt.layout_features = ['*']; opt.notdef_outline = True
sub = subset.Subsetter(options=opt)
sub.populate(unicodes=keep)
sub.subset(font)
font.flavor = 'woff2'
font.save(OUT)

got = set(TTFont(OUT).getBestCmap())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
meta = {
    'source_file': SRC.name, 'source_bytes': SRC.stat().st_size, 'source_sha256': sha(SRC),
    'derived_file': OUT.name, 'derived_bytes': OUT.stat().st_size, 'derived_sha256': sha(OUT),
    'hangul_kept': sum(1 for c in got if 0xAC00 <= c <= 0xD7A3), 'hangul_set': 'KS X 1001 완성형 2,350자',
    'ks_complete': KS <= got, 'non_hangul_kept': sum(1 for c in got if not 0xAC00 <= c <= 0xD7A3),
    'non_hangul_same_as_source': {c for c in cmap if not 0xAC00 <= c <= 0xD7A3} == {c for c in got if not 0xAC00 <= c <= 0xD7A3},
    'printable_ascii_complete': all(c in got for c in range(0x20, 0x7F)),
    'license': 'SIL Open Font License 1.1 (OFL-NotoSerifKR.txt)',
}
(FONTS / 'cover-font-ks-metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False, indent=1))
