"""Process Chapter 5/6 sections - V5: fix duplicate headers, unit leakage, page artifacts."""
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
    "腹带": "履带",
    "内然": "内燃",
    "内燃李压机": "内燃空压机",
    "设施摊消费": "设施摊销费",
    "Ⅰt": "1t",
    "Ⅰ": "1",
}

UNIT_WORDS = {'台班', '艘班', '工日', '单位', '项目', '定额编号', '顺序号', '顺序'}

def fix_text(t):
    for old, new in OCR_FIXES.items():
        t = t.replace(old, new)
    t = re.sub(r'(\d)\.\s+(\d)', r'\1.\2', t)
    return t.strip()

def clean_num(s):
    s = s.strip().replace(' ', '').replace(',', '.')
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
            v = line.split('：', 1)[1].strip()
            info['chapter'] = v if v else '第六章 引桥及护岸'
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
            raw = re.sub(r'顺序号[\dA-Za-z]+', '', raw).strip()
            raw = re.sub(r'定额编号\d+', '', raw).strip()
            raw = re.sub(r'^工程内容：', '', raw).strip()
            info['content'] = raw
    return info

def get_rows(blocks, gap=8):
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
    """Find code columns. Only consider blocks in the定额编号 header row area (y ~150-170)."""
    dn_y = None
    for b in blocks:
        if b['t'].strip() == '定额编号' and 100 < b['y'] < 200:
            dn_y = b['y']
            break

    if dn_y is None:
        for b in blocks:
            if '定额编号' in b['t'] and 100 < b['y'] < 200:
                dn_y = b['y']
                break

    code_blocks = []
    for b in blocks:
        t = b['t'].strip()
        if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999:
            if dn_y and abs(b['y'] - dn_y) < 25:
                code_blocks.append((b['x'], int(t)))
            elif dn_y is None:
                code_blocks.append((b['x'], int(t)))

    if not code_blocks:
        for b in blocks:
            t = b['t'].strip()
            if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999 and 100 < b['y'] < 200:
                code_blocks.append((b['x'], int(t)))

    if not code_blocks:
        return []

    code_blocks.sort(key=lambda x: x[0])

    clusters = []
    cur = [code_blocks[0]]
    for c in code_blocks[1:]:
        if abs(c[0] - cur[-1][0]) < 25:
            cur.append(c)
        else:
            clusters.append(cur)
            cur = [c]
    if cur:
        clusters.append(cur)

    result = []
    for cl in clusters:
        avg_x = sum(c[0] for c in cl) / len(cl)
        code_counts = {}
        for _, code in cl:
            code_counts[code] = code_counts.get(code, 0) + 1
        best_code = max(code_counts, key=code_counts.get)
        result.append((avg_x, str(best_code)))

    result.sort(key=lambda x: x[0])
    return result

def split_merged_baseprice(text):
    """Split merged base price strings like '3854.184486.631438.36' into parts."""
    parts = re.findall(r'\d{3,6}\.\d{2}', text)
    if len(parts) > 1:
        return parts
    parts = re.findall(r'\d{4,}', text)
    if len(parts) > 2:
        result = []
        for p in parts:
            if len(p) >= 5:
                result.append(p[:-2] + '.' + p[-2:])
            else:
                result.append(p)
        return result
    return [text]

def is_page_artifact(text):
    """Check if text is a page number artifact like '424 424 —' or '432 432 二'."""
    t = text.strip()
    if re.match(r'^\d{3}\s*[\s\-–—]*\s*\d{3}\s*[二三四五六七八九]?\s*[\-–—]*\s*$', t):
        return True
    if re.match(r'^\d{3}[\s\-–—]+$', t):
        return True
    if re.match(r'^\d{3}\s*二?\s*$', t):
        return True
    return False

