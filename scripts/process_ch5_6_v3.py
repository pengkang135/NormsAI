"""Process Chapter 5/6 sections - V3: precise per-row processing with debug output."""
import json
import re
import sys
from pathlib import Path

PROMPT_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\prompts")
MD_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\md")

OCR_FIXES = {
    "围抢": "围堰", "围捻": "围堰",
    "瘦班": "艘班",
    "混凝士": "混凝土",
    "箕他材料": "其他材料",
    "腹带式起重机": "履带式起重机",
    "内然空压机": "内燃空压机",
    "内燃李压机": "内燃空压机",
    "设施摊消费": "设施摊销费",
}

def fix_text(t):
    for old, new in OCR_FIXES.items():
        t = t.replace(old, new)
    t = re.sub(r'(\d)\.\s+(\d)', r'\1.\2', t)
    return t.strip()

def clean_num(s):
    s = s.strip().replace(' ', '')
    return s

def parse_page_blocks(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    page_data = {}
    for m in re.finditer(r'####\s*页\s*(\d+)\s*\((\d+)\s*blocks?\)\s*\n```json\n(.*?)\n```', content, re.DOTALL):
        page_num = int(m.group(1))
        try:
            blks = json.loads(m.group(3))
            for b in blks:
                if 't' in b:
                    b['x'] = float(b.get('x', 0))
                    b['y'] = float(b.get('y', 0))
            page_data[page_num] = blks
        except:
            pass
    return page_data

def extract_info(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    info = {}
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('- 章节：'):
            info['chapter'] = line.split('：', 1)[1].strip() or '第六章 引桥及护岸'
        elif line.startswith('- 节：'):
            info['section'] = line.split('：', 1)[1].strip()
        elif line.startswith('- 分项：'):
            info['sub'] = line.split('：', 1)[1].strip()
        elif line.startswith('- 页码范围：'):
            nums = re.findall(r'\d+', line)
            info['pages'] = [int(n) for n in nums]
        elif line.startswith('- 定额编号范围：'):
            nums = re.findall(r'\d+', line)
            info['codes'] = [int(n) for n in nums]
        elif line.startswith('- 代码列数：'):
            info['code_cols'] = int(re.findall(r'\d+', line)[0])
        elif line.startswith('- 单位：'):
            info['unit'] = line.split('：', 1)[1].strip()
        elif line.startswith('- 工程内容：'):
            raw = line.split('：', 1)[1].strip()
            # Remove OCR artifact
            raw = re.sub(r'顺序号[\dA-Za-z]+', '', raw).strip()
            raw = re.sub(r'定额编号\d+', '', raw).strip()
            raw = re.sub(r'^工程内容：', '', raw).strip()
            info['content'] = raw
    return info

def get_sorted_rows(blocks, gap=8):
    """Group blocks by y and return sorted rows."""
    if not blocks:
        return []
    sb = sorted(blocks, key=lambda b: (b['y'], b['x']))
    rows = []
    cur = [sb[0]]
    cy = sb[0]['y']
    for b in sb[1:]:
        if abs(b['y'] - cy) < gap:
            cur.append(b)
        else:
            rows.append(sorted(cur, key=lambda x: x['x']))
            cur = [b]
            cy = b['y']
    if cur:
        rows.append(sorted(cur, key=lambda x: x['x']))
    return rows

def identify_columns(blocks):
    """Find定额编号 column x-positions. Returns sorted list of (x_center, code_name)."""
    candidates = []
    for b in blocks:
        t = b['t'].strip()
        if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999:
            candidates.append((b['x'], int(t), b['y']))

    if not candidates:
        return []

    candidates.sort(key=lambda x: x[0])
    clusters = []
    cur = [candidates[0]]
    for c in candidates[1:]:
        if abs(c[0] - cur[-1][0]) < 30 and abs(c[2] - cur[-1][2]) < 30:
            cur.append(c)
        else:
            clusters.append(cur)
            cur = [c]
    if cur:
        clusters.append(cur)

    result = []
    for cl in clusters:
        avg_x = sum(c[0] for c in cl) / len(cl)
        # Pick the most common code (for multi-page sections, same x may have different codes)
        code_counts = {}
        for _, code, _ in cl:
            code_counts[code] = code_counts.get(code, 0) + 1
        best_code = max(code_counts, key=code_counts.get)
        result.append((avg_x, str(best_code)))

    result.sort(key=lambda x: x[0])
    return result


def process_page(blocks, page_num, info, prompt_name):
    """Generate clean markdown output for one page."""
    chapter = '第五章 基础工程' if prompt_name.startswith('section_s18') else '第六章 引桥及护岸'
    section = info.get('section', '')
    sub = info.get('sub', '')
    unit = info.get('unit', '')
    content = info.get('content', '')

    columns = identify_columns(blocks)
    if not columns:
        rows = get_sorted_rows(blocks)
        md = f'---\npage: {page_num}\ntype: chapter_text\nchapter: {chapter}\nsection: {section}\n---\n\n# 第{page_num}页\n\n'
        for r in rows:
            line = ' '.join(fix_text(b['t']) for b in r)
            if line.strip():
                md += line.strip() + '\n\n'
        return md

    col_x = [c[0] for c in columns]
    col_codes = [c[1] for c in columns]
    first_col = min(col_x)

    rows = get_sorted_rows(blocks, gap=8)

    # Build frontmatter
    md = f'---\npage: {page_num}\ntype: chapter_text\nchapter: {chapter}\nsection: {section}\n---\n\n# 第{page_num}页\n\n'
    md += f'{sub}\n\n'
    if content:
        cleaner = re.sub(r'顺序号[\dA-Za-z]+', '', content).strip()
        cleaner = re.sub(r'定额编号\d+', '', cleaner).strip()
        cleaner = re.sub(r'^工程内容：', '', cleaner).strip()
        if cleaner:
            md += f'工程内容：{cleaner}  {unit}\n\n'

    # Determine if this page has a secondary table (水上运距)
    # Check for "水上运距" or "每增" keywords
    has_secondary = False
    secondary_start_y = 9999
    for r in rows:
        text = ' '.join(b['t'] for b in r)
        if '水上运距' in text and '每增' in text:
            has_secondary = True
            secondary_start_y = min(b['y'] for b in r)
        elif '每增' in text and '1km' in text:
            if secondary_start_y > 500:
                has_secondary = True
                secondary_start_y = min(secondary_start_y, min(b['y'] for b in r))

    # Split into main table rows and secondary table rows
    main_rows = []
    secondary_rows = []

    # Find data start (after headers)
    data_start = 0
    for i, r in enumerate(rows):
        text = ' '.join(b['t'] for b in r)
        if any(kw in text for kw in ['定额编号', '顺序号']) and any(c in text for c in col_codes):
            data_start = i
            break

    # Skip header rows
    header_end = data_start + 1
    for i in range(data_start + 1, min(data_start + 8, len(rows))):
        r = rows[i]
        text = ' '.join(b['t'] for b in r)
        avg_y = sum(b['y'] for b in r) / len(r)
        # Skip sub-headers like 项目, 单位
        if any(kw == text.strip() for kw in ['项目', '单位', '顺序', '顺序号']):
            header_end = i + 1
        elif avg_y < secondary_start_y - 10:
            # Check if this is a sub-header row (attribute names)
            is_subheader = False
            for b in r:
                if b['t'].strip() in ['项目', '单位', '制作', '安装', '箱型', '结构']:
                    is_subheader = True
            if is_subheader:
                header_end = i + 1
            else:
                break
        else:
            break

    # Separate main and secondary rows
    for i, r in enumerate(rows):
        avg_y = sum(b['y'] for b in r) / len(r)
        if i < header_end:
            continue
        # Skip title/header rows
        text = ' '.join(b['t'] for b in r)
        if text.strip() in ['项目', '单位', '定额编号', '顺序号', '顺序']:
            continue

        if has_secondary and avg_y > secondary_start_y - 15:
            secondary_rows.append(r)
        else:
            main_rows.append(r)

    # Write定额编号 header
    code_line = '定额编号'
    for c in col_codes:
        code_line += f'  {c}'
    md += f'{code_line}\n\n'

    # Add sub-header hints from header rows
    for i in range(data_start + 1, header_end):
        r = rows[i]
        left_texts = []
        right_texts = []
        for b in r:
            t = fix_text(b['t'])
            if b['x'] < first_col - 10:
                left_texts.append(t)
            else:
                right_texts.append((b['x'], t))

        if not left_texts:
            continue
        label = ' '.join(left_texts)
        if label in ['项目', '单位', '顺序号', '顺序', '定额编号']:
            continue

        # Check if there are column sub-headers (like 制作/安装, or 600/1100 etc.)
        if right_texts:
            # This is a column sub-header row, output it
            vals = [''] * len(col_x)
            for x, t in right_texts:
                best = 0
                best_d = 9999
                for j, cx in enumerate(col_x):
                    d = abs(x - cx)
                    if d < best_d:
                        best_d = d
                        best = j
                if best_d < 80:
                    vals[best] = t
            line = label
            for v in vals:
                line += f'  {v}' if v else '  '
            md += f'{line}\n'

    # Process main data rows
    for r in main_rows:
        left_texts = []
        right_items = []
        for b in r:
            t = fix_text(b['t'])
            if b['x'] < first_col - 10:
                left_texts.append(t)
            else:
                right_items.append((b['x'], t))

        # Filter page number artifacts (located at far right, bottom)
        if not left_texts:
            continue

        item = ' '.join(left_texts)

        # Skip pure page numbers
        if re.match(r'^\d{2,3}\s*-?\s*$', item.strip()):
            continue

        # Map values to columns
        vals = [''] * len(col_x)
        for x, t in right_items:
            best = 0
            best_d = 9999
            for j, cx in enumerate(col_x):
                d = abs(x - cx)
                if d < best_d:
                    best_d = d
                    best = j
            if best_d < 90:
                vals[best] = clean_num(t)

        # Check if ALL values are empty (sequence number only row)
        if all(v == '' for v in vals):
            # This is likely an attribute label row
            md += f'{item}\n'
            continue

        line = item
        for v in vals:
            line += f'  {v}' if v else '  —'
        md += f'{line}\n'

    # Secondary table (水上运距)
    if secondary_rows:
        md += f'\n'
        # Write secondary header
        sec_code_line = '定额编号'
        for c in col_codes:
            sec_code_line += f'  {c}'
        md += f'{sec_code_line}\n\n'

        for r in secondary_rows:
            left_texts = []
            right_items = []
            for b in r:
                t = fix_text(b['t'])
                if b['x'] < first_col - 10:
                    left_texts.append(t)
                else:
                    right_items.append((b['x'], t))

            if not left_texts:
                continue
            item = ' '.join(left_texts)
            if re.match(r'^\d{2,3}\s*-?\s*$', item.strip()):
                continue

            vals = [''] * len(col_x)
            for x, t in right_items:
                best = 0
                best_d = 9999
                for j, cx in enumerate(col_x):
                    d = abs(x - cx)
                    if d < best_d:
                        best_d = d
                        best = j
                if best_d < 90:
                    vals[best] = clean_num(t)

            line = item
            for v in vals:
                line += f'  {v}' if v else '  —'
            md += f'{line}\n'

    # Check for附注
    for r in rows:
        text = ''.join(fix_text(b['t']) for b in r)
        if text.startswith('附注') or '附注：' in text:
            clean = text.replace('附注：', '附注：').strip()
            if len(clean) > 5:
                md += f'\n{clean}\n'

    return md


def main():
    sections = [
        'section_s182.md',
        'section_s185.md',
        'section_s190.md',
        'section_s191.md',
        'section_s192.md',
        'section_s193.md',
        'section_s194.md',
        'section_s195.md',
        'section_s196.md',
        'section_s197.md',
        'section_s198.md',
        'section_s199.md',
    ]

    MD_DIR.mkdir(parents=True, exist_ok=True)
    all_pages = []

    for sfile in sections:
        print(f"\n=== {sfile} ===")
        filepath = PROMPT_DIR / sfile
        if not filepath.exists():
            print(f"  NOT FOUND")
            continue

        info = extract_info(filepath)
        page_data = parse_page_blocks(filepath)
        pages = info.get('pages', list(page_data.keys()))

        for pnum in pages:
            if pnum not in page_data:
                continue
            blocks = page_data[pnum]
            md_text = process_page(blocks, pnum, info, sfile)
            out_path = MD_DIR / f'page_{pnum:04d}.md'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(md_text)
            print(f"  page_{pnum:04d}.md: {len(md_text)} chars, {md_text.count(chr(10))} lines")
            all_pages.append(pnum)

    print(f"\nTotal: {len(all_pages)} pages")

if __name__ == '__main__':
    main()
