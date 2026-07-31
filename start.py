#!/usr/bin/env python3
"""启动定额浏览器。

在 Norms-AI/output/ 目录下启动HTTP服务，
自动打开浏览器访问 jts_browser.html。
内置 /api/ 端点直接查询 SQLite，无需预导出 JSON。

Usage:
    python start.py              # 默认端口 8080
    python start.py --port 9000  # 自定义端口
    python start.py --no-open    # 不自动打开浏览器
"""

import sys
import os
import argparse
import http.server
import socketserver
import webbrowser
import threading
import json
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
DB_DIR = ROOT_DIR / "db"
INTERMEDIATE_DIR = OUTPUT_DIR / "intermediate"
TEXT_DIR = INTERMEDIATE_DIR / "text"

# 附录表格定制渲染器
try:
    from src.appendix_tables import render as render_appendix_table
except ImportError:
    render_appendix_table = None

DOC_TO_DB = {
    "jts_2019_excel": "norms_jts276-1-2019_excel.sqlite",
    "jts_2019_excel_ref": "norms_jts276-3-2019_excel.sqlite",
    "bj_2012_norm": "北京2012_建设工程计价依据_预算定额.sqlite",
    "bj_2012_repair": "北京2012_房屋修缮工程计价依据_预算定额.sqlite",
    "bj_2012_bill_2013": "北京2012_建设工程计价依据_清单规范2013.sqlite",
    "bj_2012_bill_2009": "北京2012_建设工程计价依据_清单规范2009.sqlite",
    "boq_pk_civil_202606": "boq_pk_civil_202606.sqlite",
    "sanhang_laldia": "三航局Laldia项目人工机械定额.sqlite",
    "ent_a_building": "企业定额_A册_建筑装饰.sqlite",
    "ent_b_mechanical": "企业定额_B册_通用安装.sqlite",
    "ent_c_municipal": "企业定额_C册_市政园林.sqlite",
    "ent_d_water": "企业定额_D册_水运工程.sqlite",
    "bj_2021_building": "北京2021房屋建筑与装饰工程预算消耗量定额.sqlite",
}

# 北京2012定额schema的doc key（使用不同的 Norm/Consumption/Content 表结构）
# 企业定额 A/C 册也复用同一 schema
BJ_DOC_KEYS = {
    "bj_2012_norm", "bj_2012_repair", "bj_2012_bill_2013", "bj_2012_bill_2009",
    "ent_a_building", "ent_b_mechanical", "ent_c_municipal", "ent_d_water",
}

# 2021版房屋建筑与装饰工程消耗量标准 schema
BJ2021_DOC_KEYS = {"bj_2021_building"}


