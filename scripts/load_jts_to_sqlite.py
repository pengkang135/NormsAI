"""
Load JTS/T 276-1-2019 MD files into SQLite with full document structure.

Usage:
    python scripts/load_jts_to_sqlite.py [--md-dir output/md_jts] [--db output/db/JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite] [--reset]
"""
import sys, json, re, argparse, sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_SCHEMA

ROOT = Path(__file__).resolve().parent.parent

TABLE_PAGE_TYPES = {'norms_table', 'continued_table'}
TEXT_PAGE_TYPES = {'cover', 'blank', 'notice', 'toc', 'general_instruction', 'chapter_title', 'section_intro', 'appendix'}

_UNIT_WORDS = {'工日','台班','元','m3','m²','m³','m','t','kg','10m3','100m3','100m2','艘班','组','根','榀','%','件','个','块','套','只','条','片','座','处','段','延长米','榀','根','块','m²','100m²'}


def parse_frontmatter(text):
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


def parse_body_text(text):
    """Extract body text content from MD (excluding frontmatter and tables)."""
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)
    lines = []
    for line in body.split('\n'):
        line = line.strip()
        if not line or line.startswith('|') or line.startswith('#') or line.startswith('- **'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def parse_tables(text):
    """Parse markdown tables, returning list of {headers, rows} dicts."""
    lines = text.split('\n')
    tables = []
    seen = set()

    i = 0
    while i < len(lines):
        if not lines[i].startswith('|'):
            i += 1
            continue
        if any(s <= i < e for s, e in seen):
            i += 1
            continue

        header_line = lines[i]
        headers = [h.strip() for h in header_line.split('|')[1:-1]]
        if not headers:
            i += 1
            continue

        data_idx = i + 1
        if data_idx < len(lines) and re.match(r'^\|[\s\-:|\s]+$', lines[data_idx]):
            data_idx += 1

        rows = []
        while data_idx < len(lines):
            row_line = lines[data_idx]
            if not row_line.startswith('|'):
                break
            cells = [c.strip() for c in row_line.split('|')[1:-1]]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            elif len(cells) < len(headers):
                row = dict(zip(headers[:len(cells)], cells))
                rows.append(row)
            data_idx += 1

        if rows:
            seen.add((i, data_idx))
            tables.append({'headers': headers, 'rows': rows})
        i = data_idx

    return tables


def clean_amount(val):
    if val is None or val == '' or val == '－' or val == '—':
        return None
    if isinstance(val, (int, float)):
        return float(val)
    v = str(val).strip()
    if not v or v in ('－', '—', '-', '---'):
        return None
    try:
        return float(v.replace(',', ''))
    except ValueError:
        return None


def infer_unit(name):
    if not name:
        return ''
    if name == '人工':
        return '工日'
    if '混凝土' in name or '砂浆' in name:
        return 'm3'
    if any(k in name for k in ('板枋材', '圆木', '硬杂木', '块石', '片石', '碎石', '石屑')):
        return 'm3'
    if any(k in name for k in ('钢筋', '型钢', '钢板', '钢管', '铁件', '螺栓', '钢丝绳', '铁钉', '铁线', '电焊条', '连接卡具', '骨架', '支撑')):
        return 'kg'
    if '基价' in name:
        return '元'
    if '其他材料' in name or '其他船机' in name:
        return '元'
    if '船' in name or '驳' in name or '艇' in name:
        return '艘班'
    if any(k in name for k in ('起重机', '装载机', '汽车', '翻斗车', '搅拌', '钻机', '电焊机', '空压机', '卷扬机', '振捣器', '切断机', '弯曲机', '水泵', '抽水机')):
        return '台班'
    if '拖轮' in name:
        return '艘班'
    if name.endswith('气'):
        return 'm3'
    return ''


def build_chapter_tree(structure):
    """Build chapter hierarchy from structure.json, returning list of (chapter_id, parent_id, level, title, internal_page)."""
    raw = structure.get('chapters', [])

    # Flatten with proper sorting by internal_page
    all_nodes = []

    for ch in raw:
        ch_page = ch.get('internal_page') or 9999
        all_nodes.append({
            'parent_title': None,
            'level': 1,
            'title': ch['title'],
            'internal_page': ch_page,
            'sections': ch.get('sections', []),
        })

    # Sort chapters by internal_page
    all_nodes.sort(key=lambda x: x['internal_page'])

    result = []
    for ch in all_nodes:
        result.append((None, 1, ch['title'], ch['internal_page']))
        ch_title = ch['title']
        for sec in sorted(ch.get('sections', []), key=lambda s: s.get('internal_page') or 9999):
            sec_page = sec.get('internal_page') or 9999
            result.append((ch_title, 2, sec['title'], sec_page))
            for sub in sorted(sec.get('subsections', []), key=lambda s: s.get('internal_page') or 9999):
                sub_page = sub.get('internal_page') or 9999
                result.append((sec['title'], 3, sub['title'], sub_page))

    return result


def create_tables(conn):
    conn.executescript(DB_SCHEMA)
    conn.commit()


def load_structure(conn, structure):
    """Import document and chapter tables."""
    doc = structure.get('document', {})
    conn.execute(
        "INSERT INTO document (title, doc_number, total_pages) VALUES (?, ?, ?)",
        (doc.get('title', ''), doc.get('doc_number', ''), doc.get('total_pages', 0))
    )
    conn.commit()

    # Create a virtual chapter for front matter pages (cover, notice, toc, etc.)
    conn.execute(
        "INSERT INTO chapter (parent_id, sort_order, level, title, start_page) VALUES (NULL, 0, 0, '前置材料', NULL)"
    )
    front_matter_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    parent_map = {'前置材料': front_matter_id}
    chapter_ids = {'前置材料': front_matter_id}

    # Build and insert chapter tree
    chapter_nodes = build_chapter_tree(structure)

    for sort_order, (parent_title, level, title, internal_page) in enumerate(chapter_nodes):
        parent_id = parent_map.get(parent_title) if parent_title else None
        conn.execute(
            "INSERT INTO chapter (parent_id, sort_order, level, title, start_page) VALUES (?, ?, ?, ?, ?)",
            (parent_id, sort_order + 1, level, title, internal_page if internal_page != 9999 else None)
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        parent_map[title] = cid
        chapter_ids[title] = cid

    conn.commit()
    return chapter_ids, front_matter_id


def resolve_chapter_id(chapter_title, chapter_ids):
    """Match a chapter title string to a chapter_id."""
    if not chapter_title:
        return None
    # Direct match
    if chapter_title in chapter_ids:
        return chapter_ids[chapter_title]
    # Try to match by prefix
    for title, cid in chapter_ids.items():
        if title and chapter_title.startswith(title):
            return cid
        if title and title.startswith(chapter_title):
            return cid
    return None


def load_page(conn, md_path, chapter_ids, front_matter_id):
    """Load a single MD page into the database."""
    text = md_path.read_text(encoding='utf-8')
    fm = parse_frontmatter(text)
    page = fm.get('page', 0)
    page_type = fm.get('type', 'section_intro')

    # Resolve chapter_id
    chapter_title = fm.get('chapter', '')
    chapter_id = resolve_chapter_id(chapter_title, chapter_ids)
    if chapter_id is None:
        chapter_id = front_matter_id

    if page_type in TABLE_PAGE_TYPES:
        return _load_norms_page(conn, page, page_type, fm, text, chapter_id, chapter_title)
    else:
        return _load_text_page(conn, page, page_type, fm, text, chapter_id, chapter_title)


def _load_text_page(conn, page, page_type, fm, text, chapter_id, chapter_title):
    """Import a text page (cover, notice, toc, section_intro, etc.)."""
    content = parse_body_text(text)

    # Insert page_index
    conn.execute(
        "INSERT OR REPLACE INTO page_index (page, page_type, chapter_id, text_preview) VALUES (?, ?, ?, ?)",
        (page, page_type, chapter_id, content[:200] if content else '')
    )

    # Insert section_text
    if content.strip():
        conn.execute(
            "INSERT INTO section_text (chapter_id, page, seq_no, type, content) VALUES (?, ?, ?, ?, ?)",
            (chapter_id, page, 1, page_type, content.strip())
        )

    conn.commit()
    return page, 0


def _load_norms_page(conn, page, page_type, fm, text, chapter_id, chapter_title):
    """Import a norms table page."""
    tables = parse_tables(text)
    section_title = fm.get('section', '')
    subsection_title = fm.get('subsection', '')
    work_content = fm.get('work_content', '')
    unit = fm.get('unit', '')

    total_rows = 0
    table_id = None

    for seq, tbl in enumerate(tables):
        headers = tbl['headers']
        rows = tbl['rows']
        if not rows:
            continue

        # Build header_json
        attr_cols = [h for h in headers if h not in ('定额编号', '费用项目', '单位', '代码', '数量')]
        header_json = json.dumps({
            'attr_columns': attr_cols,
            'full_headers': headers,
        }, ensure_ascii=False)

        # Infer unit from first row if not in frontmatter
        tbl_unit = unit
        if not tbl_unit and rows:
            tbl_unit = rows[0].get('单位', '')

        conn.execute("""
            INSERT INTO norms_table
                (chapter_id, section_title, subsection_title, work_content, unit, page, seq_on_page, header_json, row_count, col_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chapter_id, section_title, subsection_title, work_content, tbl_unit,
            page, seq + 1, header_json, len(rows), len(headers),
        ))
        table_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert norms_items
        for sort_order, row in enumerate(rows):
            norms_code = row.get('定额编号', '').strip()
            if not norms_code:
                continue

            cost_item = row.get('费用项目', '').strip()
            if not cost_item:
                continue

            cost_unit = row.get('单位', '').strip()
            amount_raw = row.get('数量', '')
            amount = clean_amount(amount_raw)

            if not cost_unit:
                cost_unit = infer_unit(cost_item)

            # Extract attribute values
            attr_values = []
            attr_labels = []
            for ac in attr_cols:
                v = row.get(ac, '')
                if v:
                    attr_labels.append(ac)
                    attr_values.append(v)

            conn.execute("""
                INSERT INTO norms_item
                    (table_id, page, norms_code, sort_order,
                     attr_level1, attr_level2, attr_level3, attr_level4,
                     attr1_label, attr2_label, attr3_label, attr4_label,
                     cost_item, cost_item_unit, amount, data_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                table_id, page, norms_code, sort_order,
                attr_values[0] if len(attr_values) > 0 else '',
                attr_values[1] if len(attr_values) > 1 else '',
                attr_values[2] if len(attr_values) > 2 else '',
                attr_values[3] if len(attr_values) > 3 else '',
                attr_labels[0] if len(attr_labels) > 0 else '',
                attr_labels[1] if len(attr_labels) > 1 else '',
                attr_labels[2] if len(attr_labels) > 2 else '',
                attr_labels[3] if len(attr_labels) > 3 else '',
                cost_item, cost_unit, amount, 'raw',
            ))
            total_rows += 1

    # Insert page_index with table_id
    conn.execute(
        "INSERT OR REPLACE INTO page_index (page, page_type, chapter_id, table_id) VALUES (?, ?, ?, ?)",
        (page, page_type, chapter_id, table_id)
    )

    conn.commit()
    return page, total_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--md-dir', default=str(ROOT / 'output' / 'md_jts'))
    parser.add_argument('--db', default=str(ROOT / 'output' / 'db' / 'JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite'))
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    md_dir = Path(args.md_dir)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    structure_path = ROOT / 'output' / 'structure.json'
    if not structure_path.exists():
        print("ERROR: structure.json not found. Run build_md_jts.py first.")
        sys.exit(1)

    structure = json.loads(structure_path.read_text(encoding='utf-8'))

    md_files = sorted(md_dir.glob('page_*.md'))
    if not md_files:
        print(f"No MD files found in {md_dir}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    if args.reset:
        for tbl in ['norms_item', 'norms_table', 'page_index', 'chapter', 'section_text', 'document',
                     'appendix_row', 'appendix_table', 'ocr_block']:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    create_tables(conn)

    # Load structure
    chapter_ids, front_matter_id = load_structure(conn, structure)
    print(f"Imported {len(chapter_ids)} chapters (including front matter)")

    # Load pages
    total_pages = 0
    total_rows = 0
    for md_path in md_files:
        try:
            pg, n_rows = load_page(conn, md_path, chapter_ids, front_matter_id)
            total_pages += 1
            total_rows += n_rows
            ptype = ''
            if n_rows:
                ptype = f'  {n_rows} rows'
            else:
                fm = parse_frontmatter(md_path.read_text(encoding='utf-8'))
                ptype = f'  type={fm.get("type", "?")}'
            print(f"  page_{pg:04d}: {ptype}")
        except Exception as e:
            print(f"  ERROR {md_path.stem}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nLoaded {total_pages} pages, {total_rows} norms items into {db_path}")
    conn.close()


if __name__ == '__main__':
    main()
