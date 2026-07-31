"""Process Chapter 5 final + Chapter 6 sections from agent prompt files to markdown output."""
import json
import re
import sys
from pathlib import Path

PROMPT_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\prompts")
MD_DIR = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\Norms-AI\output\md")

# OCR corrections
OCR_FIXES = {
    "围抢": "围堰", "围捻": "围堰",
    "般土方": "一般土方", "冻士": "冻土",
    "瘦班": "艘班", "艘班": "艘班",
    "32400t方驳": "400t方驳",
    "33294kW拖轮": "294kW拖轮",
    "混凝士": "混凝土",
    "箕他材料": "其他材料",
    "腰瘦嫂台台台台组": "艘班",
    "内然空压机": "内燃空压机",
    "内燃李压机": "内燃空压机",
    "腹带式起重机": "履带式起重机",
    "%元": "%",
    "陆运、装船、运输、吊装定位加固": "陆运、装船、运输、吊装定位加固",
    "台台台台组": "",
    "设施摊消费": "设施摊销费",
}

def fix_ocr(text):
    for old, new in OCR_FIXES.items():
        text = text.replace(old, new)
    text = text.replace("  ", " ").strip()
    # Fix spacing in numbers
    text = re.sub(r'(\d)\.\s+(\d)', r'\1.\2', text)
    return text

def parse_blocks_from_prompt(filepath):
    """Extract OCR blocks from a prompt markdown file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find all JSON block arrays
    all_blocks = []
    for match in re.finditer(r'```json\s*\n(.*?)\n```', content, re.DOTALL):
        try:
            blocks = json.loads(match.group(1))
            # Normalize blocks to have x, y, t, c
            for b in blocks:
                if 't' not in b:
                    continue
                b['x'] = b.get('x', 0)
                b['y'] = b.get('y', 0)
            all_blocks.extend(blocks)
        except json.JSONDecodeError:
            continue
    return all_blocks

def extract_page_info(filepath):
    """Extract page context from prompt."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    info = {}
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('- 章节：'):
            info['chapter'] = line.split('：')[1].strip() or ''
        elif line.startswith('- 节：'):
            info['section'] = line.split('：')[1].strip()
        elif line.startswith('- 分项：'):
            info['sub'] = line.split('：')[1].strip()
        elif line.startswith('- 页码范围：'):
            pages_str = line.split('：')[1].strip()
            pages = re.findall(r'\d+', pages_str)
            info['pages'] = [int(p) for p in pages]
        elif line.startswith('- 定额编号范围：'):
            codes_str = line.split('：')[1].strip()
            codes = re.findall(r'\d+', codes_str)
            info['codes'] = [int(c) for c in codes]
        elif line.startswith('- 代码列数：'):
            info['code_cols'] = int(re.findall(r'\d+', line)[0])
        elif line.startswith('- 单位：'):
            info['unit'] = line.split('：')[1].strip()
        elif line.startswith('- 工程内容：'):
            info['content'] = line.split('：', 1)[1].strip()
    return info

def group_by_y(blocks, threshold=12):
    """Group blocks by y coordinate."""
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=lambda b: (b['y'], b['x']))
    groups = []
    current = [sorted_blocks[0]]
    current_y = sorted_blocks[0]['y']
    for b in sorted_blocks[1:]:
        if abs(b['y'] - current_y) < threshold:
            current.append(b)
        else:
            groups.append(sorted(current, key=lambda x: x['x']))
            current = [b]
        current_y = b['y']
    if current:
        groups.append(sorted(current, key=lambda x: x['x']))
    return groups

def clean_number(val):
    """Clean up a numeric value string."""
    val = val.strip()
    val = val.replace(' ', '')
    # Fix common OCR decimal issues
    val = re.sub(r'^\.\s*(\d)', r'0.\1', val)
    return val

