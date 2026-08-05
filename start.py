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

# 企业定额BOQ模式（无norms_table表，使用Norm/Content/Consumption schema）
ENT_BOQ_DOC_KEYS = {"ent_a_building", "ent_b_mechanical", "ent_c_municipal", "ent_d_water"}

# NRM2 原版清单库（英国清单规范，只读）+ 映射来源的企业定额册
NRM2_DB = Path(r'f:/BaiduSyncdisk/2.清单定额/3 清单规范/英国清单/PART3 nrm_2.sqlite')
NRM2_BEIJING_DOCS = ["ent_a_building", "ent_b_mechanical", "ent_c_municipal"]


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
    # NRM 库复用对应企业定额册的数据库文件
    if doc_key.startswith('nrm_'):
        doc_key = doc_key[len('nrm_'):]
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
    if doc_key == 'nrm2':
        return _api_nrm2_index()

    conn = get_db(doc_key)
    if not conn:
        return None, 400, "Invalid doc parameter"

    if doc_key.startswith('nrm_'):
        result = _api_nrm_index_beijing(conn)
        conn.close()
        return result

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
    if doc_key == 'nrm2':
        return _api_nrm2_items_agg(table_id)

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
    import re
    code = re.sub(r'^[A-Z]\.', '', chap_code)
    return code.count('.') + 1