def text_page_to_html(page):
    """将原始文本JSON（含坐标）转为HTML，自动检测并渲染表格。"""
    fpath = TEXT_DIR / f"page_{page:04d}.json"
    if not fpath.exists():
        return None

    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Check for custom appendix table renderer first
    if render_appendix_table:
        custom_html = render_appendix_table(page)
        if custom_html:
            return f'<div class="text-page">{custom_html}</div>'

    lines = data.get('lines', [])
    if not lines:
        return '<div class="text-page"><p>（无文本内容）</p></div>'

    # Sort by y then x
    lines.sort(key=lambda l: (l['y'], l['x']))

    # Phase 1: Group lines by y into rows (tolerance = 5px)
    rows = []  # [[line, ...], ...]
    for line in lines:
        if not line.get('text', '').strip():
            continue
        if rows and abs(line['y'] - rows[-1][0]['y']) <= 5:
            rows[-1].append(line)
        else:
            rows.append([line])

    # Sort each row by x
    for row in rows:
        row.sort(key=lambda l: l['x'])

    # Phase 2: Detect table regions
    # Strategy: find table titles (rows with "表" prefix), then extend backward
    # to include preceding single-cell short rows and forward through multi-cell rows
    import re

    # Mark each row as table-candidate
    row_is_table = [False] * len(rows)
    table_title_indices = set()

    for i, row in enumerate(rows):
        combined = ''.join(l['text'] for l in row)
        # Only match when table keyword starts the row or is preceded by whitespace
        # Avoid matching "按表1", "见表2" etc.
        if re.match(r'^(续?附表?\d|续?表[\d一二三四五六七八九十]|续表)', combined.strip()):
            table_title_indices.add(i)

    # Expand from each table title: forward through multi-cell rows
    for ti in sorted(table_title_indices):
        # Extend backward to include preceding short single-cell rows (like "表1")
        j = ti
        while j >= 0 and not row_is_table[j]:
            row_is_table[j] = True
            j -= 1
            if j >= 0:
                combined = ''.join(l['text'] for l in rows[j])
                if len(combined) > 30 and len(rows[j]) == 1:
                    break  # don't go past paragraph text

        # Extend forward
        j = ti + 1
        while j < len(rows):
            if len(rows[j]) >= 2:
                row_is_table[j] = True
            elif len(rows[j]) == 1:
                txt = rows[j][0]['text']
                if txt.startswith('注') or txt.startswith('注：'):
                    break
                # Page numbers end table (must have dash/marker or be at page edge)
                stripped = txt.strip()
                is_page_num = bool(re.match(r'^[-–—·]\s*\d+\s*[-–—·]?\s*$', stripped))
                if not is_page_num:
                    x0 = rows[j][0]['x']
                    is_page_num = (x0 < 60 or x0 > 500) and re.match(r'^\d{1,3}$', stripped)
                if is_page_num:
                    break
                # Short text or table-related → continue
                if len(txt) < 20 or any(kw in txt for kw in ['表', '附表', '续表']):
                    row_is_table[j] = True
                else:
                    break  # long paragraph text ends table
            else:
                break
            j += 1

    # Fallback: 4+ consecutive rows with 2+ cells each
    i = 0
    while i < len(rows):
        if row_is_table[i]:
            i += 1
            continue
        if len(rows[i]) >= 2:
            j = i
            while j < len(rows) and len(rows[j]) >= 2:
                j += 1
            if j - i >= 4:
                for k in range(i, j):
                    row_is_table[k] = True
            i = j
        else:
            i += 1

    # Build segments
    segments = []
    i = 0
    while i < len(rows):
        if row_is_table[i]:
            j = i
            while j < len(rows) and row_is_table[j]:
                j += 1
            segments.append((i, j, True))
            i = j
        else:
            j = i
            while j < len(rows) and not row_is_table[j]:
                j += 1
            segments.append((i, j, False))
            i = j

    # Merge adjacent non-table segments
    merged = []
    for start, end, is_table in segments:
        if merged and not is_table and not merged[-1][2]:
            merged[-1] = (merged[-1][0], end, False)
        else:
            merged.append((start, end, is_table))
    segments = merged

    # Phase 3: Build HTML
    html_parts = ['<div class="text-page">']

    for start, end, is_table in segments:
        if not is_table:
            # Paragraph text
            for idx in range(start, end):
                for line in rows[idx]:
                    txt = line['text'].strip()
                    if txt:
                        html_parts.append(f'<p>{_esc(txt)}</p>')
        else:
            # Table region
            table_rows = rows[start:end]
            html_parts.append(_build_table_html(table_rows))

    html_parts.append('</div>')
    return '\n'.join(html_parts)


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _build_table_html(table_rows):
    """从坐标行列表构建HTML表格。"""
    import re

    # Find table title row — used as caption and to mark the header boundary
    title_text = ''
    data_start = 0
    for i, row in enumerate(table_rows):
        combined = ''.join(l['text'] for l in row)
        if re.match(r'^(续?附表?\d|续?表[\d一二三四五六七八九十]|续表)', combined.strip()):
            title_text = combined.strip()
            data_start = i + 1
            break

    # Find data end: row with "注：" or "注 " prefix, or page number only
    data_end = len(table_rows)
    for i in range(data_start, len(table_rows)):
        combined = ''.join(l['text'] for l in table_rows[i])
        if combined.startswith('注') or combined.startswith('注：'):
            data_end = i
            break
        # Page number: must have dash/footnote markers, or be a short number at page edge
        stripped = combined.strip()
        is_page_num = bool(re.match(r'^[-–—·]\s*\d+\s*[-–—·]?\s*$', stripped))
        if not is_page_num and len(table_rows[i]) == 1:
            x0 = table_rows[i][0]['x']
            is_page_num = (x0 < 60 or x0 > 500) and re.match(r'^\d{1,3}$', stripped)
        if is_page_num:
            data_end = i
            break

    # Determine column count from the row with the most cells.
    max_cells = max((len(r) for r in table_rows[data_start:data_end]), default=1)
    n_cols = max_cells

    # Gather x positions from multi-cell rows for primary gap detection.
    multi_x = sorted(set(
        round(line['x'], 0)
        for row in table_rows[data_start:data_end] if len(row) >= 2
        for line in row
    ))
    # Also gather single-cell positions — they may reveal label columns on the left.
    solo_x = sorted(set(
        round(row[0]['x'], 0)
        for row in table_rows[data_start:data_end] if len(row) == 1
    ))
    # Left-side label column: single-cell positions to the left of the first multi-cell position,
    # clustered within 25px, with 2+ occurrences.
    left_solo = [x for x in solo_x if multi_x and x < multi_x[0] - 10]
    if left_solo and len(left_solo) >= 2:
        all_x = sorted(set(multi_x + solo_x))
    else:
        all_x = multi_x

    if len(all_x) <= n_cols:
        # Too few distinct x — use all cols from max-cells row as anchors
        max_cells_row = max(
            (r for r in table_rows[data_start:data_end] if len(r) == max_cells),
            key=lambda r: len(r), default=table_rows[data_start])
        col_anchors = sorted(set(round(cell['x'], 0) for cell in max_cells_row))
        n_cols = len(col_anchors)
    else:
        # Use top N-1 largest gaps as column boundaries.
        # If the Nth gap is comparable to the (N-1)th, add an extra column.
        gaps = [(all_x[i] - all_x[i-1], i) for i in range(1, len(all_x))]
        gaps.sort(key=lambda g: -g[0])
        # Only expand at most 1 extra column (for left-side label columns like P35).
        # More aggressive expansion creates too many columns for complex headers (P38).
        if n_cols < len(all_x) and n_cols >= 2:
            nth = gaps[n_cols - 2][0]
            extra = gaps[n_cols - 1][0]
            if nth > 0 and extra / nth >= 0.7:
                n_cols += 1
        boundaries = sorted(g[1] for g in gaps[:n_cols - 1])

        col_anchors = []
        cluster_start = all_x[0]
        for i, b in enumerate(boundaries):
            col_anchors.append(round((cluster_start + all_x[b-1]) / 2))
            cluster_start = all_x[b]
        col_anchors.append(round((cluster_start + all_x[-1]) / 2))
        n_cols = len(col_anchors)

    def x_to_col(x):
        return min(range(n_cols), key=lambda c: abs(x - col_anchors[c]))

    # Build grid: assign cells to nearest column, merge multi-line
    # adjacent rows that only populate one column
    grid = []  # [{col: text}]
    for i in range(data_start, data_end):
        row = table_rows[i]
        row_cells = {}
        for line in row:
            col = x_to_col(round(line['x'], 0))
            existing = row_cells.get(col, '')
            row_cells[col] = existing + line['text'] if existing else line['text']
        grid.append(row_cells)

    # Merge continuation rows: if a row has only 1 non-empty cell and
    # that cell is in a column that had content in the previous row
    # at similar x, merge the text upward (multi-line cell)
    merged_grid = []
    for ri, row_cells in enumerate(grid):
        non_empty = {c: t for c, t in row_cells.items() if t.strip()}
        if len(non_empty) == 1 and merged_grid:
            col, text = next(iter(non_empty.items()))
            # Check if this is a continuation
            prev = merged_grid[-1]
            if col in prev:
                prev[col] = prev[col] + text
                continue
        merged_grid.append(row_cells)
    grid = merged_grid

    # Detect header rows: rows before first row with digits in any cell
    first_data_row = 0
    for ri, row_cells in enumerate(grid):
        if any(_has_digit(t) for t in row_cells.values()):
            first_data_row = ri
            break

    html = ['<div class="table-card">']
    if title_text:
        html.append(f'<div class="table-card-header"><div class="table-card-info"><div class="title">{_esc(title_text)}</div></div></div>')
    html.append('<div class="data-table-wrap"><table class="data-table"><tbody>')

    for ri, row_cells in enumerate(grid):
        is_header = ri < first_data_row
        tag = 'th' if is_header else 'td'
        html.append('<tr>')
        for ci in range(n_cols):
            cell = row_cells.get(ci, '').strip()
            html.append(f'<{tag}>{_esc(cell)}</{tag}>')
        html.append('</tr>')

    html.append('</tbody></table></div></div>')
    return '\n'.join(html)


