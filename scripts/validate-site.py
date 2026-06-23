#!/usr/bin/env python3
from pathlib import Path
import re, sys
root=Path(__file__).resolve().parents[1]
errors=[]
htmls=sorted(root.glob('*.html'))+sorted((root/'docs').glob('*.html'))
for f in htmls:
    text=f.read_text()
    if '</html>' not in text.lower(): errors.append(f'{f.relative_to(root)} missing </html>')
    if '<title>' not in text.lower(): errors.append(f'{f.relative_to(root)} missing <title>')
    for href in re.findall(r'href="([^"]+)"', text):
        if href.startswith(('http://','https://','mailto:','#','data:')): continue
        href=href.split('#',1)[0]
        if not href: continue
        target=(f.parent/href).resolve()
        try: target.relative_to(root.resolve())
        except ValueError: continue
        if not target.exists(): errors.append(f'{f.relative_to(root)} broken href {href}')
for asset in ['assets/hero.png','assets/character.png','assets/telegram-mobile-hero.png','css/styles.css','js/main.js','docs/style.css']:
    if not (root/asset).exists(): errors.append(f'missing {asset}')
if errors:
    print('\n'.join(errors)); sys.exit(1)
print(f'validated {len(htmls)} html files and required assets')