def _api_index_beijing(conn):
    chapters = []
    for row in conn.execute("SELECT * FROM chapter ORDER BY chap_ID"):
        # chap_Content 承载企业定额的项目特征/计量规则/工作内容等扩展说明
        content = ""
        content_en = ""
        try:
            content = row["chap_Content"] or ""
        except (IndexError, KeyError):
            content = ""
        try:
            content_en = row["chap_Content_EN"] or ""
        except (IndexError, KeyError):
            content_en = ""
        chapters.append({
            "id": row["chap_ID"],
            "parent_id": row["chap_PID"],
            "sort_order": row["chap_ID"],
            "level": _bj_chapter_level(row["chap_code"] or ""),
            "title": row["chap_Name"],
            "title_en": row["chap_Name_EN"] or "",
            "content": content,
            "content_en": content_en,
            "start_page": None,
            "end_page": None,
        })

    tables = []
    # Build recursive Norm count map so chapters at all levels show up
    direct_norm = {}
    for r in conn.execute("SELECT chap_ID, COUNT(*) FROM Norm GROUP BY chap_ID"):
        direct_norm[r[0]] = r[1]
    chap_children = {}
    for r in conn.execute("SELECT chap_ID, chap_PID FROM chapter"):
        pid = r["chap_PID"]
        if pid not in chap_children:
            chap_children[pid] = []
        chap_children[pid].append(r["chap_ID"])
    _rc_cache = {}
    def _recursive_norm(chap_id):
        if chap_id in _rc_cache:
            return _rc_cache[chap_id]
        total = direct_norm.get(chap_id, 0)
        for cid in chap_children.get(chap_id, []):
            total += _recursive_norm(cid)
        _rc_cache[chap_id] = total
        return total
    for r in conn.execute("SELECT chap_ID FROM chapter"):
        _recursive_norm(r["chap_ID"])

    # Build parent-of lookup for fallback count (mirrors _beijing_norm_items
    # L3→L2 fallback: if a leaf chapter has no norms itself, clicking it
    # still shows its parent's norms via the /api/items endpoint)
    chap_PID_of = {}
    for r in conn.execute("SELECT chap_ID, chap_PID FROM chapter"):
        chap_PID_of[r["chap_ID"]] = r["chap_PID"]

    for row in conn.execute("SELECT * FROM chapter ORDER BY chap_ID"):
        cid = row["chap_ID"]
        count = _rc_cache.get(cid, 0)
        # If leaf has no norms but parent does, use parent's count
        # so the badge in the tree matches what the user sees on click
        effective = count
        if effective == 0:
            pid = chap_PID_of.get(cid)
            if pid and pid != 0:
                effective = direct_norm.get(pid, 0)
        if effective > 0:
            tables.append({
                "id": cid,
                "chapter_id": cid,
                "chapter_title": row["chap_Name"],
                "chapter_title_en": row["chap_Name_EN"] or "",
                "section_title": "",
                "subsection_title": row["chap_Name"],
                "subsection_title_en": row["chap_Name_EN"] or "",
                "subsection_clean": "",
                "work_content": "",
                "unit": "",
                "page": 0,
                "seq_on_page": 0,
                "row_count": effective,
                "col_count": 0,
            })
        else:
            # Leaf chapters without Norms (and without parent norms)
            # still need a table entry so the frontend tree can render
            # them as navigable (shows chapter metadata card).
            pid = row["chap_PID"]
            has_children = pid in chap_children and bool(chap_children.get(cid))
            if not has_children and pid != 0:
                tables.append({
                    "id": cid,
                    "chapter_id": cid,
                    "chapter_title": row["chap_Name"],
                    "chapter_title_en": row["chap_Name_EN"] or "",
                    "section_title": "",
                    "subsection_title": row["chap_Name"],
                    "subsection_title_en": row["chap_Name_EN"] or "",
                    "subsection_clean": "",
                    "work_content": "",
                    "unit": "",
                    "page": 0,
                    "seq_on_page": 0,
                    "row_count": 0,
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
    return _beijing_norm_items(conn, table_id), 200, None


def _beijing_norm_items(conn, table_id):
    """返回企业定额 schema 下一个章节的全部 Norm 子目（含资源消耗与价格行）。
    L3 叶子节点无直接定额时，回退到父级 L2 的定额。
    """
    items = []
    sort_order = 0

    rows = conn.execute(
        "SELECT * FROM Norm WHERE chap_ID = ? ORDER BY norm_SortID, norm_Code",
        (table_id,),
    ).fetchall()

    if not rows:
        ch = conn.execute(
            "SELECT chap_PID FROM chapter WHERE chap_ID = ?", (table_id,)
        ).fetchone()
        if ch and ch["chap_PID"]:
            rows = conn.execute(
                "SELECT * FROM Norm WHERE chap_ID = ? ORDER BY norm_SortID, norm_Code",
                (ch["chap_PID"],),
            ).fetchall()

    for row in rows:
        norm_id = row["norm_ID"]
        code = row["norm_Code"]
        name = row["norm_Name"] or ""
        name_en = row["norm_Name_EN"] or ""
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
            "attr1_label_en": "Item Name",
            "attr2_label": "专业",
            "attr2_label_en": "Discipline",
            "attr3_label": "",
            "attr3_label_en": "",
            "attr4_label": "",
            "attr4_label_en": "",
        }

        # Name row: the norm itself
        sort_order += 1
        items.append({
            **base_attrs,
            "cost_item": name,
            "cost_item_en": name_en,
            "cost_item_unit": unit,
            "amount": round(base, 4),
            "sort_order": sort_order,
        })

        # Sub-items: Content → Consumption (resource consumption)
        for cr in conn.execute(
            """SELECT cs.cons_Name, cs.cons_Name_EN, cs.cons_Units, cs.cons_Units_EN,
                      cs.cons_Price, ct.cont_Amount, cs.cons_Style
               FROM Content ct
               JOIN Consumption cs ON cs.cons_ID = ct.cons_ID
               WHERE ct.norm_ID = ?
               ORDER BY ct.cont_ID""",
            (norm_id,),
        ):
            sort_order += 1
            resource_name = cr["cons_Name"] or ""
            resource_name_en = cr["cons_Name_EN"] or ""
            resource_unit = cr["cons_Units"] or ""
            resource_unit_en = cr["cons_Units_EN"] or ""
            unit_price = cr["cons_Price"] or 0
            quantity = cr["cont_Amount"] or 0
            style = cr["cons_Style"] or 0

            # Determine label based on cons_Style (3=labor, 4=material, 5=machinery)
            if style == 3:
                label = "人工"
                label_en = "Labour"
            elif style == 4:
                label = "材料"
                label_en = "Material"
            elif style == 5:
                label = "机械"
                label_en = "Machinery"
            else:
                label = ""
                label_en = ""

            items.append({
                **base_attrs,
                "cost_item": resource_name,
                "cost_item_en": resource_name_en,
                "cost_item_unit": resource_unit,
                "cost_item_unit_en": resource_unit_en,
                "amount": round(quantity, 6),
                "sort_order": sort_order,
                "attr_level3": label,
                "attr_level3_en": label_en,
            })

        # Price summary rows (only 人工费/材料费/机械费 used by frontend main table)
        price_items = [
            ("人工费", "Labour Cost", man),
            ("材料费", "Material Cost", mat),
            ("机械费", "Machinery Cost", mach),
        ]
        for cost_name, cost_name_en, amount in price_items:
            if amount == 0:
                continue
            sort_order += 1
            items.append({
                **base_attrs,
                "cost_item": cost_name,
                "cost_item_en": cost_name_en,
                "cost_item_unit": "元",
                "amount": round(amount, 4),
                "sort_order": sort_order,
            })

    return items


def _beijing_norm_rows(conn, table_id):
    """返回一个章节下全部 Norm 定额子目（每行一个子目，含综合价）。"""
    rows = []
    for r in conn.execute(
        "SELECT * FROM Norm WHERE chap_ID = ? ORDER BY norm_SortID, norm_Code",
        (table_id,),
    ):
        man = r["norm_ManPrice"] or 0
        mat = r["norm_MaterialPrice"] or 0
        mach = r["norm_MachinePrice"] or 0
        other = r["norm_OtherPrice"] or 0
        rows.append({
            "norms_code": r["norm_Code"],
            "name": r["norm_Name"] or "",
            "name_en": r["norm_Name_EN"] or "",
            "unit": r["norm_Units"] or "",
            "amount": round(man + mat + mach + other, 4),
        })
    return rows


def _nrm_prefix(code):
    """从 NRM 代码前缀解析二级章节代码，如 'A.05.01.501' → '05.01'。"""
    import re
    m = re.match(r'^[A-Z]\.(\d{2})\.(\d{2})', code or '')
    return m.group(1) + '.' + m.group(2) if m else None


def _nrm_mapped_chap_ids(conn, prefix):
    """返回 NRM 前缀对应的二级章节下所有直接含 Norm 的三级章节 chap_ID。"""
    if not prefix:
        return []
    rows = conn.execute(
        "SELECT chap_ID FROM chapter WHERE chap_code LIKE ?",
        (prefix + '.%',),
    ).fetchall()
    return [r["chap_ID"] for r in rows]


def _api_nrm_index_beijing(conn):
    """返回 NRM 库结构：nrm_section_title 分组 → nrm_item 列表（含映射章节的 Norm 计数）。"""
    has_nrm = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nrm_item'"
    ).fetchone()
    if not has_nrm:
        return {"sections": [], "total": 0}, 200, None

    # 预取各三级章 Norm 计数
    norm_count_by_chap = {}
    for r in conn.execute("SELECT chap_ID, COUNT(*) as cnt FROM Norm GROUP BY chap_ID"):
        norm_count_by_chap[r["chap_ID"]] = r["cnt"]

    sections = []
    sec_index = {}
    total = 0
    for row in conn.execute("SELECT * FROM nrm_item ORDER BY code"):
        prefix = _nrm_prefix(row["code"])
        chap_ids = _nrm_mapped_chap_ids(conn, prefix)
        norm_count = sum(norm_count_by_chap.get(cid, 0) for cid in chap_ids)
        item = {
            "code": row["code"],
            "name": row["name"] or "",
            "name_zh": row["name_ZH"] or "",
            "unit": row["unit"] or "",
            "norm_count": norm_count,
            "level_one": row["level_one"] or "",
            "level_two": row["level_two"] or "",
            "level_three": row["level_three"] or "",
            "level_one_zh": row["level_one_ZH"] or "",
            "level_two_zh": row["level_two_ZH"] or "",
            "notes": row["notes"] or "",
        }
        total += norm_count
        sec_key = row["nrm_section_title"] or ""
        sec_zh = row["nrm_section_title_ZH"] or sec_key
        if sec_key not in sec_index:
            sec_index[sec_key] = {"title": sec_key, "title_zh": sec_zh, "items": []}
            sections.append(sec_index[sec_key])
        sec_index[sec_key]["items"].append(item)

    return {"sections": sections, "total": total}, 200, None