def _has_digit(s):
    import re
    return bool(re.search(r'\d', s))


def get_db(doc_key):
    db_name = DOC_TO_DB.get(doc_key)
    if not db_name:
        return None
    db_path = DB_DIR / db_name
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def api_index(doc_key):
    conn = get_db(doc_key)
    if not conn:
        return None, 400, "Invalid doc parameter"

    if doc_key in BJ_DOC_KEYS:
        result = _api_index_beijing(conn)
        conn.close()
        return result

    if doc_key in BJ2021_DOC_KEYS:
        result = _api_index_bj2021(conn)
        conn.close()
        return result

    chapters = []
    for row in conn.execute("SELECT * FROM chapter ORDER BY sort_order"):
        chapters.append({
            "id": row["id"],
            "parent_id": row["parent_id"],
            "sort_order": row["sort_order"],
            "level": row["level"],
            "title": row["title"],
            "start_page": row["start_page"],
            "end_page": row["end_page"],
        })

    # Build page->type mapping for continued_table detection
    page_type_map = {}
    for row in conn.execute("SELECT page, page_type, table_id FROM page_index"):
        page_type_map[row["page"]] = (row["page_type"], row["table_id"])

    tables = []
    prev_table = None
    for row in conn.execute(
        "SELECT qt.*, ch.title as chapter_title FROM norms_table qt "
        "LEFT JOIN chapter ch ON qt.chapter_id = ch.id "
        "ORDER BY qt.page, qt.seq_on_page"
    ):
        entry = {
            "id": row["id"],
            "chapter_id": row["chapter_id"],
            "chapter_title": row["chapter_title"] or "",
            "section_title": row["section_title"] or "",
            "subsection_title": row["subsection_title"] or "",
            "subsection_clean": "",
            "work_content": row["work_content"] or "",
            "unit": row["unit"] or "",
            "page": row["page"],
            "seq_on_page": row["seq_on_page"],
            "row_count": row["row_count"],
            "col_count": row["col_count"],
        }

        pt, _ = page_type_map.get(row["page"], ("", None))
        if pt == "continued_table" and not entry["subsection_title"] and prev_table:
            entry["section_title"] = prev_table["section_title"]
            entry["subsection_title"] = prev_table["subsection_title"]
            entry["chapter_title"] = prev_table["chapter_title"]

        entry["subsection_clean"] = entry["subsection_title"].lstrip("一二三四五六七八九十、")
        tables.append(entry)
        prev_table = entry

    pages = []
    for row in conn.execute(
        "SELECT pi.*, ch.title as chapter_title FROM page_index pi "
        "LEFT JOIN chapter ch ON pi.chapter_id = ch.id "
        "ORDER BY pi.page"
    ):
        pages.append({
            "page": row["page"],
            "page_type": row["page_type"],
            "chapter_id": row["chapter_id"],
            "chapter_title": row["chapter_title"] or "",
            "table_id": row["table_id"],
            "text_preview": row["text_preview"] or "",
        })

    code_index = {}
    for trow in conn.execute("SELECT id FROM norms_table"):
        tid = trow["id"]
        for row in conn.execute(
            "SELECT DISTINCT norms_code FROM norms_item WHERE table_id = ?", (tid,)
        ):
            code = row["norms_code"]
            if code:
                code_index[code] = tid

    conn.close()

    return {
        "chapters": chapters,
        "tables": tables,
        "pages": pages,
        "code_index": code_index,
    }, 200, None


