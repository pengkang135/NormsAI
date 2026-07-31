"""Auto-convert text-dominant OCR pages to markdown.

Usage:
    python scripts/text_to_md.py --pages 1-18,20-22 [--dry-run]
"""

import sys
import json
import re
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OCR_DIR, MD_DIR

# Known page types from OCR analysis
PAGE_TYPES = {
    1: 'title_page',
    2: 'title_page',
    3: 'notice',
    4: 'toc',
    5: 'toc',
    6: 'toc',
    7: 'toc',
    8: 'toc',
    9: 'toc',
    10: 'toc',
    11: 'toc',
    12: 'toc',
    13: 'toc',
    14: 'toc',
    15: 'toc',
    16: 'toc',
    17: 'toc',
    18: 'toc',
    19: 'chapter_divider',
    20: 'chapter_text',
    21: 'chapter_text',
    22: 'chapter_text',
    23: 'appendix',
    24: 'appendix',
    25: 'appendix',
    26: 'appendix',
    27: 'appendix',
    28: 'appendix',
}


def group_blocks_by_y(blocks, gap=12):
    """Group OCR blocks into lines by y-coordinate proximity."""
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=lambda b: (b['y1'], b['x1']))
    groups = []
    current = [sorted_blocks[0]]
    current_y = sorted_blocks[0]['y1']
    for b in sorted_blocks[1:]:
        if abs(b['y1'] - current_y) < gap:
            current.append(b)
            current_y = (current_y + b['y1']) / 2
        else:
            groups.append(sorted(current, key=lambda x: x['x1']))
            current = [b]
            current_y = b['y1']
    groups.append(sorted(current, key=lambda x: x['x1']))
    return groups


def blocks_to_text(blocks):
    """Convert a group of blocks to a single text line, merging overlapping x-ranges."""
    if not blocks:
        return ""
    # Sort by x, merge overlapping blocks
    blocks = sorted(blocks, key=lambda b: b['x1'])
    text = blocks[0]['text']
    for i in range(1, len(blocks)):
        prev = blocks[i - 1]
        curr = blocks[i]
        gap = curr['x1'] - prev['x2']
        if gap > 20:
            text += "  " + curr['text']
        elif gap > 0:
            text += " " + curr['text']
        else:
            text += curr['text']
    return text


def detect_type_from_ocr(blocks):
    """Heuristic page type detection."""
    text = ' '.join(b['text'] for b in blocks)
    if any(kw in text for kw in ['交通部文件', '交水发']):
        return 'notice'
    if any(kw in text for kw in ['总说明', '目录']):
        return 'toc'
    if '附表' in text and any(kw in text for kw in ['分类表', '分级表']):
        return 'appendix'
    if re.search(r'第[一二三四五六七八九十]+章', text) and len(blocks) < 8:
        return 'chapter_divider'
    if '说明' in text and len(blocks) > 5:
        return 'chapter_text'
    return 'chapter_text'


def text_page_to_md(blocks, page_num):
    """Convert a text-dominant page to markdown."""
    page_type = PAGE_TYPES.get(page_num) or detect_type_from_ocr(blocks)
    lines = group_blocks_by_y(blocks)

    # Determine chapter context
    chapter = ''
    section = ''
    all_text = ' '.join(b['text'] for b in blocks)

    ch_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    ch_match = re.search(r'第([一二三四五六七八九十]+)章\s*(\S+)', all_text)
    if ch_match:
        ch_str = ch_match.group(1)
        ch_num = ch_map.get(ch_str, 1)
        chapter = f'第{ch_num}章 {ch_match.group(2)}'

    sec_match = re.search(r'第([一二三四五六七八九十]+)节\s*(\S+)', all_text)
    if sec_match:
        section = f'第{sec_match.group(1)}节 {sec_match.group(2)}'

    fm = {
        'page': page_num,
        'type': page_type,
    }
    if chapter:
        fm['chapter'] = chapter
        fm['section'] = section

    md = '---\n'
    for k, v in fm.items():
        md += f'{k}: {v}\n'
    md += '---\n\n'
    md += f'# 第{page_num}页\n\n'

    for line_blocks in lines:
        text = blocks_to_text(line_blocks)
        text = text.strip()
        if not text:
            continue
        if text and not text.isdigit() and len(text) > 1:
            md += f'{text}\n\n'

    return md, page_type


def main():
    parser = argparse.ArgumentParser(description='Convert text pages from OCR to markdown')
    parser.add_argument('--pages', default='1-18,20-22', help='Page range')
    parser.add_argument('--dry-run', action='store_true', help='Print only, do not write')
    args = parser.parse_args()

    pages = set()
    for part in args.pages.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))

    md_dir = Path(MD_DIR)
    md_dir.mkdir(parents=True, exist_ok=True)

    type_counts = defaultdict(int)
    for p in sorted(pages):
        ocr_path = Path(OCR_DIR) / f'ocr_{p:04d}.json'
        if not ocr_path.exists():
            print(f"  SKIP page {p}: no OCR data")
            continue

        with open(ocr_path, 'r', encoding='utf-8') as f:
            blocks = json.load(f)

        md_text, ptype = text_page_to_md(blocks, p)
        type_counts[ptype] += 1

        if args.dry_run:
            print(f"\n--- page {p} ({ptype}) ---")
            print(md_text[:300])
        else:
            out_path = md_dir / f'page_{p:04d}.md'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(md_text)
            print(f"  page_{p:04d}: {ptype} ({len(md_text)} chars)")

    print(f"\nGenerated: {dict(type_counts)}")


if __name__ == '__main__':
    main()
