"""Import 配比材料 from 报价模板.xlsm (3.3土建定额) into PK土建定额库 SQLite."""
import zipfile, re, json, sqlite3, sys
from pathlib import Path

XLSM_PATH = Path('1 预算定额/5 PK定额库/定额库模板/2026-6-27 报价模板.xlsm')
DB_PATH = Path('Norms-AI/db/refers/boq_pk_civil_202606.sqlite')
BATCH_CODE = 'X'    # 配比材料 section code prefix
BATCH_CODE_L2 = 'X.a'  # 配比材料 subsection code prefix

def parse_sheet_6(xlsm_path):
    zf = zipfile.ZipFile(xlsm_path)
    raw_ss = zf.open('xl/sharedStrings.xml').read()
    strings = [t.decode('utf-8') for t in re.findall(rb'<t[^>]*>([^<]*)</t>', raw_ss)]
    raw6 = zf.open('xl/worksheets/sheet6.xml').read().decode('utf-8')

    cell_pat = re.compile(
        r'<c r="([A-Z]+)(\d+)"'
        r'([^>]*?)'
        r'(/>'
        r'|>(.*?)</c>)'
    )

    rows_data = {}
    for m in cell_pat.finditer(raw6):
        col = m.group(1)
        row = int(m.group(2))
        attrs = m.group(3)
        content = m.group(5)
        if row not in rows_data:
            rows_data[row] = {}
        if content is None:
            continue
        t_match = re.search(r't="([^"]*)"', attrs)
        v_match = re.search(r'<v>([^<]+)</v>', content)
        is_match = re.search(r'<is><t>([^<]*)</t></is>', content)
        if t_match and t_match.group(1) == 's' and v_match:
            si = int(v_match.group(1))
            rows_data[row][col] = strings[si] if si < len(strings) else v_match.group(1)
        elif is_match:
            rows_data[row][col] = is_match.group(1)
        elif v_match:
            rows_data[row][col] = v_match.group(1)
    zf.close()
    return rows_data


def safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    print("Parsing 3.3土建定额 sheet...")
    rows = parse_sheet_6(str(XLSM_PATH))

    # Extract header info
    header = rows.get(1, {})

    # Row 2: L1 section title 【配比材料】
    section_b = rows.get(2, {}).get('B', '')
    section_title = section_b.strip('【】')

    # Row 3: L2 subsection with resource definitions
    sub_b = rows.get(3, {}).get('B', '')
    sub_title = sub_b.strip('《》')

    # Extract resource definitions from Row 3
    # Columns J-V contain "name\nunit" format
    resources = []
    res_col_map = {}  # col_letter -> resource index
    for col in 'JKLMNOPQRSTUVWXYZ':
        val = rows.get(3, {}).get(col, '')
        if val and '\n' in val:
            parts = val.strip().split('\n')
            name = parts[0].strip()
            unit = parts[1].strip() if len(parts) > 1 else ''
            if name:
                resources.append({'col': col, 'name': name, 'unit': unit})
                res_col_map[col] = len(resources) - 1

    # Row 4: Resource unit prices
    for r in resources:
        price_val = rows.get(4, {}).get(r['col'], '0')
        r['unit_price'] = safe_float(price_val) or 0

    print(f"Section: {section_title}")
    print(f"Subsection: {sub_title}")
    print(f"Resources: {len(resources)}")
    for r in resources:
        print(f"  {r['col']}: {r['name']} ({r['unit']}) @ {r['unit_price']}")

    # Collect material items (rows with B列=item name and C列=unit)
    items = []
    for rn in sorted(rows.keys()):
        rd = rows[rn]
        b_val = rd.get('B', '')
        c_val = rd.get('C', '')
        e_val = safe_float(rd.get('E'))
        # Skip header rows, section headers, empty rows
        if rn <= 4:
            continue
        if not b_val or b_val.startswith('【') or b_val.startswith('《'):
            continue
        item = {
            'row': rn,
            'name': b_val.strip(),
            'unit': c_val.strip(),
            'rate': e_val,
            'labour': safe_float(rd.get('F')),
            'materials': safe_float(rd.get('G')),
            'mech': safe_float(rd.get('H', '0')),
            'mgmt_rate': safe_float(rd.get('I')),
            'quantity': safe_float(rd.get('D')),
            'consumption': {}
        }
        for r in resources:
            qty = safe_float(rd.get(r['col']))
            if qty is not None and qty != 0:
                item['consumption'][r['col']] = qty
        items.append(item)

    print(f"\nMaterial items: {len(items)}")
    for item in items:
        print(f"  {item['name']:30s} {item['unit']:4s} rate={item['rate']}")

    # ── Write to SQLite ──
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA foreign_keys = ON")

    # Find max IDs to avoid conflicts
    max_chapter = db.execute("SELECT COALESCE(MAX(id), 0) FROM chapter").fetchone()[0]
    max_table = db.execute("SELECT COALESCE(MAX(id), 0) FROM norms_table").fetchone()[0]
    max_item = db.execute("SELECT COALESCE(MAX(id), 0) FROM norms_item").fetchone()[0]
    max_page = db.execute("SELECT COALESCE(MAX(page), 0) FROM page_index").fetchone()[0]

    # Check if already imported
    existing = db.execute(
        "SELECT id FROM chapter WHERE code = ? AND level = 1", (BATCH_CODE,)
    ).fetchone()
    if existing:
        print(f"\n配比材料 section already exists (id={existing[0]}), deleting...")
        l1_id = existing[0]
        all_x_chapters = [row[0] for row in db.execute(
            "SELECT id FROM chapter WHERE code LIKE 'X%'"
        ).fetchall()]
        for cid in all_x_chapters:
            db.execute("DELETE FROM norms_item WHERE table_id IN (SELECT id FROM norms_table WHERE chapter_id = ?)", (cid,))
            db.execute("DELETE FROM norms_table WHERE chapter_id = ?", (cid,))
            db.execute("DELETE FROM page_index WHERE chapter_id = ?", (cid,))
        # Delete children first, then parent
        for cid in sorted(all_x_chapters, reverse=True):
            db.execute("DELETE FROM chapter WHERE id = ?", (cid,))

    db.commit()

    # Create chapter structure: X 配比材料 (L1) -> X.a 配比_混凝土制品 (L2)
    page_start = max_page + 1
    page_end = max_page + len(items)

    cid_l1 = max_chapter + 1
    cid_l2 = max_chapter + 2

    # L1: X 配比材料
    db.execute("""
        INSERT INTO chapter (id, parent_id, sort_order, level, title, subtitle, code, bracket_type, start_page, end_page)
        VALUES (?, NULL, ?, 1, ?, ?, ?, 'section', ?, ?)
    """, (cid_l1, 900, f"{BATCH_CODE} {section_title}", '', BATCH_CODE, page_start, page_end))

    # L2: X.a 配比_混凝土制品
    db.execute("""
        INSERT INTO chapter (id, parent_id, sort_order, level, title, subtitle, code, bracket_type, start_page, end_page)
        VALUES (?, ?, ?, 2, ?, ?, ?, 'subsection', ?, ?)
    """, (cid_l2, cid_l1, 1, f"{BATCH_CODE_L2} {sub_title}", '', BATCH_CODE_L2, page_start, page_end))

    print(f"Created chapters: L1={cid_l1}, L2={cid_l2}")

    # Create one norms_table per material item
    table_ids = []
    for i, item in enumerate(items):
        tid = max_table + 1 + i
        table_ids.append(tid)
        page = page_start + i

        # Build header_json with cost + resource info
        res_count = sum(1 for r in resources if item['consumption'].get(r['col'], 0) != 0)
        header = {
            'resources': [{'col': r['col'], 'name': r['name'], 'unit': r['unit'],
                           'unit_price': r['unit_price']} for r in resources],
            'unit': item['unit'],
            'rate': item['rate'],
            'labour': item['labour'],
            'materials': item['materials'],
            'mech': item['mech'],
        }

        db.execute("""
            INSERT INTO norms_table (id, chapter_id, section_title, subsection_title, unit, page, seq_on_page, header_json, row_count, col_count)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (tid, cid_l2, f"{BATCH_CODE_L2} {sub_title}", item['name'],
              item['unit'], page, json.dumps(header, ensure_ascii=False),
              res_count, 2))

        # Page index entry
        db.execute("""
            INSERT INTO page_index (page, page_type, chapter_id, table_id, text_preview)
            VALUES (?, 'norms_table', ?, ?, ?)
        """, (page, cid_l2, tid, item['name']))

        # norms_items: resource consumption rows only
        sort = 0
        item_id_base = max_item + 1 + i * 20

        # Resource consumption rows
        for r in resources:
            qty = item['consumption'].get(r['col'], 0)
            if qty:
                db.execute("""
                    INSERT INTO norms_item (id, table_id, norms_code, sort_order,
                        cost_item, cost_item_unit, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (item_id_base + sort, tid, item['name'], sort,
                      r['name'], r['unit'], qty))
                sort += 1

    db.commit()

    # Verify
    ch_count = db.execute("SELECT COUNT(*) FROM chapter WHERE code LIKE 'X%'").fetchone()[0]
    tbl_count = db.execute("SELECT COUNT(*) FROM norms_table WHERE chapter_id IN (SELECT id FROM chapter WHERE code LIKE 'X%')").fetchone()[0]
    itm_count = db.execute("SELECT COUNT(*) FROM norms_item WHERE table_id IN (SELECT id FROM norms_table WHERE chapter_id IN (SELECT id FROM chapter WHERE code LIKE 'X%'))").fetchone()[0]
    pg_count = db.execute("SELECT COUNT(*) FROM page_index WHERE chapter_id IN (SELECT id FROM chapter WHERE code LIKE 'X%')").fetchone()[0]

    print(f"\nImport complete: {ch_count} chapters, {tbl_count} tables, {itm_count} items, {pg_count} pages")

    db.close()


if __name__ == '__main__':
    main()