def api_items(doc_key, table_id):
    conn = get_db(doc_key)
    if not conn:
        return None, 400, "Invalid doc parameter"

    if doc_key in BJ_DOC_KEYS:
        result = _api_items_beijing(conn, table_id)
        conn.close()
        return result

    if doc_key in BJ2021_DOC_KEYS:
        result = _api_items_bj2021(conn, table_id)
        conn.close()
        return result

    items = []
    for row in conn.execute(
        "SELECT * FROM norms_item WHERE table_id = ? ORDER BY sort_order",
        (table_id,),
    ):
        items.append({
            "norms_code": row["norms_code"],
            "attr_level1": row["attr_level1"] or "",
            "attr_level2": row["attr_level2"] or "",
            "attr_level3": row["attr_level3"] or "",
            "attr_level4": row["attr_level4"] or "",
            "attr1_label": row["attr1_label"] or "",
            "attr2_label": row["attr2_label"] or "",
            "attr3_label": row["attr3_label"] or "",
            "attr4_label": row["attr4_label"] or "",
            "cost_item": row["cost_item"],
            "cost_item_unit": row["cost_item_unit"] or "",
            "amount": row["amount"],
        })

    conn.close()
    return items, 200, None


def _bj_chapter_level(chap_code):
    if not chap_code:
        return 1
    return chap_code.count('.') + 1


