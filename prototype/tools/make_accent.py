"""자주색(버건디 · 장미색) → 웜톤 덮어쓰기 CSS 를 만든다.
python3 tools/make_accent.py app app/warm-accent.css   (pip install tinycss2 필요 — 색을 바꿀 CSS 를 고친 뒤 다시 돌린다)

화면 CSS 를 읽어, 값에 자주 계열 색(색상각 300~359°, 채도 0.12 이상)이 든 선언만 골라
`html.tone-warm-btn <원래 선택자>` 로 같은 속성을 웜톤 색으로 다시 적는다. @media 는 그대로 감싼다.
읽기 화면 · 코르크 보드 · 책장 · 엽서 그림 같은 「소재 색」 파일은 건드리지 않는다.
"""
import colorsys
import os
import re
import sys

import tinycss2

APP, OUT = sys.argv[1], sys.argv[2]
SKIP = {'ebook-reader.css', 'reader-book.css', 'reader-spread.css', 'reader-turn.css', 'reader-arrows.css',
        'postcards-cork.css', 'library-view.css', 'library-pull.css', 'library-arrive.css', 'radio-art.css',
        'book-pdf.css', 'warm-tone.css', 'warm-accent.css', 'bookk-font.css', 'cover-font.css'}
# index.html 에 걸린 순서대로 (나중 규칙이 이기는 순서를 지킨다)
html = open(os.path.join(APP, 'index.html'), encoding='utf-8').read()
files = [f for f in re.findall(r'<link rel="stylesheet" href="([^"]+)">', html) if os.path.basename(f) not in SKIP]

HEX = re.compile(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b')
TARGET_H = 22 / 360  # 테라코타


def purple(h):
    r, g, b = h[:3]
    H, L, S = colorsys.rgb_to_hls(r, g, b)
    return (H * 360 >= 300) and S >= 0.12 and 0.04 < L < 0.985


def parse(hx):
    if len(hx) == 3:
        hx = ''.join(c * 2 for c in hx)
    v = [int(hx[i:i + 2], 16) / 255 for i in range(0, len(hx), 2)]
    return v


def warm(m):
    hx = m.group(1)
    v = parse(hx)
    if not purple(v):
        return m.group(0)
    H, L, S = colorsys.rgb_to_hls(*v[:3])
    # 버튼과 같은 테라코타 계열이 되게 채도를 맞춘다 (밝기만 원래 색을 따른다)
    S2 = 0.72 if L > 0.86 else 0.58 if L > 0.6 else 0.52 if L > 0.3 else 0.45
    r, g, b = colorsys.hls_to_rgb(TARGET_H, L, S2)
    out = '#%02x%02x%02x' % (round(r * 255), round(g * 255), round(b * 255))
    if len(v) == 4:
        out += '%02x' % round(v[3] * 255)
    return out


def has_purple(text):
    return any(purple(parse(m.group(1))) for m in HEX.finditer(text))


def scoped(sel):
    parts = []
    for one in sel.split(','):
        one = one.strip()
        if not one:
            continue
        if one.startswith(':root'):
            parts.append('html.tone-warm-btn' + one[5:])
        elif one.startswith('html'):
            parts.append('html.tone-warm-btn' + one[4:])
        else:
            parts.append('html.tone-warm-btn ' + one)
    return ', '.join(parts)


def rules(nodes, indent=''):
    out = []
    for n in nodes:
        if n.type == 'qualified-rule':
            sel = tinycss2.serialize(n.prelude).strip()
            if '::backdrop' in sel and 'dialog' in sel and False:
                continue
            decls = tinycss2.parse_declaration_list(n.content, skip_whitespace=True, skip_comments=True)
            keep = []
            for d in decls:
                if d.type != 'declaration':
                    continue
                val = tinycss2.serialize(d.value)
                if has_purple(val):
                    keep.append(f'{d.name}: {HEX.sub(warm, val).strip()}{" !important" if d.important else ""}')
            if keep:
                out.append(f'{indent}{scoped(sel)} {{ {"; ".join(keep)}; }}')
        elif n.type == 'at-rule' and n.lower_at_keyword in ('media', 'supports') and n.content:
            inner = rules(tinycss2.parse_rule_list(n.content, skip_whitespace=True, skip_comments=True), indent + '  ')
            if inner:
                out.append(f'{indent}@{n.at_keyword} {tinycss2.serialize(n.prelude).strip()} {{')
                out.extend(inner)
                out.append(f'{indent}}}')
    return out


lines = ['/* ═══ 자주색 → 웜톤 (자동 생성: prototype/tools/make_accent.py) ═══',
         '   html.tone-warm-btn 일 때, 화면 CSS 에서 자주 · 버건디 · 장미 계열 색이 든 선언만 같은 밝기의 테라코타 계열로 다시 적는다.',
         '   손으로 고치지 말고 다시 만든다. 읽기 화면 · 코르크 보드 · 책장 · 엽서 그림 색은 건드리지 않는다. */']
total = 0
for f in files:
    css = open(os.path.join(APP, f), encoding='utf-8').read()
    got = rules(tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True))
    if got:
        lines.append(f'\n/* {f} */')
        lines.extend(got)
        total += len(got)
open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('rules', total, 'from', len(files), 'files')
