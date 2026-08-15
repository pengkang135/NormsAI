"""
Export JTS SQLite data to JSON files for norms_browser.html.

Generates:
  output/norms_index.json  — chapter tree + table index
  output/norms_items/      — per-table item JSON files
"""
import json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'db' / 'refers' / 'JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite'
OUT_DIR = ROOT / 'output'


def export():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Export chapters
    chapters = []
    for row in conn.execute('SELECT * FROM chapter ORDER BY sort_order'):
        chapters.append({
            'id': row['id'],
            'parent_id': row['parent_id'],
            'sort_order': row['sort_order'],
            'level': row['level'],
            'title': row['title'],
            'start_page': row['start_page'],
            'end_page': row['end_page'],
        })

    # Export tables
    tables = []
    for row in conn.execute('SELECT qt.*, ch.title as chapter_title FROM norms_table qt LEFT JOIN chapter ch ON qt.chapter_id = ch.id ORDER BY qt.page, qt.seq_on_page'):
        tables.append({
            'id': row['id'],
            'chapter_id': row['chapter_id'],
            'chapter_title': row['chapter_title'] or '',
            'section_title': row['section_title'] or '',
            'subsection_title': row['subsection_title'] or '',
            'subsection_clean': (row['subsection_title'] or '').lstrip('一二三四五六七八九十、'),
            'work_content': row['work_content'] or '',
            'unit': row['unit'] or '',
            'page': row['page'],
            'seq_on_page': row['seq_on_page'],
            'row_count': row['row_count'],
            'col_count': row['col_count'],
        })

    # Export page_index (for text pages)
    pages = []
    for row in conn.execute('SELECT pi.*, ch.title as chapter_title FROM page_index pi LEFT JOIN chapter ch ON pi.chapter_id = ch.id ORDER BY pi.page'):
        pages.append({
            'page': row['page'],
            'page_type': row['page_type'],
            'chapter_id': row['chapter_id'],
            'chapter_title': row['chapter_title'] or '',
            'table_id': row['table_id'],
            'text_preview': row['text_preview'] or '',
        })

    # Build code_index for fast code→table lookup
    code_index = {}
    for trow in conn.execute('SELECT id FROM norms_table'):
        tid = trow['id']
        for row in conn.execute('SELECT DISTINCT norms_code FROM norms_item WHERE table_id = ?', (tid,)):
            code = row['norms_code']
            if code:
                code_index[code] = tid

    index = {
        'chapters': chapters,
        'tables': tables,
        'pages': pages,
        'code_index': code_index,
    }

    (OUT_DIR / 'norms_index.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote norms_index.json ({len(chapters)} chapters, {len(tables)} tables, {len(pages)} pages)")

    # Export per-table items
    items_dir = OUT_DIR / 'norms_items'
    items_dir.mkdir(parents=True, exist_ok=True)

    for trow in conn.execute('SELECT id FROM norms_table'):
        tid = trow['id']
        items = []
        for row in conn.execute('SELECT * FROM norms_item WHERE table_id = ? ORDER BY sort_order', (tid,)):
            items.append({
                'norms_code': row['norms_code'],
                'attr_level1': row['attr_level1'] or '',
                'attr_level2': row['attr_level2'] or '',
                'attr_level3': row['attr_level3'] or '',
                'attr_level4': row['attr_level4'] or '',
                'attr1_label': row['attr1_label'] or '',
                'attr2_label': row['attr2_label'] or '',
                'attr3_label': row['attr3_label'] or '',
                'attr4_label': row['attr4_label'] or '',
                'cost_item': row['cost_item'],
                'cost_item_unit': row['cost_item_unit'] or '',
                'amount': row['amount'],
            })
        (items_dir / f'{tid}.json').write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"Wrote {len(list(items_dir.glob('*.json')))} item files")

    # Export section_text pages for text display
    texts_dir = OUT_DIR / 'norms_texts'
    texts_dir.mkdir(parents=True, exist_ok=True)
    for row in conn.execute('SELECT page, type, content FROM section_text ORDER BY page'):
        if row['content']:
            (texts_dir / f'{row["page"]}.json').write_text(
                json.dumps({'page': row['page'], 'type': row['type'], 'content': row['content']},
                          ensure_ascii=False), encoding='utf-8')

    print(f"Wrote {len(list(texts_dir.glob('*.json')))} text page files")
    conn.close()


if __name__ == '__main__':
    export()