def _api_index_beijing(conn):
    chapters = []
    for row in conn.execute("SELECT * FROM chapter ORDER BY chap_ID"):
        # chap_Content 承载企业定额的项目特征/计量规则/工作内容等扩展说明
        content = ""
        try:
            content = row["chap_Content"] or ""
        except (IndexError, KeyError):
            content = ""
        chapters.append({
            "id": row["chap_ID"],
            "parent_id": row["chap_PID"],
            "sort_order": row["chap_ID"],
            "level": _bj_chapter_level(row["chap_code"] or ""),
            "title": row["chap_Name"],
            "content": content,
            "start_page": None,
            "end_page": None,
        })

    tables = []
    for row in conn.execute("""
        SELECT c.chap_ID, c.chap_Name, COUNT(n.norm_ID) as row_count
        FROM chapter c
        JOIN Norm n ON n.chap_ID = c.chap_ID
        GROUP BY c.chap_ID
        ORDER BY c.chap_ID
    """):
        tables.append({
            "id": row["chap_ID"],
            "chapter_id": row["chap_ID"],
            "chapter_title": row["chap_Name"],
            "section_title": "",
            "subsection_title": row["chap_Name"],
            "subsection_clean": "",
            "work_content": "",
            "unit": "",
            "page": 0,
            "seq_on_page": 0,
            "row_count": row["row_count"],
            "col_count": 0,
        })

    code_index = {}
    for row in conn.execute("SELECT norm_Code, chap_ID FROM Norm"):
        code = row["norm_Code"]
        if code:
            code_index[code] = row["chap_ID"]

    return {
        "chapters": chapters,
        "tables": tables,
        "pages": [],
        "code_index": code_index,
    }, 200, None


def _api_items_beijing(conn, table_id):
    items = []
    sort_order = 0

    for row in conn.execute(
        "SELECT * FROM Norm WHERE chap_ID = ? ORDER BY norm_SortID, norm_Code",
        (table_id,),
    ):
        norm_id = row["norm_ID"]
        code = row["norm_Code"]
        name = row["norm_Name"] or ""
        unit = row["norm_Units"] or ""
        specialty = row["norm_Specialty"] or ""
        man = row["norm_ManPrice"] or 0
        mat = row["norm_MaterialPrice"] or 0
        mach = row["norm_MachinePrice"] or 0
        other = row["norm_OtherPrice"] or 0
        main_mat = row["norm_MainMaterialPrice"] or 0
        equip = row["norm_EquipmentPrice"] or 0
        base = man + mat + mach + other

        base_attrs = {
            "norms_code": code,
            "attr_level1": name,
            "attr_level2": specialty,
            "attr_level3": "",
            "attr_level4": "",
            "attr1_label": "项目名称",
            "attr2_label": "专业",
            "attr3_label": "",
            "attr4_label": "",
        }

        # Name row: the norm itself
        sort_order += 1
        items.append({
            **base_attrs,
            "cost_item": name,
            "cost_item_unit": unit,
            "amount": round(base, 4),
            "sort_order": sort_order,
        })

        # Sub-items: Content → Consumption (resource consumption)
        for cr in conn.execute(
            """SELECT cs.cons_Name, cs.cons_Units, cs.cons_Price,
                      ct.cont_Amount, cs.cons_Style
               FROM Content ct
               JOIN Consumption cs ON cs.cons_ID = ct.cons_ID
               WHERE ct.norm_ID = ?
               ORDER BY ct.cont_ID""",
            (norm_id,),
        ):
            sort_order += 1
            resource_name = cr["cons_Name"] or ""
            resource_unit = cr["cons_Units"] or ""
            unit_price = cr["cons_Price"] or 0
            quantity = cr["cont_Amount"] or 0
            style = cr["cons_Style"] or 0

            # Determine label based on cons_Style (3=labor, 4=material, 5=machinery)
            if style == 3:
                label = "人工"
            elif style == 4:
                label = "材料"
            elif style == 5:
                label = "机械"
            else:
                label = ""

            items.append({
                **base_attrs,
                "cost_item": resource_name,
                "cost_item_unit": resource_unit,
                "amount": round(quantity, 6),
                "sort_order": sort_order,
                "attr_level3": label,
            })

        # Price summary rows (only 人工费/材料费/机械费 used by frontend main table)
        price_items = [
            ("人工费", man),
            ("材料费", mat),
            ("机械费", mach),
        ]
        for cost_name, amount in price_items:
            if amount == 0:
                continue
            sort_order += 1
            items.append({
                **base_attrs,
                "cost_item": cost_name,
                "cost_item_unit": "元",
                "amount": round(amount, 4),
                "sort_order": sort_order,
            })

    return items, 200, None


