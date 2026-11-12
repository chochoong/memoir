"""prototype/app/ (화면 원본) → prototype/index.html (서버가 내보내는 파일 하나).

    python prototype/build.py

CSS · JS · 그림 · 글꼴을 모두 index.html 안에 넣는다. app/ 의 원본은 바꾸지 않는다.
화면을 고칠 때는 app/ 를 고치고 이 스크립트를 다시 돌린 뒤 index.html 을 함께 커밋한다.
"""
import base64, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'app')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'index.html')


def read(p):
    with open(os.path.join(SRC, p), encoding='utf-8') as f:
        return f.read()


def data_uri(p):
    with open(os.path.join(SRC, p), 'rb') as f:
        b = f.read()
    mime = {'svg': 'image/svg+xml', 'woff2': 'font/woff2', 'png': 'image/png'}[p.rsplit('.', 1)[1]]
    return f'data:{mime};base64,' + base64.b64encode(b).decode()


SVG = data_uri('book-illustration.svg')


def fix_css(css, base):
    # @charset 은 따로 떨어진 .css 파일에서만 뜻이 있다 — <style> 안에서는 무시되고 편집기가 오류로 표시한다
    css = re.sub(r'^\ufeff?@charset[^;]*;\s*', '', css)
    def u(m):
        ref = m.group(1).strip('\'"')
        if ref.startswith(('data:', 'http', '#')):
            return m.group(0)
        return f'url("{data_uri(os.path.normpath(os.path.join(base, ref)))}")'
    return re.sub(r'url\(([^)]*)\)', u, css)


html = read('index.html')
html = re.sub(r'<link rel="stylesheet" href="([^"]+)">',
              lambda m: f'<style data-from="{m.group(1)}">\n' + fix_css(read(m.group(1)), os.path.dirname(m.group(1))) + '\n</style>',
              html)
scripts = re.findall(r'<script src="([^"]+)" defer></script>', html)
html = re.sub(r'\s*<script src="[^"]+" defer></script>', '', html)
js = '\n'.join(f'<script data-from="{s}">\n' + read(s).replace('"book-illustration.svg"', f'"{SVG}"').replace('</script', '<\\/script') + '\n</script>'
               for s in scripts)
html = html.replace('"book-illustration.svg"', f'"{SVG}"')
assert html.count('</body>') == 1
html = html.replace('</body>', js + '\n</body>')
with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
    f.write(html)
print(f'scripts {len(scripts)} · {len(html) / 1024:.0f} KB → {os.path.relpath(OUT)}')
