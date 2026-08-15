"""
JTS/T 276-1-2019 前50页: 页面分类 + 结构构建 + MD生成
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict, OrderedDict

ROOT = Path(r'E:\Code\Norms-AI')
TEXT_DIR = ROOT / 'output' / 'text'
MD_DIR = ROOT / 'output' / 'md_jts'
MD_DIR.mkdir(parents=True, exist_ok=True)

# ---- Constants (from extract_1d.py) ----
ATTR_NAME_RE = re.compile(r'(类别|级别|长度|厚度|深度|直径|高度|宽度|斗容|吨位|桩长|孔深|面积|体积|运距|截面|形式|规格|型号|等级|标号|强度|坡度|类型)')
IMPLICIT_ATTR_VAL_RE = re.compile(r'^[ⅠⅡⅢⅣⅤⅥVIIVIIIⅨⅩIVXLCDM一二三四五六七八九十]+[\s]*(类土|类|级)$')
FUSION_ATTR_RE = re.compile(r'^([一-鿿]{1,4})(\d+(?:\.\d+)?)(.*)$')
NOTE_RE = re.compile(r'^注[：:：]')
UNIT_WORDS = {'工日','台班','元','m3','m²','m³','m','t','kg','10m3','100m3','100m2','艘班','组','根','榀','%','件','个','块','套','只','条','片','座','处','段','延长米','榀','根','块'}
LEFT_LABEL_WORDS = {'顺序号','项目','单位','代码','序号','顺','序','号'}
COST_KEYWORDS = {'人工','材料','机械','船机','基价','其他材料','其他船机','板枋材','铁件','钢材','钢丝绳','卸扣','螺栓','混凝土','砂浆'}
NOISE_PATTERNS = [re.compile(r'^-\s*\d+\s*-$'), re.compile(r'^[.]$')]
SECTION_LABEL_RE = re.compile(r'^(一般土方|冻土|水上|陆上|岩石|砂土|黏土|淤泥|砾石|卵石|碎石|块石|片石)$')


def load_page(pg):
    return json.loads((TEXT_DIR / f'page_{pg:04d}.json').read_text(encoding='utf-8'))


# ========== PAGE CLASSIFICATION ==========

def classify_page(data):
    """Classify a page into one of the standard types."""
    lines = data['lines']
    full_text = ' '.join(l['text'] for l in lines)
    header_text = ' '.join(l['text'] for l in lines if l['y'] < 60)
    page_height = data['page_height']

    # Chapter title pages: few lines, contains "第X章"
    if re.search(r'第[一二三四五六七八九十]+章', full_text) and len(lines) < 6:
        return 'chapter_title'

    if len(lines) < 3:
        return 'blank'

    # Cover pages: ICS, 行业标准, etc.
    if any(kw in full_text for kw in ['ICS', '中华人民共和国行业标准', '主编单位', '批准部门']):
        if len(lines) < 10:
            return 'blank'
        return 'cover'

    # Notice pages
    if any(kw in full_text for kw in ['公告', '第57号', '修订说明']):
        return 'notice'

    # TOC pages: have "目 次" or dense toc entries with page numbers
    if '目 次' in header_text:
        return 'toc'
    # TOC continuation pages: dense list of entries with leader dots and page numbers
    toc_entries = [l for l in lines if '....' in l['text'] or re.search(r'\.{3,}', l['text'])]
    if len(toc_entries) >= 5:
        return 'toc'

    # General instructions
    if '总说明' in header_text or '总说明' in full_text[:50]:
        return 'general_instruction'

    # Appendix
    if '附加说明' in header_text or '附录' in header_text:
        return 'appendix'

    # Section intro / chapter instructions
    if ('说    明' in header_text or '说  明' in header_text or '说 明' in header_text) and len(lines) < 25:
        return 'section_intro'
    # Long text paragraphs, no norms code
    has_norms_codes = len([l for l in lines if re.match(r'^\d{5}$', l['text'])]) >= 3
    if not has_norms_codes and len(lines) >= 10:
        # Check if it's paragraph text or section intro
        long_lines = [l for l in lines if len(l['text']) > 30]
        if len(long_lines) >= 5:
            return 'section_intro'

    # Section title pages: "第X节" in header
    if re.search(r'第[一二三四五六七八九十]+节', header_text):
        if not has_norms_codes:
            return 'section_intro'

    # Norms table pages
    if has_norms_codes:
        if '续  表' in header_text or '续表' in header_text or '续 表' in header_text:
            return 'continued_table'
        return 'norms_table'

    # Fallback: check footer for page number pattern
    footer_lines = [l for l in lines if l['y'] > page_height - 60]
    if any(re.match(r'^-\s*\d+\s*-$', l['text']) for l in footer_lines):
        # Has footer but no norms codes → might be table without codes detected
        if len(lines) > 20:
            return 'section_intro'

    return 'blank'


# ========== TOC PARSING ==========

def parse_toc(pages_12_25):
    """Parse TOC from pages 12-25 to build chapter/section hierarchy."""
    all_lines = []
    for pg in range(12, 26):
        data = load_page(pg)
        for l in data['lines']:
            # Skip page number lines and pure numbers
            t = l['text'].strip()
            if re.match(r'^-\s*\d+\s*-$', t):
                continue
            if t == '目 次':
                continue
            all_lines.append({'x': l['x'], 'y': l['y'], 'text': t, 'page': pg})

    # Group by y-bucket to get coherent lines
    y_groups = defaultdict(list)
    for l in all_lines:
        y_groups[round(l['y'] / 8) * 8].append(l)

    entries = []
    for yk in sorted(y_groups.keys()):
        group = y_groups[yk]
        group.sort(key=lambda l: l['x'])
        full_text = ' '.join(l['text'] for l in group)
        x_first = group[0]['x']

        # Extract page number from text like "... - 5 -" or "... - 18 -"
        m = re.search(r'-\s*(\d+)\s*-\s*$', full_text)
        internal_page = int(m.group(1)) if m else None

        # Clean the title: remove leading dots and page number
        title = re.sub(r'\.{2,}.*$', '', full_text).strip()
        title = re.sub(r'\s*-\s*\d+\s*-\s*$', '', title).strip()

        if not title or title in ('目 次',):
            continue

        # Determine level from x position
        if x_first < 40:
            level = 0  # 总说明, 第X章
        elif x_first < 65:
            level = 1  # 说明, 第X节
        else:
            level = 2  # 一、二、... 具体定额项目

        entries.append({
            'x': x_first,
            'level': level,
            'title': title,
            'internal_page': internal_page,
        })

    return entries


def build_chapter_tree(toc_entries):
    """Build hierarchical chapter tree from flat TOC entries."""
    chapters = []
    current_chapter = None
    current_section = None

    for entry in toc_entries:
        title = entry['title']
        level = entry['level']

        if level == 0:
            if re.match(r'第[一二三四五六七八九十]+章', title):
                current_chapter = {
                    'title': title,
                    'internal_page': entry['internal_page'],
                    'sections': [],
                }
                chapters.append(current_chapter)
                current_section = None
            elif '总说明' in title:
                current_chapter = {
                    'title': title,
                    'internal_page': entry['internal_page'],
                    'sections': [],
                }
                chapters.append(current_chapter)
                current_section = None
            elif '附加说明' in title:
                current_chapter = {
                    'title': title,
                    'internal_page': entry['internal_page'],
                    'sections': [],
                }
                chapters.append(current_chapter)
                current_section = None

        elif level == 1:
            current_section = {
                'title': title,
                'internal_page': entry['internal_page'],
                'subsections': [],
            }
            if current_chapter:
                current_chapter['sections'].append(current_section)

        elif level == 2:
            sub = {
                'title': title,
                'internal_page': entry['internal_page'],
            }
            if current_section:
                current_section['subsections'].append(sub)
            elif current_chapter:
                current_chapter['sections'].append({
                    'title': title,
                    'internal_page': entry['internal_page'],
                    'subsections': [],
                })

    return chapters


# ========== INTERNAL PAGE MAPPING ==========

def build_page_mapping():
    """Build pdf_page -> internal_page mapping from all 50 pages."""
    mapping = {}
    for pg in range(1, 51):
        data = load_page(pg)
        ip = data.get('internal_page')
        if ip is not None:
            mapping[ip] = pg
            mapping[pg] = ip
    return mapping


# ========== NORMS TABLE EXTRACTION (from extract_1d.py) ==========

def code_column_for_x(x, code_cols):
    best_ci = None
    best_dist = 999
    for ci, (cx, cx2, _) in enumerate(code_cols):
        col_center = (cx + cx2) / 2
        dist = abs(x - col_center)
        if dist < best_dist:
            best_dist = dist
            best_ci = ci
    return best_ci if best_dist < 80 else None


def is_attr_name(text):
    return bool(ATTR_NAME_RE.search(text))


def is_implicit_attr_value(text):
    return bool(IMPLICIT_ATTR_VAL_RE.match(text))


def try_split_fusion_attr(text):
    m = FUSION_ATTR_RE.match(text)
    if m and is_attr_name(text):
        name_part = m.group(1)
        val_part = m.group(2) + m.group(3)
        if is_attr_name(name_part):
            return name_part, val_part
    return None, None


def find_code_columns(lines):
    code_items = []
    for l in lines:
        t = l['text']
        if re.match(r'^\d{5}$', t) and l['y'] < 250:
            code_items.append((l['x'], l['x2'], t))
    code_items.sort()
    deduped = []
    for x, x2, code in code_items:
        if not deduped or x - deduped[-1][0] > 15:
            deduped.append((x, x2, code))
    return deduped


def find_table_zones(lines, code_cols):
    code_row_y = None
    for l in lines:
        if l['text'] == '定额编号':
            code_row_y = l['y']
            break
    if not code_row_y:
        return None, None, None, None

    min_code_x = min(c[0] for c in code_cols)
    left_boundary = min_code_x - 20

    data_start_y = None
    for l in sorted(lines, key=lambda l: l['y']):
        if l['y'] <= code_row_y + 20:
            continue
        if l['x'] < left_boundary:
            t = l['text']
            if re.match(r'^\d{1,2}(\s|$)', t) or t in COST_KEYWORDS:
                if not NOTE_RE.match(t):
                    data_start_y = l['y']
                    break

    return code_row_y, left_boundary, min_code_x, data_start_y


def parse_header_row_based(lines, code_cols, code_row_y, left_boundary, data_start_y):
    codes = [c[2] for c in code_cols]
    n_codes = len(codes)

    header_frags = [l for l in lines
                    if code_row_y < l['y'] < data_start_y
                    and l['x'] >= left_boundary
                    and l['text']
                    and l['text'] not in LEFT_LABEL_WORDS]
    header_frags = [l for l in header_frags if not re.match(r'^\d{5}$', l['text'])]

    y_groups = defaultdict(list)
    for l in header_frags:
        y_groups[round(l['y'] / 8) * 8].append(l)

    sorted_y = sorted(y_groups.keys())

    level_types = {}
    for yk in sorted_y:
        group = y_groups[yk]
        has_attr = any(is_attr_name(l['text']) for l in group)
        has_implicit = any(is_implicit_attr_value(l['text']) for l in group)
        has_values = any(
            (re.match(r'^[\d.]+$', l['text']) or len(l['text']) <= 8)
            and not is_attr_name(l['text'])
            and not is_implicit_attr_value(l['text'])
            for l in group
        )
        if has_implicit:
            level_types[yk] = 'implicit_values'
        elif has_attr:
            level_types[yk] = 'attr_names'
        elif has_values:
            level_types[yk] = 'values'
        else:
            level_types[yk] = 'other'

    per_code_attrs = [{} for _ in range(n_codes)]

    # Pass 0: Fusion attr labels
    fusion_attrs = {}
    for yk in sorted_y:
        if level_types.get(yk) == 'attr_names':
            for frag in y_groups[yk]:
                name, val = try_split_fusion_attr(frag['text'])
                if name and val:
                    fusion_attrs[name] = val
    if fusion_attrs:
        for ci in range(n_codes):
            for aname, aval in fusion_attrs.items():
                per_code_attrs[ci][aname] = aval

    # Pass 1: Explicit attribute names
    attr_levels = [yk for yk in sorted_y if level_types.get(yk) == 'attr_names']
    for yk_attr in attr_levels:
        value_levels_below = [yk for yk in sorted_y
                              if yk > yk_attr and yk - yk_attr < 50
                              and level_types.get(yk) == 'values']
        if not value_levels_below:
            continue
        closest_val_yk = min(value_levels_below, key=lambda yk: yk - yk_attr)
        attr_frags = y_groups[yk_attr]
        attr_names_list = [l for l in attr_frags if is_attr_name(l['text'])]
        if not attr_names_list:
            continue
        val_frags = y_groups[closest_val_yk]
        for vf in val_frags:
            vtext = vf['text']
            if vtext in ('', '.', '-'):
                continue
            if is_attr_name(vtext) or is_implicit_attr_value(vtext):
                continue
            if len(vtext) > 30:
                continue
            v_center = (vf['x'] + vf['x2']) / 2
            ci = code_column_for_x(v_center, code_cols)
            if ci is None:
                continue
            best_attr = None
            best_x_dist = 999
            for af in attr_names_list:
                a_center = (af['x'] + af['x2']) / 2
                dist = abs(v_center - a_center)
                if dist < best_x_dist:
                    best_x_dist = dist
                    best_attr = af['text']
            if best_attr and best_attr not in per_code_attrs[ci]:
                per_code_attrs[ci][best_attr] = vtext

    # Pass 2: Implicit attributes
    implicit_levels = [yk for yk in sorted_y if level_types.get(yk) == 'implicit_values']
    for yk_impl in implicit_levels:
        frags = y_groups[yk_impl]
        implicit_vals = [l for l in frags if is_implicit_attr_value(l['text'])]
        if not implicit_vals:
            continue
        sample_val = implicit_vals[0]['text']
        if '类土' in sample_val or '类' in sample_val:
            inferred_attr = '土壤类别'
        elif '级' in sample_val:
            inferred_attr = '级别'
        else:
            inferred_attr = '分类'
        for vf in implicit_vals:
            ci = code_column_for_x((vf['x'] + vf['x2']) / 2, code_cols)
            if ci is not None and inferred_attr not in per_code_attrs[ci]:
                per_code_attrs[ci][inferred_attr] = vf['text']

    # Pass 3: Fallback per-column
    col_fragments = [[] for _ in range(n_codes)]
    for l in header_frags:
        ci = code_column_for_x((l['x'] + l['x2']) / 2, code_cols)
        if ci is not None:
            col_fragments[ci].append((l['y'], l['text']))
    for ci in range(n_codes):
        frags = sorted(col_fragments[ci], key=lambda f: f[0])
        i = 0
        while i < len(frags):
            y, text = frags[i]
            if is_attr_name(text):
                j = i + 1
                while j < len(frags) and frags[j][0] - y < 40:
                    vt = frags[j][1]
                    if (not is_attr_name(vt) and not is_implicit_attr_value(vt) and len(vt) < 30):
                        if text not in per_code_attrs[ci]:
                            per_code_attrs[ci][text] = vt
                        break
                    j += 1
                i = j
            else:
                i += 1

    return per_code_attrs, codes


def parse_data_rows(lines, code_cols, left_boundary, data_start_y):
    if not data_start_y:
        return []
    data_lines = [l for l in lines
                  if l['y'] >= data_start_y - 3
                  and l['text']
                  and l['text'] not in ('-', '.')
                  and not NOTE_RE.match(l['text'])]
    data_lines = [l for l in data_lines if not any(p.match(l['text']) for p in NOISE_PATTERNS)]

    y_buckets = defaultdict(list)
    for l in data_lines:
        y_buckets[round(l['y'] / 5) * 5].append(l)

    rows = []
    for y in sorted(y_buckets.keys()):
        items = y_buckets[y]
        items.sort(key=lambda l: l['x'])
        left_parts = []
        value_dict = {}
        for item in items:
            if item['x'] < left_boundary:
                left_parts.append(item)
            else:
                ci = code_column_for_x((item['x'] + item['x2']) / 2, code_cols)
                if ci is not None:
                    val_text = item['text']
                    if ' ' in val_text:
                        parts = val_text.split()
                        if all(re.match(r'^[\d.]+$', p) for p in parts):
                            n_cols = len(parts)
                            start_ci = code_column_for_x(item['x'], code_cols)
                            if start_ci is None:
                                start_ci = ci
                            if start_ci is not None and start_ci + n_cols <= len(code_cols) and n_cols > 1:
                                for j, part in enumerate(parts):
                                    value_dict[start_ci + j] = part
                                continue
                    value_dict[ci] = val_text
        if left_parts or value_dict:
            rows.append({'y': y, 'left_parts': left_parts, 'values': value_dict})
    return rows


def merge_orphan_rows(rows):
    units = {'台班','工日','元','m3','m2','m','t','kg','10m3','100m3','100m2','艘班','组','根','榀','%'}
    merged = []
    for row in rows:
        left_text = ' '.join(p['text'] for p in row['left_parts']).strip()
        if not left_text and not row['values']:
            continue
        if left_text in units and merged:
            prev = merged[-1]
            prev['left_parts'].extend(row['left_parts'])
            for k, v in row['values'].items():
                if k not in prev['values'] or not prev['values'][k]:
                    prev['values'][k] = v
            continue
        if left_text.startswith('注'):
            continue
        merged.append(row)
    return merged


def parse_row_fields(row):
    lefts = sorted(row['left_parts'], key=lambda p: p['x'])
    texts = [p['text'] for p in lefts]
    parts = ' '.join(texts).split()
    seq = ''
    name_parts = []
    unit = ''
    code = ''
    for p in parts:
        if not seq and re.match(r'^\d{1,2}$', p):
            seq = p
        elif not code and re.match(r'^\d{10,13}$', p):
            code = p
        elif p in UNIT_WORDS:
            unit = p
        elif not p.isdigit() and not re.match(r'^[\d.()\-]+$', p) and p not in ('-', '.'):
            name_parts.append(p)
    name = ' '.join(name_parts) if name_parts else ''
    return seq, name, unit, code


def extract_table_from_page(data):
    """Extract 1D records from a norms table page. Returns (records, all_attr_names, meta)."""
    lines = data['lines']
    code_cols = find_code_columns(lines)
    if not code_cols:
        return [], [], {}

    code_row_y, left_boundary, min_code_x, data_start_y = find_table_zones(lines, code_cols)
    if not data_start_y:
        return [], [], {}

    per_code_attrs, codes = parse_header_row_based(
        lines, code_cols, code_row_y, left_boundary, data_start_y)

    data_rows = parse_data_rows(lines, code_cols, left_boundary, data_start_y)
    data_rows = merge_orphan_rows(data_rows)

    # Build all_attr_names
    all_attr_names = []
    seen = set()
    for attrs in per_code_attrs:
        for k in attrs:
            if k not in seen:
                all_attr_names.append(k)
                seen.add(k)

    records = []
    for row in data_rows:
        seq, name, unit, code = parse_row_fields(row)
        if not name:
            continue
        for ci in range(len(codes)):
            val = row['values'].get(ci, '')
            if val == '':
                continue
            attrs = per_code_attrs[ci] if ci < len(per_code_attrs) else {}
            record = {
                '定额编号': codes[ci],
                '费用项目': name,
                '单位': unit,
                '代码': code,
                '数量': val,
            }
            for aname in all_attr_names:
                record[aname] = attrs.get(aname, '')
            records.append(record)

    # Extract metadata from header area
    meta = {}
    header_text_lines = [l for l in lines if l['y'] < data_start_y and l['x'] < 350]
    for l in header_text_lines:
        t = l['text']
        if '工程内容' in t:
            content = re.sub(r'^工程内容[：:]?\s*', '', t)
            meta['work_content'] = content
        # Unit detection: text like "100m³" in header
        if re.match(r'^\d+', t) and any(u in t for u in ['m³', 'm3', 'm²', 'm2', 'm', 't', '根', '件']):
            if 'unit' not in meta:
                meta['unit'] = t

    return records, all_attr_names, meta


# ========== HEADER/SECTION TITLE EXTRACTION ==========

def extract_section_info(data):
    """Extract section title and work content from header area of a norms table page."""
    lines = data['lines']
    header_lines = [l for l in lines if l['y'] < 130]

    info = {}
    for l in header_lines:
        t = l['text']
        # Chinese numeral section markers: 一、二、三、...
        if re.match(r'^[一二三四五六七八九十]+、', t):
            info['subsection'] = t
        elif re.match(r'^[一二三四五六七八九十]+、', t):
            info['subsection'] = t
        elif '工程内容' in t:
            info['work_content'] = re.sub(r'^工程内容[：:]?\s*', '', t)
        elif re.match(r'^\d+', t) and any(u in t for u in ['m³','m3','m²','m2','m','t','根','件','100']):
            if 'unit' not in info:
                info['unit'] = t

    # Also check the very first line for subsection title
    first_text_lines = [l for l in lines if l['y'] < 40 and len(l['text']) > 2]
    for l in first_text_lines:
        t = l['text']
        if re.match(r'^[一二三四五六七八九十]+、', t) and 'subsection' not in info:
            info['subsection'] = t
        elif re.match(r'^第[一二三四五六七八九十]+节', t) and 'section' not in info:
            info['section'] = t

    return info


# ========== TEXT PAGE TO MD ==========

def text_page_to_md(data, page_type, chapter_context):
    """Convert a non-table page to markdown."""
    lines = data['lines']
    page = data['page']
    internal = data.get('internal_page', '')

    # Build frontmatter
    fm = {
        'page': page,
        'pdf_page': page,
        'internal_page': internal,
        'type': page_type,
        'chapter': chapter_context.get('chapter', ''),
        'section': chapter_context.get('section', ''),
        'title': '',
    }

    # Get title from header
    header = [l for l in lines if l['y'] < 60]
    if header:
        fm['title'] = header[0]['text']

    # Build body text
    body_lines = [l for l in lines if l['y'] >= 60 and l['y'] < data['page_height'] - 60]

    # Group by y into paragraphs
    y_groups = defaultdict(list)
    for l in body_lines:
        y_groups[round(l['y'] / 10) * 10].append(l)

    paragraphs = []
    for yk in sorted(y_groups.keys()):
        group = y_groups[yk]
        group.sort(key=lambda l: l['x'])
        text = ' '.join(l['text'] for l in group).strip()
        if text and not re.match(r'^-\s*\d+\s*-$', text):
            # Detect indentation level for heading
            indent = group[0]['x']
            if indent < 50:
                paragraphs.append(text)
            elif indent < 90:
                paragraphs.append('  ' + text)
            else:
                paragraphs.append('    ' + text)

    # Build markdown
    md = '---\n'
    for k, v in fm.items():
        md += f'{k}: {v}\n'
    md += '---\n\n'
    md += f'# 第{page}页 ({page_type})\n\n'
    for p in paragraphs:
        md += p + '\n\n'

    return md, fm


# ========== NORMS TABLE TO MD ==========

def norms_table_to_md(data, records, all_attr_names, meta, page_type, chapter_context):
    """Convert extracted 1D records to markdown."""
    page = data['page']
    internal = data.get('internal_page', '')

    fm = {
        'page': page,
        'pdf_page': page,
        'internal_page': internal,
        'type': page_type,
        'source': 'pymupdf_text',
        'chapter': chapter_context.get('chapter', ''),
        'section': chapter_context.get('section', ''),
        'subsection': chapter_context.get('subsection', ''),
        'work_content': meta.get('work_content', ''),
        'unit': meta.get('unit', ''),
        'record_count': len(records),
    }

    columns = ['定额编号'] + all_attr_names + ['费用项目', '单位', '代码', '数量']

    md = '---\n'
    for k, v in fm.items():
        md += f'{k}: {v}\n'
    md += '---\n\n'

    # Title
    subsection = chapter_context.get('subsection', '')
    title = f'# 第{page}页'
    if subsection:
        title += f' — {subsection}'
    title += f' (一维表, {len(records)}条记录)\n'
    md += title + '\n'

    if meta.get('work_content'):
        md += f'- **工程内容**: {meta["work_content"]}\n'
    if meta.get('unit'):
        md += f'- **单位**: {meta["unit"]}\n'
    md += '\n'

    md += '| ' + ' | '.join(columns) + ' |\n'
    md += '|' + '|'.join([':---'] * len(columns)) + '|\n'

    for rec in records:
        vals = [str(rec.get(c, '')) for c in columns]
        md += '| ' + ' | '.join(vals) + ' |\n'

    return md, fm


# ========== CHAPTER CONTEXT RESOLVER ==========

def resolve_chapter_context(pg, page_type, page_map, chapters, data):
    """Determine chapter/section context for a page based on its internal page number."""
    internal = data.get('internal_page')
    lines = data['lines']

    context = {'chapter': '', 'section': '', 'subsection': ''}

    # For non-norms pages, determine from content
    if page_type in ('general_instruction',):
        context['chapter'] = '总说明'
        return context

    if page_type in ('chapter_title',):
        for l in lines:
            m = re.match(r'(第[一二三四五六七八九十]+章\s*.+)', l['text'])
            if m:
                context['chapter'] = m.group(1)
                return context
        return context

    if page_type == 'toc':
        context['chapter'] = '目录'
        return context

    if page_type == 'notice':
        context['chapter'] = '公告'
        return context

    if page_type == 'appendix':
        context['chapter'] = '附加说明'
        return context

    if page_type in ('cover', 'blank'):
        return context

    # For norms_table, continued_table, section_intro: resolve by internal page
    if internal is not None and chapters:
        chapter_title = ''
        section_title = ''
        subsection_title = ''

        for ch in chapters:
            ch_page = ch.get('internal_page', 0)
            if ch_page and ch_page <= internal:
                chapter_title = ch['title']
                for sec in ch.get('sections', []):
                    sec_page = sec.get('internal_page', 0)
                    if sec_page and sec_page <= internal:
                        section_title = sec['title']
                        for sub in sec.get('subsections', []):
                            sub_page = sub.get('internal_page', 0)
                            if sub_page and sub_page <= internal:
                                subsection_title = sub['title']

        context['chapter'] = chapter_title
        context['section'] = section_title
        context['subsection'] = subsection_title

    # For section_intro pages, try to extract from header
    if page_type == 'section_intro':
        header = [l for l in lines if l['y'] < 60]
        for l in header:
            t = l['text']
            if re.match(r'第[一二三四五六七八九十]+节', t):
                context['section'] = t

    # For norms tables, extract subsection from header
    if page_type in ('norms_table', 'continued_table'):
        info = extract_section_info(data)
        if info.get('section'):
            context['section'] = info['section']
        if info.get('subsection'):
            context['subsection'] = info['subsection']

    return context


# ========== MAIN ==========

def main():
    print("=== Phase 1: Classify pages 1-50 ===")
    page_types = {}
    for pg in range(1, 51):
        data = load_page(pg)
        pt = classify_page(data)
        page_types[pg] = pt

    print("Page type summary:")
    type_counts = defaultdict(list)
    for pg, pt in sorted(page_types.items()):
        type_counts[pt].append(pg)
    for pt, pages in sorted(type_counts.items()):
        print(f"  {pt}: {len(pages)} pages - {pages[:5]}{'...' if len(pages) > 5 else ''}")

    print("\n=== Phase 2: Parse TOC ===")
    toc_entries = parse_toc(range(12, 26))
    chapters = build_chapter_tree(toc_entries)
    page_map = build_page_mapping()

    print(f"TOC entries: {len(toc_entries)}")
    for ch in chapters:
        print(f"  {ch['title']} (internal={ch['internal_page']})")
        for sec in ch.get('sections', [])[:3]:
            print(f"    {sec['title']} (internal={sec['internal_page']})")
            for sub in sec.get('subsections', [])[:2]:
                print(f"      {sub['title']} (internal={sub['internal_page']})")
        if len(ch.get('sections', [])) > 3:
            print(f"    ... ({len(ch['sections'])} sections total)")

    print("\n=== Phase 3: Generate MD files ===")
    all_fms = {}

    for pg in range(1, 51):
        data = load_page(pg)
        pt = page_types[pg]

        # Resolve chapter context
        ctx = resolve_chapter_context(pg, pt, page_map, chapters, data)

        if pt in ('norms_table', 'continued_table'):
            records, all_attr_names, meta = extract_table_from_page(data)
            if records:
                if pt == 'norms_table' and not meta.get('work_content'):
                    info = extract_section_info(data)
                    meta.update(info)
                md, fm = norms_table_to_md(data, records, all_attr_names, meta, pt, ctx)
                print(f"  Page {pg:3d} {pt:20s} {len(records):4d} records  ch={ctx.get('chapter','')[:20]}  sec={ctx.get('subsection','')[:20]}")
            else:
                print(f"  Page {pg:3d} {pt:20s} NO DATA - falling back to text")
                md, fm = text_page_to_md(data, 'section_intro', ctx)
        else:
            md, fm = text_page_to_md(data, pt, ctx)
            preview = ' '.join(l['text'] for l in data['lines'][:3])[:60] if data['lines'] else '(empty)'
            print(f"  Page {pg:3d} {pt:20s}  {preview}...")

        out_path = MD_DIR / f'page_{pg:04d}.md'
        out_path.write_text(md, encoding='utf-8')
        all_fms[pg] = fm

    # Write structure summary
    structure = {
        'document': {
            'title': '沿海港口水工建筑工程定额',
            'doc_number': 'JTS/T 276-1-2019',
            'total_pages': 50,
        },
        'page_types': {str(k): v for k, v in page_types.items()},
        'chapters': chapters,
        'page_frontmatter': all_fms,
    }
    struct_path = ROOT / 'output' / 'structure.json'
    struct_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n=== Done! ===")
    print(f"MD files: {MD_DIR}")
    print(f"Structure: {struct_path}")
    print(f"Page types: {dict(type_counts)}")


if __name__ == '__main__':
    main()