def _api_nrm_items_beijing(conn, nrm_code):
    """返回 NRM 项映射的定额子目（聚合其前缀二级章节下全部三级章的 Norm 行）。"""
    row = conn.execute("SELECT * FROM nrm_item WHERE code = ?", (nrm_code,)).fetchone()
    if not row:
        return None, 404, "NRM item not found"

    prefix = _nrm_prefix(nrm_code)
    chap_ids = _nrm_mapped_chap_ids(conn, prefix)

    all_items = []
    for cid in chap_ids:
        all_items.extend(_beijing_norm_items(conn, cid))

    # 返回 NRM 元信息 + 聚合子目，前端可复用 BOQ 渲染
    return {
        "nrm": {
            "code": row["code"],
            "name": row["name"] or "",
            "name_zh": row["name_ZH"] or "",
            "unit": row["unit"] or "",
            "section_title": row["nrm_section_title"] or "",
            "section_title_zh": row["nrm_section_title_ZH"] or "",
            "level_one": row["level_one"] or "",
            "level_two": row["level_two"] or "",
            "level_three": row["level_three"] or "",
            "level_one_zh": row["level_one_ZH"] or "",
            "level_two_zh": row["level_two_ZH"] or "",
            "notes": row["notes"] or "",
        },
        "items": all_items,
        "norm_count": len(all_items),
    }, 200, None