def _api_index_bj2021(conn):
    """2021版房屋建筑与装饰工程消耗量标准 index API"""
    chapters = []
    for row in conn.execute("SELECT * FROM chapters ORDER BY chapter_no"):
        chapters.append({
            "id": row["id"],
            "parent_id": 0,
            "sort_order": row["chapter_no"],
            "level": 1,
            "title": f'第{row["chapter_no"]}章 {row["title"]}',
            "start_page": row["start_page"],
            "end_page": None,
        })

    # Each section = one table entry; each unique subitem_title within
    # a section also gets its own table entry for finer-grained display
    tables = []
    code_index = {}
    cur = conn.execute("""
        SELECT s.id as section_id, s.section_no, s.title as section_title,
               s.start_page, c.id as chapter_id, c.title as chapter_title,
               c.chapter_no
        FROM sections s
        JOIN chapters c ON s.chapter_id = c.id
        ORDER BY c.chapter_no, s.section_no
    """)
    sections = cur.fetchall()

    # Add sections as level-2 child chapters so the sidebar shows hierarchy
    for sec in sections:
        chapters.append({
            "id": 10000 + sec["section_id"],
            "parent_id": sec["chapter_id"],
            "sort_order": sec["section_no"],
            "level": 2,
            "title": sec["section_title"],
            "start_page": sec["start_page"],
            "end_page": None,
        })

    for sec in sections:
        # Count items in this section
        cnt_row = conn.execute(
            "SELECT COUNT(*) FROM quota_items WHERE section_id = ?",
            (sec["section_id"],)
        ).fetchone()
        row_count = cnt_row[0] if cnt_row else 0

        # Get distinct subitem titles for grouping
        subitems = conn.execute(
            "SELECT DISTINCT subitem_title FROM quota_items WHERE section_id = ? ORDER BY id",
            (sec["section_id"],)
        ).fetchall()

        if len(subitems) <= 1:
            # Single subitem group — one table per section
            subitem_title = subitems[0]["subitem_title"] if subitems else ""
            table_id = sec["section_id"]
            tables.append({
                "id": table_id,
                "chapter_id": 10000 + sec["section_id"],
                "chapter_title": f'第{sec["chapter_no"]}章 {sec["chapter_title"]}',
                "section_title": sec["section_title"],
                "subsection_title": subitem_title,
                "subsection_clean": subitem_title,
                "work_content": "",
                "unit": "",
                "page": sec["start_page"],
                "seq_on_page": sec["section_no"],
                "row_count": row_count,
                "col_count": 0,
            })
            # Build code index
            for ci in conn.execute(
                "SELECT code FROM quota_items WHERE section_id = ?",
                (sec["section_id"],)
            ):
                if ci["code"]:
                    code_index[ci["code"]] = table_id
        else:
            # Multiple subitem groups — one table per subitem
            for si in subitems:
                st = si["subitem_title"]
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM quota_items WHERE section_id = ? AND subitem_title = ?",
                    (sec["section_id"], st)
                ).fetchone()[0]
                # Use a synthetic table ID: section_id * 1000 + subitem index
                si_idx = [s["subitem_title"] for s in subitems].index(st)
                table_id = sec["section_id"] * 1000 + si_idx
                first_item = conn.execute(
                    "SELECT code, page FROM quota_items WHERE section_id = ? AND subitem_title = ? ORDER BY id LIMIT 1",
                    (sec["section_id"], st)
                ).fetchone()
                tables.append({
                    "id": table_id,
                    "chapter_id": 10000 + sec["section_id"],
                    "chapter_title": f'第{sec["chapter_no"]}章 {sec["chapter_title"]}',
                    "section_title": sec["section_title"],
                    "subsection_title": st,
                    "subsection_clean": st,
                    "work_content": "",
                    "unit": "",
                    "page": first_item["page"] if first_item else sec["start_page"],
                    "seq_on_page": sec["section_no"],
                    "row_count": cnt,
                    "col_count": 0,
                })
                for ci in conn.execute(
                    "SELECT code FROM quota_items WHERE section_id = ? AND subitem_title = ?",
                    (sec["section_id"], st)
                ):
                    if ci["code"]:
                        code_index[ci["code"]] = table_id

    return {
        "chapters": chapters,
        "tables": tables,
        "pages": [],
        "code_index": code_index,
    }, 200, None


