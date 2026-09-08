# -*- coding: utf-8 -*-
"""JTS/T 277-2019 配比材料消耗量 md → 定额库（refers/ 独立库）。

沿用 config.DB_SCHEMA（PDF 提取 schema），配比规格映射到 norms_item 1D 长格式：
属性列(粒径/强度/水胶比/抗冻…)→attr_level，材料列(水泥/碎石/砂/水…)→cost_item。
"""
import re
import sqlite3
import sys

sys.path.insert(0, '.')
from config import DB_SCHEMA

SRC = r'f:/BaiduSyncdisk/2.清单定额/1 预算定额/3 水工定额/配比材料/JTS 277-2019 水运工程混凝土和砂浆材料用量定额（非正式出版稿）.md'
OUT = r'db/refers/norms_jts277-2019_配比材料.sqlite'

MAT_UNIT = {'t': 't', 'm³': 'm3', 'kg': 'kg'}
PRICE_UNIT = '元'


def parse_header_cell(cell):
    """表头单元格 → (kind, name, unit)。kind: mat/price/attr。"""
    c = cell.strip()
    m = re.search(r'（([^（）]+)）\s*$', c)  # 末尾全角括号单位
    if m:
        u = m.group(1)
        name = c[:m.start()].strip()
        if u in MAT_UNIT:
            return 'mat', name, MAT_UNIT[u]
        if u == PRICE_UNIT:
            return 'price', name, PRICE_UNIT
        # 其他单位（MPa 等）→ 属性列
        return 'attr', c, None
    return 'attr', c, None


def norm_cost_item(name):
    """规范化材料名：去掉（强度等级）冗余括号。"""
    return name.replace('（强度等级）', '').strip()


def norm_attr_label(label):
    """属性列名规范化：只去空格，保留 (mm)/（MPa）等。"""
    return label.strip()


def norm_unit(u):
    return 'm3' if u == 'm³' else u


def clean_subsection(sub):
    """配比名清理：取最末段（子配比名），去（一）/1. 序号与 1m³/1kg 单位。"""
    parts = [p.strip() for p in sub.split('/') if p.strip()]
    last = parts[-1] if parts else ''
    last = re.sub(r'^（[一二三四五六七八九十]+）\s*', '', last)
    last = re.sub(r'^[0-9]+[\.、]\s*', '', last)
    last = re.sub(r'\s*1m[³3]\s*$', '', last)
    last = re.sub(r'\s*1kg\s*$', '', last)
    return last.strip()


def clean_section(sec):
    """节名清理：去「一、」「二、」序号。"""
    return re.sub(r'^[一二三四五六七八九十]+[、.]\s*', '', (sec or '').strip()).strip()


def classify_heading(line):
    """标题行 → (level, text) 或 None。level: 1章 2节 3小节 4续表。"""
    s = line.strip()
    if s.startswith('## '):
        t = s[3:].strip()
        if re.match(r'^第[一二三四五六七八九十]+章', t):
            return 1, t
        return None
    if s.startswith('### '):
        return 2, s[4:].strip()
    if s.startswith('#### '):
        t = s[5:].strip()
        if t.startswith('续表'):
            return 4, t
        return 3, t
    return None


def split_row(line):
    cells = line.strip().strip('|').split('|')
    return [c.strip() for c in cells]