# ── NRM2 原版库：section→item→企业定额 分部→章→分项 深树，分项为叶子 ──
_nrm2_index_cache = None
_nrm2_table_map = {}   # table_id -> (doc_key, chap_id)，供 /api/items 反查


def _nrm2_index():
    """构建 A 册格式 index：NRM2 section→item→企业定额 章→分项。"""
    global _nrm2_index_cache, _nrm2_table_map
    if _nrm2_index_cache is not None:
        return _nrm2_index_cache
    if not NRM2_DB.exists():
        _nrm2_index_cache = {"chapters": [], "tables": [], "pages": [], "code_index": {}}
        return _nrm2_index_cache

    orig = sqlite3.connect(str(NRM2_DB))
    orig.row_factory = sqlite3.Row

    doc_conns = {}
    norm_count_by_chap = {}
    chap_by_id = {}
    by_ref = {}
    for dk in NRM2_BEIJING_DOCS:
        conn = get_db(dk)
        if conn is None:
            continue
        doc_conns[dk] = conn
        norm_count_by_chap[dk] = {
            r["chap_ID"]: r["cnt"]
            for r in conn.execute("SELECT chap_ID, COUNT(*) cnt FROM Norm GROUP BY chap_ID")
        }
        chap_by_id[dk] = {r["chap_ID"]: r for r in conn.execute("SELECT * FROM chapter")}
        for r in conn.execute("SELECT * FROM nrm_item"):
            by_ref.setdefault(r["nrm_ref"], []).append((dk, r))

    sec_zh = {}
    for ref, rows in by_ref.items():
        for dk, r in rows:
            sec_zh.setdefault(str(r["nrm_section"]), r["nrm_section_title_ZH"] or "")

    chapters = []
    tables = []
    code_index = {}
    _nrm2_table_map.clear()
    sec_num = 0
    item_index = 0
    node_seq = 0
    cur = None
    for it in orig.execute(
        "SELECT * FROM building_works ORDER BY CAST(section_number AS INTEGER), CAST(item_number AS INTEGER)"
    ):
        sec = str(it["section_number"])
        ref = f"Sec{sec}#{it['item_number']}"
        sec_title = sec_zh.get(sec, "") or it["section_title"] or ""
        if cur is None or cur["number"] != sec:
            sec_num += 1
            sec_id = 10000 + sec_num
            cur = {"number": sec, "id": sec_id}
            chapters.append({
                "id": sec_id,
                "parent_id": 0,
                "sort_order": sec_num,
                "level": 1,
                "title": f"{sec} {sec_title}",
                "title_en": f"{sec} {it['section_title'] or ''}",
                "content": "",
                "start_page": None,
                "end_page": None,
            })
        name_zh = ""
        unit = it["unit"] or ""
        for dk, r in by_ref.get(ref, []):
            if not name_zh and r["name_ZH"]:
                name_zh = r["name_ZH"]

        item_index += 1
        item_id = 20000 + item_index
        item_name_zh = name_zh or it["item_name"] or ""
        chapters.append({
            "id": item_id,
            "parent_id": cur["id"],
            "sort_order": item_index,
            "level": 2,
            "title": f"{sec}.{it['item_number']} {item_name_zh}",
            "title_en": f"{sec}.{it['item_number']} {it['item_name'] or ''}",
            "content": "",
            "start_page": None,
            "end_page": None,
        })

        # ── item 映射的企业定额子树（章→分项），空分项剔除 ──
        nodes = {}
        for dk, r in by_ref.get(ref, []):
            conn = doc_conns.get(dk)
            if conn is None:
                continue
            prefix = _nrm_prefix(r["code"])
            if not prefix:
                continue
            for cid in _nrm_mapped_chap_ids(conn, prefix):
                if norm_count_by_chap[dk].get(cid, 0) == 0:
                    continue
                cur_id = cid
                while cur_id and cur_id != 0:
                    prow = chap_by_id[dk].get(cur_id)
                    if prow is None:
                        break
                    # 分部（chap_PID==0）不加入，item 下直接挂 章→分项
                    pid = prow["chap_PID"] or 0
                    if pid == 0:
                        break
                    nodes[(dk, cur_id)] = prow
                    cur_id = pid

        if not nodes:
            continue

        kids = {}
        for (dk2, cid2), row in nodes.items():
            pid = row["chap_PID"] or 0
            if pid and pid != 0 and (dk2, pid) not in nodes:
                # 父节点是已移除的 分部 → 直接挂到 item 下
                kids.setdefault(('item',), []).append((dk2, cid2))
            else:
                kids.setdefault(('item',) if not pid or pid == 0 else (dk2, pid), []).append((dk2, cid2))

        code_index[f"{sec}.{it['item_number']}"] = item_id

        def _code_parts(chap_code):
            import re
            c = re.sub(r'^[A-Z]\.', '', chap_code or '')
            try:
                return [int(x) for x in c.split('.')]
            except ValueError:
                return [999]

        def _emit(parent_key, parent_id):
            nonlocal node_seq
            order = 0
            for (dk3, cid3) in sorted(
                kids.get(parent_key, []),
                key=lambda k: (_code_parts(chap_by_id[k[0]][k[1]]["chap_code"]), k[0]),
            ):
                row3 = chap_by_id[dk3][cid3]
                c3 = row3["chap_code"] or ""
                parts = _code_parts(c3)
                if len(parts) < 3:
                    # 章 — 不在树中显示，子节点直接挂到当前 parent
                    _emit((dk3, cid3), parent_id)
                else:
                    order += 1
                    node_seq += 1
                    nid = 30000 + node_seq
                    chapters.append({
                        "id": nid,
                        "parent_id": parent_id,
                        "sort_order": order,
                        "level": 3,
                        "title": row3["chap_Name"] or "",
                        "title_en": row3["chap_Name_EN"] or "",
                        "content": row3["chap_Content"] or "",
                        "start_page": None,
                        "end_page": None,
                    })
                    tables.append({
                        "id": nid,
                        "chapter_id": nid,
                        "chapter_title": row3["chap_Name"] or "",
                        "chapter_title_en": row3["chap_Name_EN"] or "",
                        "section_title": sec_title,
                        "section_title_en": it["section_title"] or "",
                        "subsection_title": row3["chap_Name"] or "",
                        "subsection_title_en": row3["chap_Name_EN"] or "",
                        "subsection_clean": "",
                        "work_content": "",
                        "unit": unit,
                        "page": 0,
                        "seq_on_page": 0,
                        "row_count": norm_count_by_chap[dk3].get(cid3, 0),
                        "col_count": 0,
                    })
                    _nrm2_table_map[nid] = (dk3, cid3)
                    code_index[c3] = nid
                    _emit((dk3, cid3), parent_id)

        _emit(('item',), item_id)

    for c in doc_conns.values():
        c.close()
    orig.close()
    _nrm2_index_cache = {
        "chapters": chapters,
        "tables": tables,
        "pages": [],
        "code_index": code_index,
    }
    return _nrm2_index_cache