def process_section(prompt_file, output_pages):
    """Process a single section prompt file and generate md files."""
    filepath = PROMPT_DIR / prompt_file
    if not filepath.exists():
        print(f"  SKIP: {prompt_file} not found")
        return

    info = extract_page_info(filepath)
    blocks = parse_blocks_from_prompt(filepath)

    if not blocks:
        print(f"  SKIP: no blocks in {prompt_file}")
        return

    pages = info.get('pages', [])
    if not pages:
        print(f"  SKIP: no pages for {prompt_file}")
        return

    # Split blocks by page if multiple pages
    # For multi-page sections, blocks are grouped under "#### 页 XXX" headers

    # Re-parse to get page-separated blocks
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    page_blocks = {}
    # Find each page section
    page_sections = re.finditer(r'####\s*页\s*(\d+)\s*\((\d+)\s*blocks?\)\s*\n```json\n(.*?)\n```', content, re.DOTALL)
    for m in page_sections:
        page_num = int(m.group(1))
        try:
            blks = json.loads(m.group(3))
            for b in blks:
                if 't' in b:
                    b['x'] = b.get('x', 0)
                    b['y'] = b.get('y', 0)
            page_blocks[page_num] = blks
        except json.JSONDecodeError:
            continue

    if not page_blocks:
        print(f"  SKIP: no page blocks found in {prompt_file}")
        return

    for page_num in pages:
        if page_num not in page_blocks:
            print(f"  SKIP page {page_num}: no blocks")
            continue

        blks = page_blocks[page_num]
        md_text = generate_markdown(blks, page_num, info, prompt_file)

        out_path = MD_DIR / f'page_{page_num:04d}.md'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(md_text)
        print(f"  Wrote: page_{page_num:04d}.md ({len(md_text)} chars)")