def main():
    with open(SRC, encoding='utf-8') as f:
        lines = f.read().split('\n')

    con = sqlite3.connect(OUT)
    con.executescript(DB_SCHEMA)
    con.execute('DELETE FROM document')
    con.execute('DELETE FROM chapter')
    con.execute('DELETE FROM norms_table')
    con.execute('DELETE FROM norms_item')
    con.execute('DELETE FROM section_text')
    con.execute('DELETE FROM page_index')

    con.execute(
        'INSERT INTO document (title, doc_number, total_pages) VALUES (?,?,?)',
        ('水运工程混凝土和砂浆材料用量定额', 'JTS/T 277-2019', 74))

    chapter_id = None       # 当前章
    section_id = None       # 当前节
    section_title = None
    group_title = None      # （一）分组
    subsection_title = None  # 配比名
    unit = None
    cont_table_id = None    # 续表合并目标

    table_seq = 0           # 章内表序号
    row_seq = 0             # 表内行序号

    # 表头解析结果缓存
    headers = []            # [(kind, name, unit)]

    sort_counter = [0]

    def build_chapter(level, title, parent):
        sort_counter[0] += 1
        cur = con.execute(
            'INSERT INTO chapter (parent_id, sort_order, level, title) VALUES (?,?,?,?)',
            (parent, sort_counter[0], level, title))
        return cur.lastrowid

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip('\n')

        # 裸单位行（1m³ / 1kg）
        if re.match(r'^\s*(1m[³3]|1kg)\s*$', line):
            unit = '1m3' if 'm' in line else '1kg'
            i += 1
            continue

        # 表格块
        if line.strip().startswith('|'):
            block = []
            while i < n and lines[i].strip().startswith('|'):
                block.append(lines[i])
                i += 1
            # block[0]=表头, block[1]=|---|, 其余=数据行
            if len(block) >= 3:
                header_cells = split_row(block[0])
                headers = [parse_header_cell(c) for c in header_cells]
                attr_cols = [j for j, (k, _, _) in enumerate(headers) if k == 'attr']
                mat_cols = [j for j, (k, _, _) in enumerate(headers) if k == 'mat']
                price_cols = [j for j, (k, _, _) in enumerate(headers) if k == 'price']

                # 续表：追加到上一表
                if cont_table_id is not None:
                    table_id = cont_table_id
                else:
                    table_seq += 1
                    parts = []
                    if group_title:
                        parts.append(group_title)
                    if subsection_title and subsection_title != group_title:
                        parts.append(subsection_title)
                    sub = clean_subsection(' / '.join(parts)) if parts else ''
                    if not sub:
                        sub = clean_section(section_title)
                    header_json = '{}'
                    cur = con.execute(
                        'INSERT INTO norms_table (chapter_id, section_title, subsection_title, unit, page, header_json) '
                        'VALUES (?,?,?,?,?,?)',
                        (section_id, '', sub, unit or '1m3', 0, header_json))
                    table_id = cur.lastrowid
                    con.execute('UPDATE norms_table SET page=? WHERE id=?', (table_id, table_id))
                    con.execute(
                        'INSERT INTO page_index (page, page_type, chapter_id, table_id, ocr_status) '
                        'VALUES (?,?,?,?,?)',
                        (table_id, 'norms_table', section_id, table_id, 'md'))

                # 数据行
                for r in block[2:]:
                    cells = split_row(r)
                    if not any(cells):
                        continue
                    row_seq += 1
                    # 属性值
                    attr = {}
                    for idx, j in enumerate(attr_cols):
                        if j < len(cells):
                            attr[f'attr{idx + 1}'] = cells[j]
                    # 材料 + 基价
                    for j in mat_cols + price_cols:
                        if j >= len(cells):
                            continue
                        v = cells[j]
                        if v in ('', '-'):
                            continue
                        kind, name, u = headers[j]
                        cost_item = norm_cost_item(name)
                        if kind == 'price':
                            cost_item = '基价'
                            u = '元'
                        # 水的单位修正
                        if cost_item == '水':
                            u = 't'
                        try:
                            amount = float(v.replace(',', ''))
                        except ValueError:
                            continue
                        cur = con.execute(
                            'INSERT INTO norms_item (table_id, page, norms_code, sort_order, '
                            'attr_level1, attr_level2, attr_level3, attr_level4, '
                            'attr1_label, attr2_label, attr3_label, attr4_label, '
                            'cost_item, cost_item_unit, amount, ocr_source, data_quality) '
                            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (table_id, 0, '', row_seq,
                             attr.get('attr1'), attr.get('attr2'), attr.get('attr3'), attr.get('attr4'),
                             norm_attr_label(headers[attr_cols[0]][1]) if len(attr_cols) > 0 else None,
                             norm_attr_label(headers[attr_cols[1]][1]) if len(attr_cols) > 1 else None,
                             norm_attr_label(headers[attr_cols[2]][1]) if len(attr_cols) > 2 else None,
                             norm_attr_label(headers[attr_cols[3]][1]) if len(attr_cols) > 3 else None,
                             cost_item, u, amount, 'md', 'raw'))
                cont_table_id = None
            continue

        # 标题行
        h = classify_heading(line)
        if h:
            level, title = h
            if level == 1:
                chapter_id = build_chapter(1, title, None)
                section_id = None
                section_title = None
                group_title = None
                subsection_title = None
                unit = None
                table_seq = 0
            elif level == 2:
                section_id = build_chapter(2, title, chapter_id)
                section_title = title
                group_title = None
                subsection_title = None
                unit = None
            elif level == 3:
                has_unit = bool(re.search(r'1m[³3]|1kg', title))
                u = '1m3' if re.search(r'1m[³3]', title) else ('1kg' if '1kg' in title else None)
                if re.match(r'^（[一二三四五六七八九十]+）', title):
                    # （一）（二）标题 = 新分组层级；含单位则分组+配比合一
                    group_title = title
                    subsection_title = title if has_unit else None
                    unit = u if has_unit else None
                else:
                    # 1. 2. 等数字标题 = 配比
                    subsection_title = title
                    unit = u
                if has_unit:
                    row_seq = 0
            elif level == 4:
                # 续表：下一个表格合并到上一表
                cont_table_id = con.execute(
                    'SELECT id FROM norms_table ORDER BY id DESC LIMIT 1').fetchone()
                cont_table_id = cont_table_id[0] if cont_table_id else None

        i += 1

    # 回填 norms_code
    l2_to_l1 = dict(con.execute('SELECT id, parent_id FROM chapter WHERE level=2'))
    ch_map = {}
    for cid, in con.execute('SELECT id FROM chapter WHERE level=1 ORDER BY id'):
        ch_map[cid] = len(ch_map) + 1
    for tid, cid in con.execute('SELECT id, chapter_id FROM norms_table ORDER BY id'):
        # table_seq 按章内顺序
        tseq = con.execute(
            'SELECT COUNT(*) FROM norms_table WHERE chapter_id=? AND id<=?', (cid, tid)).fetchone()[0]
        cno = ch_map.get(l2_to_l1.get(cid, cid), 0)
        for iid, so in con.execute('SELECT id, sort_order FROM norms_item WHERE table_id=? ORDER BY id', (tid,)):
            code = f'S{cno:02d}{tseq:02d}{so:03d}'
            con.execute('UPDATE norms_item SET norms_code=? WHERE id=?', (code, iid))

    for tid, in con.execute('SELECT id FROM norms_table'):
        rc = con.execute(
            'SELECT COUNT(DISTINCT sort_order) FROM norms_item WHERE table_id=?', (tid,)).fetchone()[0]
        con.execute('UPDATE norms_table SET row_count=? WHERE id=?', (rc, tid))

    con.commit()

    # 统计
    def cnt(t):
        return con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]

    print('输出:', OUT)
    print('document:', cnt('document'))
    print('chapter:', cnt('chapter'))
    print('norms_table:', cnt('norms_table'))
    print('norms_item:', cnt('norms_item'))
    # 材料列全集
    mats = con.execute('SELECT DISTINCT cost_item, cost_item_unit FROM norms_item ORDER BY cost_item').fetchall()
    print(f'--- 材料列全集 ({len(mats)}) ---')
    for m, u in mats:
        print(f'  {m} [{u}]')
    con.close()


if __name__ == '__main__':
    main()
