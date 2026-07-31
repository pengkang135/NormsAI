"""
提取JTS/T 276-1-2019前50页文本+坐标 → output/text/page_XXXX.json
"""
import fitz, json, re, sys
from pathlib import Path
from collections import defaultdict

PDF = Path(r'F:\BaiduSyncdisk\2.清单定额\1 预算定额\3 水工定额\JTS∕T 276-1-2019 沿海港口水工建筑工程定额（非正式出版稿）.pdf')
OUT = Path(r'F:\BaiduSyncdisk\2.清单定额\Norms-AI\output\text')
OUT.mkdir(parents=True, exist_ok=True)

PAGES = range(1, 51)  # pages 1-50 (0-indexed: 0-49)

doc = fitz.open(str(PDF))

for pg in PAGES:
    page = doc[pg - 1]
    blocks = page.get_text("dict")["blocks"]

    lines = []
    for b in blocks:
        if b["type"] == 0:
            for line in b.get("lines", []):
                text = ''.join([span['text'] for span in line.get('spans', [])]).strip()
                if not text:
                    continue
                bbox = line['bbox']
                lines.append({
                    'x': round(bbox[0], 1),
                    'y': round(bbox[1], 1),
                    'x2': round(bbox[2], 1),
                    'y2': round(bbox[3], 1),
                    'text': text,
                })

    lines.sort(key=lambda l: (l['y'], l['x']))

    # Detect internal page number from footer
    internal_page = None
    footer_lines = [l for l in lines if l['y'] > page.rect.height - 60]
    for l in footer_lines:
        m = re.match(r'^-\s*(\d+)\s*-$', l['text'])
        if m:
            internal_page = int(m.group(1))
            break

    img_blocks = sum(1 for b in blocks if b["type"] == 1)
    text_blocks = sum(1 for b in blocks if b["type"] == 0)

    data = {
        'page': pg,
        'pdf_page': pg,
        'internal_page': internal_page,
        'source': 'pymupdf_text',
        'page_width': round(page.rect.width, 1),
        'page_height': round(page.rect.height, 1),
        'lines': lines,
        'text_blocks_count': text_blocks,
        'image_blocks_count': img_blocks,
    }

    out_path = OUT / f'page_{pg:04d}.json'
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    if pg % 10 == 0:
        print(f'  Page {pg:3d} ({len(lines):4d} lines, internal={internal_page})')

doc.close()
print(f'\nDone! {len(PAGES)} pages → {OUT}')