def generate_markdown(blocks, page_num, info, prompt_file):
    """Generate markdown from OCR blocks for a single page."""
    section = info.get('section', '')
    sub = info.get('sub', '')
    unit = info.get('unit', '')
    content = info.get('content', '')

    # Determine chapter
    chapter = ''
    if prompt_file.startswith('section_s18'):
        chapter = '第五章 基础工程'
    elif prompt_file.startswith('section_s19'):
        chapter = '第六章 引桥及护岸'

    # Group blocks by y
    lines = group_by_y(blocks, threshold=10)

    # Identify定额编号 positions (4-digit numbers)
    code_blocks = []
    for b in blocks:
        t = b['t'].strip()
        if re.match(r'^\d{4}$', t):
            code_blocks.append(b)

    # Sort codes by x position
    code_blocks.sort(key=lambda b: b['x'])
    code_positions = [(b['x'], b['t']) for b in code_blocks]

    # Deduplicate codes (keep unique ones at similar x)
    unique_codes = []
    seen_x = {}
    for x, code in code_positions:
        found = False
        for sx in seen_x:
            if abs(x - sx) < 20:
                found = True
                break
        if not found:
            unique_codes.append(code)
            seen_x[x] = code

    code_cols = info.get('code_cols', len(unique_codes))

    # Get code x-clusters
    code_x_values = [b['x'] for b in code_blocks]
    if not code_x_values:
        return f"---\npage: {page_num}\ntype: chapter_text\n---\n\n# 第{page_num}页\n\n"

    # Cluster codes into N columns
    code_x_values.sort()
    clusters = []
    current_cluster = [code_x_values[0]]
    for x in code_x_values[1:]:
        if abs(x - current_cluster[-1]) < 20:
            current_cluster.append(x)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [x]
    if current_cluster:
        clusters.append(sum(current_cluster) / len(current_cluster))

    # Build frontmatter
    fm = {
        'page': page_num,
        'type': 'chapter_text',
    }
    if chapter:
        fm['chapter'] = chapter
    if section:
        fm['section'] = section

    md = '---\n'
    for k, v in fm.items():
        md += f'{k}: {v}\n'
    md += '---\n\n'
    md += f'# 第{page_num}页\n\n'

    # Title
    md += f'{sub}\n\n'

    # 工程内容
    if content:
        md += f'工程内容：{content}  {unit}\n\n'

    # Identify the table header rows (before data starts, roughly y < 250)
    header_lines = []
    data_start_y = 0
    for line_blocks in lines:
        avg_y = sum(b['y'] for b in line_blocks) / len(line_blocks)
        texts = [b['t'] for b in line_blocks]
        line_text = ' '.join(texts)

        # Check if this is header
        if any(kw in line_text for kw in ['定额编号', '顺序号', '项目', '单位']):
            header_lines.append(line_blocks)
            data_start_y = max(data_start_y, avg_y)

    # Find the actual data start (after all headers and sub-headers)
    data_start_y += 5

    # Process data lines
    data_lines = []
    for line_blocks in lines:
        avg_y = sum(b['y'] for b in line_blocks) / len(line_blocks)
        if avg_y <= data_start_y:
            continue

        # Skip page number lines
        texts = [b['t'] for b in line_blocks]
        line_text = ' '.join(texts)
        if len(texts) == 1 and re.match(r'^\d{3}\s*-?$', texts[0].strip()):
            continue
        if len(texts) == 1 and re.match(r'^\d{2,3}$', texts[0].strip()) and avg_y > 650:
            continue

        data_lines.append(line_blocks)

    # Map data values to code columns
    # Each data line has: item_name (left) + values (aligned to columns)

    # Identify which blocks are item names (left side, x < ~450)
    # and which are values (x > minimum code column x - margin)
    min_code_x = min(clusters) if clusters else 450

    output_lines = []

    # First, build the定额编号 header line
    code_line = '定额编号'
    for c in unique_codes[:code_cols]:
        code_line += f'  {c}'
    output_lines.append(code_line)
    output_lines.append('')

    # Process each data line
    # We need to identify the item name (leftmost text) and map values to columns
    current_seq = 0

    for line_blocks in data_lines:
        texts = []
        for b in line_blocks:
            texts.append((b['x'], fix_ocr(b['t'])))

        texts.sort(key=lambda t: t[0])

        # Separate left (item name) from right (values)
        left_texts = [t for x, t in texts if x < min_code_x - 20]
        right_texts = [(x, t) for x, t in texts if x >= min_code_x - 20]

        if not left_texts:
            continue

        item_name = ' '.join(left_texts)
        item_name = fix_ocr(item_name)

        # Skip header-like rows
        if item_name in ['项目', '单位', '顺序', '定额编号', '顺序号']:
            continue

        # Check if this is a sequence number row
        seq_match = re.match(r'^(\d{1,2})$', item_name)
        if seq_match:
            current_seq = int(seq_match.group(1))
            continue

        # Map values to columns
        values = [''] * len(clusters)
        for x, t in right_texts:
            # Find nearest column cluster
            best_col = 0
            best_dist = 999
            for i, cx in enumerate(clusters):
                dist = abs(x - cx)
                if dist < best_dist:
                    best_dist = dist
                    best_col = i
            if best_dist < 60:
                val = clean_number(t)
                values[best_col] = val

        # Build output line
        # Format: item_name  [unit]  val1  val2  val3 ...
        line = item_name
        # Check if we should add a unit from previous context
        # (units typically appear as standalone blocks near item names)

        # Add values
        for v in values[:code_cols]:
            if v:
                line += f'  {v}'
            else:
                line += '  —'

        output_lines.append(line)

    md += '\n'.join(output_lines)
    md += '\n\n'

    # Check for附注 (note after table)
    for line_blocks in lines:
        texts = [fix_ocr(b['t']) for b in line_blocks]
        line_text = ''.join(texts)
        if '附注' in line_text:
            md += f'{line_text}\n\n'

    return md

def main():
    sections = [
        # Chapter 5 final sections
        ('section_s182.md', '水下基础', '每10m'),
        ('section_s185.md', '码头钢筋焊接', '每10m'),
        # Chapter 6
        ('section_s190.md', '引桥及护岸 - 金属栈桥制作', '每1t'),
        ('section_s191.md', '引桥梁板安装', '每10榀'),
        ('section_s192.md', '钢管桩制作', '每1t'),
        ('section_s193.md', '栏杆制作安装', ''),
        ('section_s194.md', '钢灯架制作安装', '每1t'),
        ('section_s195.md', '钢管式灯架', '每1t'),
        ('section_s196.md', '岸电箱制作安装', ''),
        ('section_s197.md', '钢撑杆制作安装', '每1t'),
        ('section_s198.md', '橡胶护舷安装', '每10套'),
        ('section_s199.md', '引桥安装', '每10榀'),
    ]

    MD_DIR.mkdir(parents=True, exist_ok=True)

    for prompt_file, desc, unit in sections:
        print(f"\nProcessing: {prompt_file} ({desc})")
        process_section(prompt_file, None)

    print("\nDone!")

if __name__ == '__main__':
    main()