def generate_markdown(blocks, page_num, info, prompt_name):
    chapter = '第五章 基础工程' if prompt_name.startswith('section_s18') else '第六章 引桥及护岸'
    section = info.get('section', '')
    sub = info.get('sub', '')
    unit = info.get('unit', '')
    content = info.get('content', '')
    code_cols = info.get('code_cols', 3)

    columns = identify_columns(blocks)

    # Limit to expected number of columns
    if len(columns) > code_cols:
        expected_codes = set(str(c) for c in info.get('codes', []))
        if expected_codes:
            columns = [c for c in columns if c[1] in expected_codes]
            columns = columns[:code_cols]
        else:
            columns = columns[:code_cols]

    if not columns:
        rows = get_rows(blocks)
        md = f'---\npage: {page_num}\ntype: chapter_text\nchapter: {chapter}\nsection: {section}\n---\n\n# 第{page_num}页\n\n{sub}\n\n'
        if content:
            md += f'工程内容：{content}  {unit}\n\n'
        for r in rows:
            line = ' '.join(fix_text(b['t']) for b in r).strip()
            if line and len(line) > 1:
                md += line + '\n\n'
        return md

    col_x = [c[0] for c in columns]
    col_codes = [c[1] for c in columns]
    first_col = min(col_x)

    rows = get_rows(blocks, gap=8)

    # Detect secondary table (水上运距附加费)
    secondary_y = 9999
    for r in rows:
        text = ' '.join(b['t'] for b in r)
        if ('水上运距' in text and ('每增' in text or 'km' in text)) or \
           ('每增' in text and '1km' in text and any(b['y'] > 450 for b in r)):
            secondary_y = min(secondary_y, min(b['y'] for b in r))

    has_secondary = secondary_y < 9000

    # Find which rows are in main vs secondary table
    main_rows = []
    sec_rows = []
    header_rows = []

    # Find first定额编号 row (there may be two - take the first)
    code_row_indices = []
    for i, r in enumerate(rows):
        text = ' '.join(b['t'] for b in r)
        if '定额编号' in text and any(c in text for c in col_codes):
            code_row_indices.append(i)

    code_row_idx = code_row_indices[0] if code_row_indices else 0

    # Skip header rows (定额编号 + sub-headers)
    data_start = code_row_idx + 1
    for i in range(data_start, min(data_start + 10, len(rows))):
        r = rows[i]
        text = ' '.join(b['t'] for b in r).strip()
        avg_y = sum(b['y'] for b in r) / len(r)
        if text in ['项目', '单位', '顺序', '顺序号']:
            data_start = i + 1
        elif any(b['t'].strip() in ['项目', '单位', '顺序号'] for b in r if b['x'] < first_col - 10):
            data_start = i + 1
        else:
            break

    # Process remaining rows, skip any extra定额编号 rows
    for i in range(data_start, len(rows)):
        r = rows[i]
        avg_y = sum(b['y'] for b in r) / len(r)

        # Skip rows that are duplicate定额编号 headers
        text = ' '.join(b['t'] for b in r)
        left_text = ' '.join(fix_text(b['t']) for b in r if b['x'] < first_col - 10)
        if left_text.strip() == '定额编号' or '定额编号' in left_text.split():
            continue

        # Skip page number artifacts
        if is_page_artifact(text.strip()):
            continue
        if re.match(r'^\d{2,3}\s*-?\s*$', text.strip()) and avg_y > 600:
            continue

        if has_secondary and avg_y > secondary_y - 15:
            sec_rows.append(r)
        else:
            main_rows.append(r)

    # Build output
    md = f'---\npage: {page_num}\ntype: chapter_text\nchapter: {chapter}\nsection: {section}\n---\n\n# 第{page_num}页\n\n{sub}\n\n'
    if content:
        cleaner = re.sub(r'顺序号[\dA-Za-zB]+', '', content).strip()
        cleaner = re.sub(r'定额编号\d+', '', cleaner).strip()
        cleaner = re.sub(r'^工程内容：', '', cleaner).strip()
        if cleaner:
            md += f'工程内容：{cleaner}  {unit}\n\n'

    #定额编号 header (only once)
    code_line = '定额编号'
    for c in col_codes:
        code_line += f'  {c}'
    md += f'{code_line}\n\n'

    # Sub-header attribute rows (e.g., 项目/单位, or attribute groupings)
    for i in range(code_row_idx + 1, data_start):
        r = rows[i]
        left = [fix_text(b['t']) for b in r if b['x'] < first_col - 10]
        right = [(b['x'], fix_text(b['t'])) for b in r if b['x'] >= first_col - 10]
        if not left:
            continue
        label = ' '.join(left)
        if label in ['项目', '单位', '顺序号', '顺序', '定额编号']:
            continue
        vals = [''] * len(col_x)
        for x, t in right:
            if t in UNIT_WORDS:
                continue
            best = 0
            best_d = 9999
            for j, cx in enumerate(col_x):
                d = abs(x - cx)
                if d < best_d:
                    best_d = d
                    best = j
            if best_d < 90:
                vals[best] = t
        line = label
        for v in vals:
            line += f'  {v}' if v else '  '
        md += f'{line}\n'

    # Main data rows
    for r in main_rows:
        left = [fix_text(b['t']) for b in r if b['x'] < first_col - 10]
        right = [(b['x'], fix_text(b['t'])) for b in r if b['x'] >= first_col - 10]
        if not left:
            continue
        item = ' '.join(left)
        if item.strip() in ['项目', '单位', '定额编号', '顺序号', '顺序']:
            continue
        if is_page_artifact(item.strip()):
            continue

        vals = [''] * len(col_x)
        for x, t in right:
            if t in UNIT_WORDS:
                continue
            best = 0
            best_d = 9999
            for j, cx in enumerate(col_x):
                d = abs(x - cx)
                if d < best_d:
                    best_d = d
                    best = j
            if best_d < 90:
                vals[best] = clean_num(t)

        # Handle merged base price values
        for vi in range(len(vals)):
            v = vals[vi]
            if v and len(v) > 15 and '.' in v:
                parts = split_merged_baseprice(v)
                if len(parts) > 1:
                    for pi, part in enumerate(parts):
                        if vi + pi < len(vals):
                            vals[vi + pi] = part

        # Skip rows where ALL values are empty AND the item is a sequence number
        if not item.strip():
            continue

        line = item
        has_data = any(v for v in vals)
        for v in vals:
            line += f'  {v}' if v else '  —'
        md += f'{line}\n'

    # Secondary table
    if sec_rows:
        md += f'\n定额编号'
        for c in col_codes:
            md += f'  {c}'
        md += '\n\n'
        for r in sec_rows:
            left = [fix_text(b['t']) for b in r if b['x'] < first_col - 10]
            right = [(b['x'], fix_text(b['t'])) for b in r if b['x'] >= first_col - 10]
            if not left:
                continue
            item = ' '.join(left)
            if re.match(r'^\d{2,3}\s*-?\s*$', item.strip()):
                continue
            if is_page_artifact(item.strip()):
                continue
            if item.strip() == '定额编号':
                continue
            vals = [''] * len(col_x)
            for x, t in right:
                if t in UNIT_WORDS:
                    continue
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
            clean = text.strip()
            if len(clean) > 5 and clean not in md:
                md += f'\n{clean}\n'

    # Post-process: remove duplicate consecutive定额编号 headers
    lines = md.split('\n')
    cleaned = []
    prev_was_code_header = False
    for line in lines:
        stripped = line.strip()
        is_code_header = bool(re.match(r'^定额编号\s+\d{4}', stripped))
        if is_code_header and prev_was_code_header:
            continue  # Skip duplicate
        # Also skip blank lines between duplicate定额编号 headers
        if is_code_header:
            # Remove trailing blank(s) before this header if previous was already a header
            while cleaned and cleaned[-1].strip() == '':
                cleaned.pop()
            prev_was_code_header = True
        elif stripped != '':
            prev_was_code_header = False
        elif stripped == '':
            # Keep blanks but track them
            pass
        cleaned.append(line)

    # Remove trailing artifact lines
    while cleaned and is_page_artifact(cleaned[-1].strip()):
        cleaned.pop()

    return '\n'.join(cleaned)


