"""Process Chapter 5/6 sections from agent prompts to markdown output - V2 with precise column mapping."""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

PROMPT_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\prompts")
MD_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\md")

OCR_FIXES = {
    "围抢": "围堰", "围捻": "围堰",
    "般土方": "一般土方", "冻士": "冻土",
    "瘦班": "艘班",
    "32400t方驳": "400t方驳",
    "33294kW拖轮": "294kW拖轮",
    "混凝士": "混凝土",
    "箕他材料": "其他材料",
    "腰瘦嫂台台台台组": "艘班",
    "内然空压机": "内燃空压机",
    "内燃李压机": "内燃空压机",
    "腹带式起重机": "履带式起重机",
    "136t履带式起重机": "36t履带式起重机",
    "设施摊消费": "设施摊销费",
    "内然": "内燃",
}

def fix_ocr(text):
    for old, new in OCR_FIXES.items():
        text = text.replace(old, new)
    text = re.sub(r'(\d)\.\s+(\d)', r'\1.\2', text)
    return text.strip()

def parse_page_blocks(filepath):
    """Parse all page-specific OCR blocks from a prompt file."""
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
        except json.JSONDecodeError as e:
            print(f"  JSON error on page {page_num}: {e}")
    return page_data

def extract_info(filepath):
    """Extract metadata from prompt file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    info = {}
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('- 章节：'):
            info['chapter'] = line.split('：', 1)[1].strip()
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
            info['content'] = line.split('：', 1)[1].strip()
    return info

def find_code_columns(blocks, num_cols):
    """Find the X positions of定额编号 columns by looking for 4-digit codes."""
    codes = []
    for b in blocks:
        t = b['t'].strip()
        if re.match(r'^\d{4}$', t) and 1000 <= int(t) <= 6999:
            codes.append((b['x'], int(t)))

    # Cluster by x proximity
    codes.sort(key=lambda x: x[0])
    clusters = []
    current = [codes[0]]
    for i in range(1, len(codes)):
        if abs(codes[i][0] - current[-1][0]) < 25:
            current.append(codes[i])
        else:
            clusters.append(current)
            current = [codes[i]]
    if current:
        clusters.append(current)

    # For each cluster, take the x-center and the code that appears most
    col_x = []
    col_codes = []
    for cl in clusters:
        avg_x = sum(c[0] for c in cl) / len(cl)
        # Get deduplicated codes in this cluster (usually 1 or 2 per cluster for multi-page)
        seen = set()
        unique_codes = []
        for x, code in cl:
            if code not in seen:
                unique_codes.append(code)
                seen.add(code)
        col_x.append(avg_x)
        col_codes.append(unique_codes)  # list of codes at this x position
    return col_x, col_codes

def group_blocks_y(blocks, gap=10):
    """Group blocks into rows by y-coordinate."""
    if not blocks:
        return []
    sorted_b = sorted(blocks, key=lambda b: (b['y'], b['x']))
    groups = []
    current = [sorted_b[0]]
    cur_y = sorted_b[0]['y']
    for b in sorted_b[1:]:
        if abs(b['y'] - cur_y) < gap:
            current.append(b)
        else:
            groups.append(sorted(current, key=lambda x: x['x']))
            current = [b]
            cur_y = b['y']
    if current:
        groups.append(sorted(current, key=lambda x: x['x']))
    return groups

def clean_num(s):
    """Clean a numeric string."""
    s = s.strip()
    s = s.replace(' ', '')
    s = re.sub(r'^\.\s*(\d)', r'0.\1', s)
    return s

def process_page_to_md(blocks, page_num, info, prompt_name):
    """Generate markdown for a single page."""
    chapter = '第五章 基础工程' if prompt_name.startswith('section_s18') else '第六章 引桥及护岸'
    section = info.get('section', '')
    sub = info.get('sub', '')
    unit = info.get('unit', '')
    content = info.get('content', '')
    num_cols = info.get('code_cols', 3)

    col_x, col_codes = find_code_columns(blocks, num_cols)

    if not col_x:
        # No codes found - text page
        rows = group_blocks_y(blocks)
        md = f'---\npage: {page_num}\ntype: chapter_text\n'
        if chapter:
            md += f'chapter: {chapter}\n'
        if section:
            md += f'section: {section}\n'
        md += f'---\n\n# 第{page_num}页\n\n'
        for r in rows:
            line = ' '.join(fix_ocr(b['t']) for b in r)
            if line.strip():
                md += f'{line.strip()}\n\n'
        return md

    # Sort columns left to right
    sorted_cols = sorted(zip(col_x, col_codes), key=lambda x: x[0])
    col_x = [c[0] for c in sorted_cols]
    col_codes = [c[1] for c in sorted_cols]

    # Determine which codes to display (use first code from each cluster for primary display)
    display_codes = []
    for codes in col_codes:
        display_codes.append(str(codes[0]))  # Use the first code as representative

    # Group blocks by y
    rows = group_blocks_y(blocks, gap=8)

    # Determine data area (after headers)
    # Header rows contain 定额编号, 顺序号, 项目, 单位 etc.
    data_start_idx = 0
    for i, r in enumerate(rows):
        text = ''.join(b['t'] for b in r)
        if any(kw in text for kw in ['定额编号', '顺序号']):
            data_start_idx = i + 1
            # Continue past sub-headers
            for j in range(i+1, min(i+8, len(rows))):
                sub_text = ''.join(b['t'] for b in rows[j])
                if any(kw in sub_text for kw in ['项目', '单位', '顺序']):
                    data_start_idx = j + 1
                else:
                    break

    # Build output
    md = f'---\npage: {page_num}\ntype: chapter_text\n'
    if chapter:
        md += f'chapter: {chapter}\n'
    if section:
        md += f'section: {section}\n'
    md += f'---\n\n# 第{page_num}页\n\n'
    md += f'{sub}\n\n'
    if content:
        # Clean duplicate prefixes
        clean_content = content
        md += f'工程内容：{clean_content}  {unit}\n\n'

    # 定额编号 header line
    code_header = '定额编号'
    for c in display_codes:
        code_header += f'  {c}'
    md += f'{code_header}\n\n'

    # Process data rows
    first_col_x = min(col_x) - 20
    data_rows = rows[data_start_idx:]

    # Current attribute row tracking
    current_attrs = []

    for row in data_rows:
        row_texts = [(float(b['x']), fix_ocr(b['t'])) for b in row]
        row_texts.sort(key=lambda x: x[0])

        # Filter out page number blocks
        filtered = []
        for x, t in row_texts:
            if re.match(r'^\d{2,3}\s*-?\s*$', t.strip()) and x > 900:
                continue
            if t.strip() in ['项目', '单位', '定额编号', '顺序号']:
                continue
            filtered.append((x, t))

        if not filtered:
            continue

        # Separate left (item names) from right (values)
        left_parts = []
        right_parts = []

        for x, t in filtered:
            if x < first_col_x:
                left_parts.append(t)
            else:
                right_parts.append((x, t))

        if not left_parts:
            continue

        item_name = ' '.join(left_parts)

        # Handle sequence number at start of line
        seq_match = re.match(r'^(\d{1,2})$', item_name)
        if seq_match and len(right_parts) == 0:
            current_attrs.append(item_name)
            continue

        # Map right values to columns
        values = [''] * len(col_x)
        for x, t in right_parts:
            best_idx = 0
            best_dist = 9999
            for i, cx in enumerate(col_x):
                dist = abs(x - cx)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            if best_dist < 80:
                values[best_idx] = clean_num(t)

        # Build the output line
        line = item_name
        for v in values:
            if v:
                line += f'  {v}'
            else:
                line += '  —'
        md += f'{line}\n'

    # Check for附注
    remaining_rows = rows[data_start_idx + len(data_rows):] if data_start_idx + len(data_rows) < len(rows) else []
    for r in rows:
        text = ''.join(fix_ocr(b['t']) for b in r)
        if text.startswith('附注') or '附注：' in text:
            md += f'\n{text}\n'

    return md


def process_section(prompt_file):
    """Process a single section prompt file."""
    filepath = PROMPT_DIR / prompt_file
    if not filepath.exists():
        print(f"  SKIP: {prompt_file} not found")
        return []

    info = extract_info(filepath)
    page_data = parse_page_blocks(filepath)

    if not page_data:
        print(f"  SKIP: no page data in {prompt_file}")
        return []

    pages = info.get('pages', list(page_data.keys()))
    written = []

    for page_num in pages:
        if page_num not in page_data:
            print(f"  SKIP page {page_num}: not in data")
            continue

        blocks = page_data[page_num]
        md_text = process_page_to_md(blocks, page_num, info, prompt_file)

        out_path = MD_DIR / f'page_{page_num:04d}.md'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(md_text)
        print(f"  page_{page_num:04d}.md ({len(md_text)} chars)")
        written.append(page_num)

    return written


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

    for s in sections:
        print(f"\n{s}:")
        pages = process_section(s)
        if pages:
            all_pages.extend(pages)

    print(f"\nTotal: {len(all_pages)} pages written: {sorted(all_pages)}")

if __name__ == '__main__':
    main()