def _api_nrm2_index():
    return _nrm2_index(), 200, None


def _api_nrm2_items_agg(table_id):
    """返回单个企业定额分项的定额子目展开行（与 A 册 selectChapter 相同的 items 格式）。"""
    _nrm2_index()  # 确保 _nrm2_table_map 已构建
    key = _nrm2_table_map.get(table_id)
    if key is None:
        return None, 404, "NRM2 item not found"
    dk, chap_id = key
    conn = get_db(dk)
    if conn is None:
        return None, 404, "NRM2 item not found"
    try:
        return _beijing_norm_items(conn, chap_id), 200, None
    finally:
        conn.close()


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
    if doc_key == 'nrm2':
        return {}, 200, None

    conn = get_db(doc_key)
    if not conn:
        return {}, 404, "Table not found"

    if doc_key in BJ2021_DOC_KEYS or doc_key in ENT_BOQ_DOC_KEYS:
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

        elif path == "/api/nrm-index":
            doc_key = params.get("doc", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            conn = get_db(doc_key)
            if not conn:
                self.send_error_json(400, "Invalid doc parameter")
                return
            try:
                base_key = doc_key[len('nrm_'):] if doc_key.startswith('nrm_') else doc_key
                if base_key in BJ_DOC_KEYS:
                    data, status, err = _api_nrm_index_beijing(conn)
                else:
                    data, status, err = {"sections": [], "total": 0}, 200, None
                conn.close()
                if err:
                    self.send_error_json(status, err)
                    return
                self.send_json(data)
            except Exception as e:
                conn.close()
                import traceback
                traceback.print_exc()
                self.send_error_json(500, str(e))

        elif path == "/api/nrm-items":
            doc_key = params.get("doc", [None])[0]
            nrm_code = params.get("nrm_code", [None])[0]
            if not doc_key:
                self.send_error_json(400, "Missing doc parameter")
                return
            if not nrm_code:
                self.send_error_json(400, "Missing nrm_code parameter")
                return
            conn = get_db(doc_key)
            if not conn:
                self.send_error_json(400, "Invalid doc parameter")
                return
            try:
                base_key = doc_key[len('nrm_'):] if doc_key.startswith('nrm_') else doc_key
                if base_key in BJ_DOC_KEYS:
                    data, status, err = _api_nrm_items_beijing(conn, nrm_code)
                else:
                    data, status, err = {"nrm": {}, "items": [], "norm_count": 0}, 200, None
                conn.close()
                if err:
                    self.send_error_json(status, err)
                    return
                self.send_json(data)
            except Exception as e:
                conn.close()
                import traceback
                traceback.print_exc()
                self.send_error_json(500, str(e))

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