def _api_items_bj2021(conn, table_id):
    """2021版房屋建筑与装饰工程消耗量标准 items API"""
    items = []
    sort_order = 0

    # Determine if table_id is a section-level or subitem-level ID
    if table_id >= 1000:
        section_id = table_id // 1000
        si_idx = table_id % 1000
        subitems = conn.execute(
            "SELECT DISTINCT subitem_title FROM quota_items WHERE section_id = ? ORDER BY id",
            (section_id,)
        ).fetchall()
        if si_idx < len(subitems):
            target_subitem = subitems[si_idx]["subitem_title"]
        else:
            target_subitem = None
    else:
        section_id = table_id
        target_subitem = None

    if target_subitem:
        rows = conn.execute(
            "SELECT * FROM quota_items WHERE section_id = ? AND subitem_title = ? ORDER BY id",
            (section_id, target_subitem)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM quota_items WHERE section_id = ? ORDER BY id",
            (section_id,)
        ).fetchall()

    for qi in rows:
        sort_order += 1
        code = qi["code"] or ""
        item_name = qi["item_name"] or ""
        work_unit = qi["work_unit"] or ""
        subitem_title = qi["subitem_title"] or ""
        work_content = qi["work_content"] or ""

        items.append({
            "norms_code": code,
            "attr_level1": subitem_title,
            "attr_level2": item_name,
            "attr_level3": work_content,
            "attr_level4": "",
            "attr1_label": "分类",
            "attr2_label": "项目名称",
            "attr3_label": "工作内容",
            "attr4_label": "",
            "cost_item": item_name,
            "cost_item_unit": work_unit,
            "amount": 0,
            "sort_order": sort_order,
        })

        # Add consumption sub-rows
        consumptions = conn.execute(
            "SELECT * FROM quota_consumptions WHERE quota_item_id = ? ORDER BY category, id",
            (qi["id"],)
        ).fetchall()

        for c in consumptions:
            sort_order += 1
            cat_label = {"人工": "人工", "材料": "材料", "机械": "机械"}.get(c["category"], c["category"])
            items.append({
                "norms_code": code,
                "attr_level1": subitem_title,
                "attr_level2": c["resource_name"] or "",
                "attr_level3": cat_label,
                "attr_level4": c["resource_code"] or "",
                "attr1_label": "分类",
                "attr2_label": "资源名称",
                "attr3_label": "类别",
                "attr4_label": "资源编码",
                "cost_item": c["resource_name"] or "",
                "cost_item_unit": c["resource_unit"] or "",
                "amount": round(c["quantity"], 6) if c["quantity"] is not None else 0,
                "sort_order": sort_order,
            })

    return items, 200, None


def api_text(doc_key, page):
    conn = get_db(doc_key)
    if not conn:
        return None, 400, "Invalid doc parameter"

    row = conn.execute(
        "SELECT page, type, content FROM section_text WHERE page = ?", (page,)
    ).fetchone()

    conn.close()

    if not row:
        return None, 404, "Page not found"

    return {
        "page": row["page"],
        "type": row["type"],
        "content": row["content"],
    }, 200, None


def api_text_html(doc_key, page):
    html = text_page_to_html(page)
    if html is None:
        return None, 404, "Raw text data not found for this page"

    return {"page": page, "html": html}, 200, None


def _build_notes_table_html(notes_table):
    """Convert parsed notes table rows to HTML."""
    if not notes_table or not notes_table.get('rows'):
        return ''
    rows = notes_table['rows']
    # Build HTML table
    html = '<table class="notes-data-table"><thead><tr>'
    # Header row (first row name + values)
    html += '<th>' + rows[0]['name'] + '</th>'
    for v in rows[0].get('values', []):
        html += '<th>' + v + '</th>'
    html += '</tr></thead><tbody>'
    for row in rows[1:]:
        html += '<tr><td class="row-label">' + row['name'] + '</td>'
        for v in row.get('values', []):
            html += '<td>' + v + '</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


def api_table_header(doc_key, table_id):
    """Return the full header_json for a norms_table."""
    conn = get_db(doc_key)
    if not conn:
        return {}, 404, "Table not found"

    if doc_key in BJ2021_DOC_KEYS:
        conn.close()
        return {}, 200, None

    try:
        row = conn.execute(
            "SELECT header_json FROM norms_table WHERE id = ?", (table_id,)
        ).fetchone()
        conn.close()
        if row and row["header_json"]:
            return json.loads(row["header_json"]), 200, None
    except:
        conn.close()
    return {}, 404, "Table not found"