def main():
    sections = [
        ('section_s182.md', [434]),
        ('section_s185.md', [437]),
        ('section_s190.md', [442, 443]),
        ('section_s191.md', [444, 445]),
        ('section_s192.md', [446, 447]),
        ('section_s193.md', [448, 449, 450]),
        ('section_s194.md', [451, 452]),
        ('section_s195.md', [453, 454]),
        ('section_s196.md', [455]),
        ('section_s197.md', [456, 457, 458]),
        ('section_s198.md', [459, 460]),
        ('section_s199.md', [461, 462]),
    ]

    MD_DIR.mkdir(parents=True, exist_ok=True)

    for sfile, expected_pages in sections:
        print(f"\n=== {sfile} ===")
        filepath = PROMPT_DIR / sfile
        if not filepath.exists():
            print(f"  NOT FOUND")
            continue

        info = extract_info(filepath)
        page_data = parse_page_blocks(filepath)

        for pnum in expected_pages:
            if pnum not in page_data:
                print(f"  page_{pnum:04d}: NO DATA")
                continue
            blocks = page_data[pnum]
            columns = identify_columns(blocks)
            print(f"  Columns: {[(c[1], round(c[0])) for c in columns]}")
            md_text = generate_markdown(blocks, pnum, info, sfile)
            out_path = MD_DIR / f'page_{pnum:04d}.md'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(md_text)
            print(f"  page_{pnum:04d}.md: {len(md_text)} chars")

    print("\nDone!")

if __name__ == '__main__':
    main()
