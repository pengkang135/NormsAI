"""Parse Markdown norms files and load into SQLite.

Usage:
    python scripts/load_md_to_sqlite.py [--pages 29,33,35] [--db final.sqlite]
"""

import sys
import json
import re
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import MD_DIR, DB_PATH, DB_SCHEMA

_ARABIC_TO_CN = {'1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六',
                 '7': '七', '8': '八', '9': '九', '10': '十'}


def normalize_chapter(chapter_name):
    """Convert Arabic-numeral chapters to Chinese: 第2章 → 第二章"""
    return re.sub(r'第(\d+)章', lambda m: '第' + _ARABIC_TO_CN.get(m.group(1), m.group(1)) + '章', chapter_name)


def parse_frontmatter(text):
    """Extract YAML frontmatter from markdown text."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).strip().split('\n'):
        kv = line.split(':', 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            try:
                val = int(val)
            except ValueError:
                pass
            fm[key] = val
    return fm


def clean_cost_item(name):
    """Remove OCR noise from cost item names and fix common errors."""
    if not name:
        return name
    # Skip rows that are clearly not real cost items
    if name in ('-', '定额。', '续前页', '工日', 'kg', 'm3', '台班', '艘班'):
        return ''
    if name in ('-', '—', '—'):
        return ''
    if name.startswith('附注') or name.startswith('顺序号') or name.startswith('每组'):
        return ''
    if name.startswith('项目') or name.startswith('（') or name.startswith('('):
        return ''
    if name.startswith('$'):
        return ''
    # Strip trailing "kg." / "kg" patterns after digit stripping
    name = re.sub(r'\s*kg\.?\s*', '', name, flags=re.IGNORECASE)
    # Apply known fixes first (before stripping digits)
    fixes = {
        '定型板面': '定型组合钢模',
        '钢模厂连接卡具': '连接卡具',
        '钢模连接卡具': '连接卡具',
        '组合骨架、支撑': '骨架、支撑',
        '基基价': '基价',
        '2基': '基价',
        '组合板面': '定型组合钢模',
        '板面 定型': '定型组合钢模',
        '定型 板面': '定型组合钢模',
        '混凝主': '混凝土',
        '钢加钢': '钢筋',
        '板面': '定型组合钢模',
    }
    for wrong, right in fixes.items():
        if wrong in name:
            name = name.replace(wrong, right)
    # Strip leading digits and common OCR prefixes
    name = re.sub(r'^\d+\s*', '', name)
    # Strip leading unit prefixes that OCR mistakenly attached
    name = re.sub(r'^(台班|艘班|工日)\s+', '', name)
    # Clean trailing "kg.", "kg" with trailing units
    name = re.sub(r'\s+kg\.?\s*$', '', name, flags=re.IGNORECASE)
    # Post-strip fixes
    if name == '钢':
        name = '钢筋'
    if name == '板材':
        name = '板枋材'
    # After digit stripping, check for dangling dash or single chars
    if name in ('-', '—', '—', '.', '/'):
        return ''
    # Skip OCR-merged garbage rows: 3+ consecutive digits AND mostly non-text
    if re.search(r'\d{3,}', name):
        text_chars = len(re.sub(r'[\d\s\.\/—\-\(\)\,\;\:\+]+', '', name))
        if text_chars < 3:
            return ''
    return name.strip()


def clean_amount(val):
    """Clean and normalize amount values. Returns (normalized_value, data_quality_flag)."""
    if val is None:
        return None, 'raw'
    if isinstance(val, (int, float)):
        return float(val), 'raw'
    if not isinstance(val, str):
        return None, 'raw'
    v = val.strip()
    if not v:
        return None, 'raw'
    # Intentional blanks from original doc
    if v in ('---', '—', '—', '-', '—'):
        return None, 'raw'
    # Parenthesized numbers: "(10.20)" → 10.20
    m = re.match(r'^\((\d+\.?\d*)\)$', v)
    if m:
        return float(m.group(1)), 'raw'
    # Range values: "920-1560" → keep as string for special handling
    if re.match(r'^\d+\-\d+$', v):
        return v, 'range'
    # Comma-separated pairs (European format or OCR artifact): "0,15"
    if re.match(r'^\d+,\d+$', v):
        return float(v.replace(',', '.')), 'raw'
    # Try direct float conversion
    try:
        return float(v), 'raw'
    except ValueError:
        pass
    # Strip common OCR artifacts and retry
    cleaned = re.sub(r'[^\d\.\-,]', '', v)
    if cleaned and cleaned != v:
        try:
            return float(cleaned), 'raw'
        except ValueError:
            pass
    # Unparseable — log and return None
    return None, 'unparseable'


def infer_unit(cost_item):
    """Infer the unit for a cost item based on its name."""
    if not cost_item:
        return ''
    item = cost_item.strip()
    if item == '人工':
        return '工日'
    if '混凝土' in item and '搅拌' not in item:
        return 'm3'
    # Wood materials
    if item in ('板枋材', '圆木', '硬杂木') or '板枋材' in item or '圆木' in item or '硬杂木' in item:
        return 'm3'
    # Mortar/concrete-like
    if any(k in item for k in ('水泥砂浆', '环氧砂浆', '环氧水泥砂浆', '沥青砂浆', '沥青混凝土')):
        return 'm3'
    # Stone/aggregate
    if any(k in item for k in ('碎石', '石屑', '石英砂', '砂', '石子')):
        return 'm3' if '砂' not in item else 'kg'
    if '石英砂' in item:
        return 'kg'
    # Steel/metal products (weight-based)
    steel_items = ('定型组合钢模', '定型板面', '钢板', '型钢', '钢管', '钢筋',
                   '铁件', '螺栓', '电焊条', '碳精棒', '系船柱壳体',
                   '预埋件', '钢轨', '钢丝绳', '铁钉', '铁线')
    if any(k in item for k in steel_items):
        return 'kg'
    if '骨架' in item or '支撑' in item:
        return 'kg'
    if '连接卡具' in item:
        return 'kg'
    if '模板' in item or '胎模' in item:
        return 'kg'
    # Rubber/plastic
    if any(k in item for k in ('橡胶', '胶囊', '稀释剂')):
        return 'kg'
    if item == '橡胶护舷':
        return '套'
    # Paints/coatings
    if any(k in item for k in ('沥青', '红丹', '汽油', '煤油', '油漆', '涂料')):
        return 'kg'
    # Other materials
    if '其他材料' in item:
        return '元'
    if '预制构件' in item:
        return 'm3'
    if '固定预制场使用费' in item:
        return '元'
    # Machinery
    if '搅拌站' in item:
        return '台班'
    if '搅拌船' in item:
        return '艘班'
    if any(k in item for k in ('起重机', '装载机', '皮带机', '自卸汽车', '机动翻斗车', '卷扬机', '电焊机', '空压机', '振捣器', '切断机', '弯曲机', '对焊机', '抽水机', '水泵', '电钻')):
        return '台班'
    if '汽车' in item or '平板车' in item or '拖车' in item:
        return '台班'
    if '拖轮' in item:
        return '艘班'
    if '方驳' in item or '铁驳' in item or '驳船' in item or '工作船' in item or '定位船' in item or '抛锚船' in item or '潜水船' in item:
        return '艘班'
    if '机动艇' in item:
        return '艘班'
    if '其他船机' in item:
        return '元'
    if '船用锤' in item or '打桩船' in item:
        return '艘班'
    if '扒杆起重船' in item or '旋转扒杆' in item:
        return '艘班'
    if '潜水组' in item:
        return '组日'
    # Electric cart
    if '电动运砼车' in item or '带斗车' in item:
        return '台班'
    if '基价' in item:
        return '元'
    if '钢筋' in item:
        return 'kg'
    # Gases
    if item in ('氧气', '乙炔气') or '乙炔气' in item or '氧气' in item:
        return 'm3'
    # Misc materials
    if item in ('脱模剂', '调合漆', '铁链', '麻丝', '焊剂') or '调合漆' in item:
        return 'kg'
    if item in ('麻布', '塑料止水带'):
        return 'm2'
    if item in ('卡环M42', '卡环M52', '钻头', '扣件', '底座', '系船柱'):
        return '个'
    if '系船柱' in item:
        return '个'
    if item in ('块石', '片石', '粘土', '特大枋', '毛竹', '垫木', '碎石'):
        return 'm3'
    if item in ('编织袋',):
        return '个'
    if item == '成品钢护':
        return 't'
    if item == '设施摊销费':
        return '元'
    if '施工取费' in item or '设备摊销' in item or '使用费' in item or '摊销费' in item:
        return '元'
    # Fallback for common patterns
    if item.endswith('气'):
        return 'm3'
    if item.endswith('石') or item.endswith('土'):
        return 'm3'
    if item.endswith('木') or item.endswith('材') or item.endswith('枋'):
        return 'm3'
    if item.endswith('链'):
        return 'kg'
    return ''


def _align_cells(cells, headers):
    """Align data cells to match header column count.

    Most broken tables have: header with extra attribute columns, data with
    only 定额编号/分部工程/分项工程/{1 attr}/费用项目/单位/数量 (7 cols).
    We pad empty strings for missing attribute columns in the data.
    """
    if len(cells) == len(headers):
        return cells

    if len(cells) > len(headers):
        # Data has extra columns - try truncating from the right
        return cells[:len(headers)]

    # Data has fewer columns - pad attributes in the middle
    # Standard structure: first 3 cols (定额编号, 分部工程, 分项工程)
    #                    last 3 cols (费用项目, 单位, 数量)
    #                    middle = attribute columns
    if len(cells) >= 6 and len(headers) >= 6:
        num_header_attrs = len(headers) - 6
        num_data_attrs = max(0, len(cells) - 6)
        if num_header_attrs > num_data_attrs:
            # Pad empty strings for missing attribute columns
            padded = (
                cells[:3] +
                cells[3:3 + num_data_attrs] +
                [''] * (num_header_attrs - num_data_attrs) +
                cells[3 + num_data_attrs:]
            )
            if len(padded) == len(headers):
                return padded

    # Fallback: try to identify where cost_item sits and pad attributes in the middle
    # Cost item keywords for position detection
    _COST_ITEM_TOKENS = {
        '人工', '材料', '机械', '船机', '基价', '合计', '型钢', '钢板',
        '钢筋', '混凝土', '板枋材', '铁件', '电焊条', '氧气', '乙炔气',
        '红丹', '调合漆', '稀释剂', '螺栓带帽', '机加工件', '其他材料',
        '其他船机', '设施摊销费', '定型组合钢模', '骨架', '支撑',
        '连接卡具', '块石', '圆木', '硬杂木',
    }
    # Find the likely cost_item column index in cells
    cost_idx = None
    for idx, cell in enumerate(cells):
        if idx == 0:
            continue  # skip norms_code
        if cell in _COST_ITEM_TOKENS or any(tok in cell for tok in ('水泥', '砂浆', '搅拌', '起重', '汽车', '钻床', '焊机')):
            cost_idx = idx
            break
    if cost_idx is None:
        # Can't identify — assume last 3 cells are (cost_item, unit, amount)
        cost_idx = max(1, len(cells) - 3)
    # Pad empty strings between the id section (before cost_idx) and cost_idx
    # The id cols map to first (len(headers) - 3) header positions
    # Cost_item goes to position len(headers) - 3
    id_cells = cells[:cost_idx]
    data_cells = cells[cost_idx:]
    num_id_slots = len(headers) - len(data_cells)
    if num_id_slots > 0:
        padded = id_cells[:num_id_slots] + [''] * max(0, num_id_slots - len(id_cells)) + data_cells
        if len(padded) == len(headers):
            return padded
    return cells + [''] * (len(headers) - len(cells))


def parse_tables(text):
    """Parse markdown tables from text. Returns list of table dicts."""
    tables = []
    lines = text.split('\n')
    seen_ranges = set()  # track line ranges already parsed

    # Find table sections: heading, optional metadata, then |...| table rows
    i = 0
    while i < len(lines):
        line = lines[i]

        # Match ##, ###, or #### heading
        heading_match = re.match(r'^#{2,4}\s+(.+)', line)
        if not heading_match:
            i += 1
            continue

        heading = heading_match.group(1).strip()
        metadata = {}
        data_start = i + 1

        # Collect metadata lines (starting with - **)
        j = i + 1
        while j < len(lines) and lines[j].startswith('- **'):
            mm = re.match(r'- \*\*(.+?)\*\*:\s*(.+)', lines[j])
            if mm:
                metadata[mm.group(1).strip()] = mm.group(2).strip()
            j += 1

        # Find the table header line (starts with |)
        header_idx = None
        while j < len(lines):
            if lines[j].startswith('|') and '---' in lines[j + 1] if j + 1 < len(lines) else False:
                header_idx = j
                break
            if lines[j].startswith('|'):
                header_idx = j
                break
            j += 1

        if header_idx is None:
            i = j
            continue

        # Parse header row
        header_line = lines[header_idx]
        headers = [h.strip() for h in header_line.split('|')[1:-1]]

        # Skip alignment row if present
        data_idx = header_idx + 1
        if data_idx < len(lines) and re.match(r'^\|[\s\-:|\s]+$', lines[data_idx]):
            data_idx += 1

        # Parse data rows
        rows = []
        while data_idx < len(lines):
            row_line = lines[data_idx]
            if not row_line.startswith('|'):
                break
            cells = [c.strip() for c in row_line.split('|')[1:-1]]
            cells = _align_cells(cells, headers)
            if cells:
                row = dict(zip(headers, cells))
                # Convert numeric values
                for k in list(row.keys()):
                    v = row[k]
                    if k in ('数量', 'amount'):
                        cleaned_val, quality = clean_amount(v)
                        row[k] = cleaned_val
                        row['_quality'] = quality
                    if k == '定额编号':
                        row[k] = v.strip()
                if '_quality' not in row:
                    row['_quality'] = 'raw'
                rows.append(row)
            data_idx += 1

        seen_ranges.add((i, data_idx))
        tables.append({
            'heading': heading,
            'metadata': metadata,
            'headers': headers,
            'rows': rows,
        })
        i = data_idx

    # Second pass: find tables without headings (continuation pages)
    for i, line in enumerate(lines):
        if not line.startswith('|'):
            continue
        # Check if this line range is already parsed
        if any(s <= i < e for s, e in seen_ranges):
            continue
        # Check next line is a separator row
        if i + 1 >= len(lines) or not re.match(r'^\|[\s\-:|\s]+$', lines[i + 1]):
            continue

        # This is a potential table header line
        header_line = lines[i]
        headers = [h.strip() for h in header_line.split('|')[1:-1]]
        # Remove empty strings from split
        headers = [h for h in headers if h]
        if not headers or headers[0] != '定额编号':
            continue

        metadata = {}
        # Check lines above for metadata
        j = i - 1
        while j >= 0 and lines[j].startswith('- **'):
            mm = re.match(r'- \*\*(.+?)\*\*:\s*(.+)', lines[j])
            if mm:
                metadata[mm.group(1).strip()] = mm.group(2).strip()
            j -= 1

        # Parse data rows
        data_idx = i + 2  # skip header + separator
        rows = []
        while data_idx < len(lines):
            row_line = lines[data_idx]
            if not row_line.startswith('|'):
                break
            cells = [c.strip() for c in row_line.split('|')[1:-1]]
            cells = _align_cells(cells, headers)
            if cells:
                row = dict(zip(headers, cells))
                for k in list(row.keys()):
                    v = row[k]
                    if k in ('数量', 'amount'):
                        cleaned_val, quality = clean_amount(v)
                        row[k] = cleaned_val
                        row['_quality'] = quality
                    if k == '定额编号':
                        row[k] = v.strip()
                if '_quality' not in row:
                    row['_quality'] = 'raw'
                rows.append(row)
            data_idx += 1

        if rows:
            seen_ranges.add((i, data_idx))
            tables.append({
                'heading': metadata.get('工程内容', metadata.get('单位', '')),
                'metadata': metadata,
                'headers': headers,
                'rows': rows,
            })

    return tables


def infer_attrs(row, headers):
    """Extract attribute columns (non-standard columns) from a row."""
    standard = {'定额编号', '分部工程', '分项工程', '费用项目', '单位', '数量'}
    attrs = {}
    for h in headers:
        if h not in standard and h in row:
            attrs[h] = row[h]
    return attrs


def create_tables(conn):
    conn.executescript(DB_SCHEMA)
    conn.commit()


def load_page(conn, md_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        text = f.read()

    fm = parse_frontmatter(text)
    tables = parse_tables(text)

    page = fm.get('page', 0)
    chapter = normalize_chapter(fm.get('chapter', ''))
    section = fm.get('section', '')

    # Ensure chapter exists
    cur = conn.execute("SELECT id FROM chapter WHERE title = ? AND level = 1", (chapter,))
    ch = cur.fetchone()
    if ch:
        chapter_id = ch[0]
    else:
        cur = conn.execute(
            "INSERT INTO chapter (sort_order, level, title) VALUES (?, 1, ?)",
            (1, chapter)
        )
        chapter_id = cur.lastrowid

    # Ensure page_index entry
    page_type = fm.get('type', 'norms_table')
    conn.execute(
        "INSERT OR REPLACE INTO page_index (page, page_type, chapter_id) VALUES (?, ?, ?)",
        (page, page_type, chapter_id)
    )

    for seq, tbl in enumerate(tables):
        # Determine attribute columns from first row
        standard = {'定额编号', '分部工程', '分项工程', '费用项目', '单位', '数量'}
        attr_cols = [h for h in tbl['headers'] if h not in standard]

        # Insert norms_table
        header_json = json.dumps({
            'heading': tbl['heading'],
            'attr_columns': attr_cols,
            'full_headers': tbl['headers'],
        }, ensure_ascii=False)

        conn.execute("""
            INSERT INTO norms_table
                (chapter_id, section_title, subsection_title, work_content, unit, page, seq_on_page, header_json, row_count, col_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chapter_id,
            section,
            tbl['heading'],
            tbl['metadata'].get('工程内容', ''),
            tbl['metadata'].get('单位', ''),
            page,
            seq + 1,
            header_json,
            len(tbl['rows']),
            len(tbl['headers']),
        ))
        table_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Update page_index with table_id
        conn.execute(
            "UPDATE page_index SET table_id = ? WHERE page = ?",
            (table_id, page)
        )

        # Insert norms_items
        for sort_order, row in enumerate(tbl['rows']):
            attrs = {h: row.get(h, '') for h in attr_cols}

            # Map attr levels: use up to 4 attribute columns
            attr_labels = list(attrs.keys())
            attr_values = [attrs.get(k, '') for k in attr_labels]

            cost_item = clean_cost_item(row.get('费用项目', ''))
            if not cost_item:
                # Skip rows with empty cost item after cleaning
                continue

            cost_unit = row.get('单位', '')
            amount = row.get('数量', None)

            # Clean garbage from amount column (units mistaken as values)
            if isinstance(amount, str) and amount.strip() in ('瘦班', '艘班', '台班', '工日', 'kg', '元', 'm3'):
                if not cost_unit:
                    cost_unit = amount.strip().replace('瘦', '艘')
                amount = None

            if not cost_unit:
                cost_unit = infer_unit(cost_item)

            # Also strip trailing unit patterns and leading prefixes from cost_item
            cost_item = re.sub(r'\s+(kg|元|m3|工日|台班|艘班|套|个|把|根|t|m2|m)$', '', cost_item)
            cost_item = re.sub(r'^[tT]\s*', '', cost_item)  # "t固定扒杆起重船" → "固定扒杆起重船"

            conn.execute("""
                INSERT INTO norms_item
                    (table_id, page, norms_code, sort_order,
                     attr_level1, attr_level2, attr_level3, attr_level4,
                     attr1_label, attr2_label, attr3_label, attr4_label,
                     cost_item, cost_item_unit, amount, data_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                table_id,
                page,
                row.get('定额编号', ''),
                sort_order,
                attr_values[0] if len(attr_values) > 0 else '',
                attr_values[1] if len(attr_values) > 1 else '',
                attr_values[2] if len(attr_values) > 2 else '',
                attr_values[3] if len(attr_values) > 3 else '',
                attr_labels[0] if len(attr_labels) > 0 else '',
                attr_labels[1] if len(attr_labels) > 1 else '',
                attr_labels[2] if len(attr_labels) > 2 else '',
                attr_labels[3] if len(attr_labels) > 3 else '',
                cost_item,
                cost_unit,
                amount,
                row.get('_quality', 'raw'),
            ))

    # Check for norms codes missing 基价
    codes_in_page = set()
    codes_with_jijia = set()
    for tbl in tables:
        for row in tbl['rows']:
            code = row.get('定额编号', '').strip()
            if code and code.isdigit():
                codes_in_page.add(code)
                ci = clean_cost_item(row.get('费用项目', ''))
                if ci == '基价':
                    codes_with_jijia.add(code)
    missing_jijia = codes_in_page - codes_with_jijia
    if missing_jijia:
        print(f"  WARNING page {page}: {len(missing_jijia)} code(s) missing 基价: {sorted(missing_jijia, key=int)}")

    conn.commit()
    return page, len(tables), sum(len(t['rows']) for t in tables)


def main():
    parser = argparse.ArgumentParser(description='Load markdown norms files into SQLite')
    parser.add_argument('--pages', help='Comma-separated page numbers or range (e.g. 29,33,35 or 29-60)')
    parser.add_argument('--db', default=str(DB_PATH), help='SQLite database path')
    parser.add_argument('--md-dir', default=str(MD_DIR), help='Markdown directory')
    parser.add_argument('--reset', action='store_true', help='Drop and recreate tables')
    args = parser.parse_args()

    md_dir = Path(args.md_dir)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine pages to load
    if args.pages:
        pages = set()
        for part in args.pages.split(','):
            part = part.strip()
            if '-' in part:
                a, b = part.split('-', 1)
                pages.update(range(int(a), int(b) + 1))
            else:
                pages.add(int(part))
        md_files = sorted(md_dir.glob('page_*.md'))
        md_files = [f for f in md_files if int(f.stem.split('_')[1]) in pages]
    else:
        md_files = sorted(md_dir.glob('page_*.md'))

    if not md_files:
        print(f"No markdown files found in {md_dir}")
        return

    conn = sqlite3.connect(str(db_path))
    if args.reset:
        conn.executescript("DROP TABLE IF EXISTS norms_item")
        conn.executescript("DROP TABLE IF EXISTS norms_table")
        conn.executescript("DROP TABLE IF EXISTS page_index")
        conn.executescript("DROP TABLE IF EXISTS chapter")
        conn.executescript("DROP TABLE IF EXISTS appendix_row")
        conn.executescript("DROP TABLE IF EXISTS appendix_table")
        conn.executescript("DROP TABLE IF EXISTS section_text")
        conn.executescript("DROP TABLE IF EXISTS document")
        conn.executescript("DROP TABLE IF EXISTS ocr_block")
    create_tables(conn)

    total_pages = 0
    total_rows = 0
    for md_path in md_files:
        try:
            page, n_tables, n_rows = load_page(conn, md_path)
            total_pages += 1
            total_rows += n_rows
            print(f"  page_{page:04d}: {n_tables} table(s), {n_rows} rows")
        except Exception as e:
            print(f"  ERROR page {md_path.stem}: {e}")

    print(f"\nLoaded {total_pages} pages, {total_rows} total rows into {db_path}")
    conn.close()


if __name__ == '__main__':
    main()
