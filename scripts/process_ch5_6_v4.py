"""Process Chapter 5/6 sections - V4: fixed code detection, multi-table, merged values."""
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
}

def fix_text(t):
    for old, new in OCR_FIXES.items():
        t = t.replace(old, new)
    t = re.sub(r'(\d)\.\s+(\d)', r'\1.\2', t)
    return t.strip()

def clean_num(s):
    return s.strip().replace(' ', '')

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
    # First find the "定额编号" label
    dn_y = None
    for b in blocks:
        if b['t'].strip() == '定额编号' and 100 < b['y'] < 200:
            dn_y = b['y']
            break

    if dn_y is None:
        # Try broader search
        for b in blocks:
            if '定额编号' in b['t'] and 100 < b['y'] < 200:
                dn_y = b['y']
                break

    # Collect 4-digit numbers only near the定额编号 row (±20 y range)
    code_blocks = []
    for b in blocks:
        t = b['t'].strip()
        if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999:
            if dn_y and abs(b['y'] - dn_y) < 25:
                code_blocks.append((b['x'], int(t)))
            elif dn_y is None:
                code_blocks.append((b['x'], int(t)))

    if not code_blocks:
        # Try broader: look for consecutive 4-digit numbers in same y-range
        for b in blocks:
            t = b['t'].strip()
            if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999 and 100 < b['y'] < 200:
                code_blocks.append((b['x'], int(t)))

    if not code_blocks:
        return []

    code_blocks.sort(key=lambda x: x[0])

    # Cluster
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
    # Look for patterns like NNNN.NN
    parts = re.findall(r'\d{3,6}\.\d{2}', text)
    if len(parts) > 1:
        return parts
    # Try with possible OCR errors (missing decimal)
    parts = re.findall(r'\d{4,}', text)
    if len(parts) > 2:
        # Insert decimals: assuming format is either NNNN.NN or NNNNN.NN
        result = []
        for p in parts:
            if len(p) >= 5:
                result.append(p[:-2] + '.' + p[-2:])
            else:
                result.append(p)
        return result
    return [text]

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
        # Heuristic: keep only columns where codes match expected range
        expected_codes = set(str(c) for c in info.get('codes', []))
        if expected_codes:
            columns = [c for c in columns if c[1] in expected_codes]
            columns = columns[:code_cols]
        else:
            columns = columns[:code_cols]

    if not columns:
        # Text-only page fallback
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

    # Find定额编号 row index
    code_row_idx = None
    for i, r in enumerate(rows):
        text = ' '.join(b['t'] for b in r)
        if '定额编号' in text and any(c in text for c in col_codes):
            code_row_idx = i
            break

    if code_row_idx is None:
        code_row_idx = 0

    # Skip header rows (定额编号 + sub-headers)
    data_start = code_row_idx + 1
    for i in range(data_start, min(data_start + 10, len(rows))):
        r = rows[i]
        text = ' '.join(b['t'] for b in r).strip()
        avg_y = sum(b['y'] for b in r) / len(r)
        # Skip obvious header keywords
        if text in ['项目', '单位', '顺序', '顺序号']:
            data_start = i + 1
        elif any(b['t'].strip() in ['项目', '单位', '顺序号'] for b in r if b['x'] < first_col - 10):
            data_start = i + 1
        else:
            break

    # Process remaining rows
    for i in range(data_start, len(rows)):
        r = rows[i]
        avg_y = sum(b['y'] for b in r) / len(r)

        # Skip page number artifacts
        text = ' '.join(b['t'] for b in r)
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

    #定额编号 header
    code_line = '定额编号'
    for c in col_codes:
        code_line += f'  {c}'
    md += f'{code_line}\n\n'

    # Sub-header attributes
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

        vals = [''] * len(col_x)
        for x, t in right:
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
                    # Distribute parts across columns starting from this one
                    for pi, part in enumerate(parts):
                        if vi + pi < len(vals):
                            vals[vi + pi] = part

        line = item
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
            vals = [''] * len(col_x)
            for x, t in right:
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

    return md


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