def api_notes(doc_key, page):
    """Read notes from DB header_json. Works for both PDF and Excel imports."""
    conn = get_db(doc_key)
    if conn:
        try:
            cur = conn.execute(
                "SELECT header_json FROM norms_table WHERE id = "
                "(SELECT table_id FROM page_index WHERE page = ?)", (int(page),))
            row = cur.fetchone()
            if row:
                h = json.loads(row[0])
                notes_list = h.get('notes', [])
                if notes_list:
                    text = '<br>'.join(
                        n.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                        for n in notes_list)
                    return {'notes': text, 'notes_html': text}
        except:
            pass
    return {'notes': '', 'notes_html': ''}

class APIHandler(http.server.SimpleHTTPRequestHandler):
    """Serves static files from cwd, with /api/ routes for SQLite queries."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".json": "application/json",
        ".html": "text/html; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
    }

    def log_message(self, format, *args):
        pass  # suppress access log noise

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/index":
            try:
                doc_key = params.get("doc", [None])[0]
                if not doc_key:
                    self.send_error_json(400, "Missing doc parameter")
                    return
                data, status, err = api_index(doc_key)
                if err:
                    self.send_error_json(status, err)
                    return
                self.send_json(data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_error_json(500, str(e))

        elif path == "/api/items":
            doc_key = params.get("doc", [None])[0]
            table_id_str = params.get("table_id", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not table_id_str:
                self.send_error_json(400, "Missing table_id parameter")
                return
            try:
                table_id = int(table_id_str)
            except ValueError:
                self.send_error_json(400, "Invalid table_id")
                return
            data, status, err = api_items(doc_key, table_id)
            if err:
                self.send_error_json(status, err)
                return
            self.send_json(data)

        elif path == "/api/text":
            doc_key = params.get("doc", [None])[0]
            page_str = params.get("page", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not page_str:
                self.send_error_json(400, "Missing page parameter")
                return
            try:
                page = int(page_str)
            except ValueError:
                self.send_error_json(400, "Invalid page")
                return
            data, status, err = api_text(doc_key, page)
            if err:
                self.send_error_json(status, err)
                return
            self.send_json(data)

        elif path == "/api/notes":
            doc_key = params.get("doc", [None])[0]
            page_str = params.get("page", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not page_str:
                self.send_error_json(400, "Missing page parameter")
                return
            try:
                page = int(page_str)
            except ValueError:
                self.send_error_json(400, "Invalid page")
                return
            data = api_notes(doc_key, page)
            self.send_json(data)

        elif path == "/api/table-header":
            doc_key = params.get("doc", [None])[0]
            table_id_str = params.get("table_id", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not table_id_str:
                self.send_error_json(400, "Missing table_id")
                return
            try:
                table_id = int(table_id_str)
            except ValueError:
                self.send_error_json(400, "Invalid table_id")
                return
            data, status, err = api_table_header(doc_key, table_id)
            if err:
                self.send_error_json(status, err)
                return
            self.send_json(data)

        elif path == "/api/text-html":
            doc_key = params.get("doc", [None])[0]
            page_str = params.get("page", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not page_str:
                self.send_error_json(400, "Missing page parameter")
                return
            try:
                page = int(page_str)
            except ValueError:
                self.send_error_json(400, "Invalid page")
                return
            data, status, err = api_text_html(doc_key, page)
            if err:
                self.send_error_json(status, err)
                return
            self.send_json(data)

        else:
            super().do_GET()


def main():
    parser = argparse.ArgumentParser(description="启动定额浏览器")
    parser.add_argument("--port", type=int, default=8080, help="HTTP端口 (默认: 8080)")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    if not OUTPUT_DIR.exists():
        print(f"错误: output/ 目录不存在: {OUTPUT_DIR}")
        sys.exit(1)

    os.chdir(str(OUTPUT_DIR))

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    url = f"http://localhost:{args.port}/norms_browser.html"

    try:
        with ReusableTCPServer(("0.0.0.0", args.port), APIHandler) as httpd:
            print(f"\n  定额浏览器已启动")
            print(f"  {url}\n")
            print(f"  按 Ctrl+C 停止服务\n")

            if not args.no_open:
                def _open():
                    webbrowser.open(url)
                threading.Timer(0.5, _open).start()

            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n服务已停止")
    except OSError as e:
        if hasattr(e, 'winerror') and e.winerror == 10048 or 'Address already in use' in str(e):
            print(f"  端口 {args.port} 已被占用，请先关闭占用进程或使用其他端口:")
            print(f"    python start.py --port {args.port + 100}")
            try:
                subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, timeout=5
                )
            except Exception:
                pass
        else:
            print(f"  启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
